import json, re, statistics, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

ROOT=Path(__file__).parent
DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
CFG=json.loads((ROOT/'config/watchlist.json').read_text(encoding='utf-8'))
FORUM=f"https://forums.d2jsp.org/forum.php?f={CFG['forum_id']}"
RUNE_FORUM=f"https://forums.d2jsp.org/forum.php?f={CFG['forum_id']}&c=2"
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'}
PRICE=r'(\d+(?:\.\d+)?\s*[kK]?)'
COMPLETE=re.compile(r'\b(?:t4t|sold|closed|trade complete)\b',re.I)


def nval(s):
    s=s.strip().replace(' ','')
    mult=1000 if s.lower().endswith('k') else 1
    if mult==1000:s=s[:-1]
    try:v=float(s)*mult
    except:return None
    return v if 0<v<100000 else None


def reader(url,timeout=35,retries=4):
    target='https://r.jina.ai/https://'+url.removeprefix('https://').removeprefix('http://')
    last=None
    for attempt in range(retries):
        try:
            r=requests.get(target,headers=HEADERS,timeout=timeout)
            if r.status_code==429:
                last=f'429 Too Many Requests ({attempt+1}/{retries})'
                time.sleep(2.5*(attempt+1))
                continue
            r.raise_for_status()
            return r.text
        except Exception as e:
            last=str(e)
            if attempt<retries-1: time.sleep(1.5*(attempt+1))
    raise RuntimeError(last or 'reader failed')


def topic_links(md):
    out=[]; seen=set()
    for title,url in re.findall(r'\[([^\]]+)\]\((https?://forums\.d2jsp\.org/topic\.php\?[^)\s]+)\)',md,re.I):
        title=re.sub(r'[*_`]+','',title)
        title=re.sub(r'\s+',' ',title).strip()
        url=url.replace('&amp;','&')
        if title and url not in seen:
            seen.add(url); out.append((title,url))
    return out


def side_of(title):
    t=title.lower().strip()
    if re.search(r'\b(?:iso|wtb|need|buying|paying)\b',t) or re.match(r'^n\b',t): return 'iso'
    if re.search(r'\b(?:ft|wts|selling|sell|bin)\b',t) or re.match(r'^o\b',t): return 'ft'
    # A direct FG price in a non-ISO title is normally an offer / FT listing.
    if re.search(r'\d+(?:\.\d+)?\s*[kK]?\s*(?:fg|forum\s*gold)\b',t): return 'ft'
    return 'unknown'


def rune_names_in(line):
    low=line.lower(); names=[]
    for rune in CFG['runes']:
        if re.search(rf'(?<![a-z]){re.escape(rune.lower())}(?![a-z])',low): names.append(rune)
    return names


def line_prices(line):
    low=line.lower(); found=[]
    names=rune_names_in(line)
    if not names:return found
    has_price_context=bool(re.search(r'\b(?:fg|forum\s*gold|bin|price|pay|paying|offer|vs)\b',low))
    for rune in names:
        rr=re.escape(rune.lower()); price=None
        # Prefer a price written after the rune. This correctly handles lines such
        # as "Cham 550 Fg Lo 165" (Cham=550, Lo=165).
        m=re.search(rf'(?<![a-z]){rr}(?![a-z]).{{0,22}}?{PRICE}\s*(?:fg|forum\s*gold)\b',low,re.I)
        if m: price=nval(m.group(1))
        if price is None and has_price_context:
            m=re.search(rf'(?<![a-z]){rr}(?![a-z])(?:\s+rune)?\s*(?:=|:|-|vs|for|@)?\s*{PRICE}(?!\s*x\b)',low,re.I)
            if m: price=nval(m.group(1))
        # Price-before-rune is only safe when the line mentions one rune.
        if price is None and len(names)==1:
            m=re.search(rf'{PRICE}\s*(?:fg|forum\s*gold)\b.{{0,22}}?(?<![a-z]){rr}(?![a-z])',low,re.I)
            if m: price=nval(m.group(1))
        if price is None and len(names)==1:
            fgs=[nval(x) for x in re.findall(rf'{PRICE}\s*(?:fg|forum\s*gold)\b',low,re.I)]
            fgs=[x for x in fgs if x is not None]
            if len(fgs)==1: price=fgs[0]
        if price is not None: found.append((rune,price))
    return found


def item_prices(line):
    low=line.lower(); result=[]
    for item in CFG.get('items',[]):
        if not any(a.lower() in low for a in item['aliases']): continue
        m=re.search(rf'{PRICE}\s*(?:fg|forum\s*gold)\b',low,re.I)
        if m:
            v=nval(m.group(1))
            if v is not None: result.append((item,v))
    return result


def parse_topic(title,url):
    try: md=reader(url)
    except Exception as e: return {'error':str(e),'url':url,'title':title,'samples':[],'completed':False}
    side=side_of(title); completed=bool(COMPLETE.search(md))
    samples=[]; per_rune={}; seen=set()

    def add(s):
        key=(s['kind'],s['id'],s['side'],s['price_fg'],s['url'])
        if key not in seen:
            seen.add(key); samples.append(s)

    for raw in md.splitlines():
        line=re.sub(r'\s+',' ',raw).strip()
        if not line or len(line)>600: continue
        for rune,price in line_prices(line):
            per_rune.setdefault(rune,[]).append(price)
            add({'kind':'rune','id':rune,'label':rune,'side':side,'price_fg':price,'title':title,'url':url})
        for item,price in item_prices(line):
            add({'kind':'item','id':item['id'],'label':item['label'],'side':side,'price_fg':price,'title':title,'url':url})

    # T4T / sold is an actual completion signal regardless of whether the original
    # topic was ISO, FT, or had no explicit side marker.
    if completed:
        for rune,vals in per_rune.items():
            if vals:
                add({'kind':'rune','id':rune,'label':rune,'side':'trade','price_fg':statistics.median(vals),'title':title+' · T4T/sold signal','url':url})
    return {'url':url,'title':title,'samples':samples,'completed':completed}


def summarize(samples):
    groups={}
    for s in samples: groups.setdefault((s['kind'],s['id'],s['label']),[]).append(s)
    out=[]
    for (kind,id_,label),rows in groups.items():
        base=[r['price_fg'] for r in rows if r['side']!='trade' and r['price_fg'] is not None]
        tr=[r['price_fg'] for r in rows if r['side']=='trade' and r['price_fg'] is not None]
        iso=[r['price_fg'] for r in rows if r['side']=='iso' and r['price_fg'] is not None]
        ft=[r['price_fg'] for r in rows if r['side']=='ft' and r['price_fg'] is not None]
        fairvals=base or tr
        conf='high' if len(base)>=10 else 'medium' if len(base)>=4 else 'low'
        out.append({'kind':kind,'id':id_,'label':label,'fair_fg':round(statistics.median(fairvals),2) if fairvals else None,'iso_fg':round(statistics.median(iso),2) if iso else None,'ft_fg':round(statistics.median(ft),2) if ft else None,'trade_fg':round(statistics.median(tr),2) if tr else None,'samples':len(base),'confidence':conf,'sources':rows[:24]})
    return out


def main():
    links=[]; diagnostics=[]
    pages=[RUNE_FORUM+('' if i==0 else f'&o={i*25}') for i in range(4)] + [FORUM]
    for u in pages:
        try:
            md=reader(u); ls=topic_links(md); links.extend(ls)
            diagnostics.append({'url':u,'topics':len(ls),'bytes':len(md)})
        except Exception as e: diagnostics.append({'url':u,'error':str(e)})

    dedup={}
    for title,url in links: dedup.setdefault(url,title)
    topics=[(t,u) for u,t in dedup.items()][:45]
    samples=[]; errors=[]; completed_topics=0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs=[ex.submit(parse_topic,t,u) for t,u in topics]
        for f in as_completed(futs):
            r=f.result(); samples.extend(r.get('samples',[]))
            if r.get('completed'): completed_topics+=1
            if r.get('error'): errors.append({'url':r['url'],'error':r['error']})

    now=datetime.now(timezone.utc).isoformat(); rows=summarize(samples)
    market={'updated_at':now,'forum':FORUM,'topic_count':len(dedup),'parsed_topics':len(topics)-len(errors),'completed_topics':completed_topics,'sample_count':sum(m['samples'] for m in rows),'market':rows}
    (DATA/'market.json').write_text(json.dumps(market,ensure_ascii=False,indent=2),encoding='utf-8')
    (DATA/'diagnostic.json').write_text(json.dumps({'forum_pages':diagnostics,'topic_errors':errors[:20],'completed_topics':completed_topics},ensure_ascii=False,indent=2),encoding='utf-8')

    hp=DATA/'history.json'
    try: hist=json.loads(hp.read_text(encoding='utf-8'))
    except: hist=[]
    cutoff=datetime.now(timezone.utc)-timedelta(days=7)
    hist=[h for h in hist if datetime.fromisoformat(h['at'])>=cutoff]
    hist.append({'at':now,'prices':{m['id']:m['fair_fg'] for m in rows}})
    hp.write_text(json.dumps(hist,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"topics={len(dedup)} parsed={len(topics)-len(errors)} completed={completed_topics} samples={market['sample_count']} market={len(rows)} errors={len(errors)}")

if __name__=='__main__': main()
