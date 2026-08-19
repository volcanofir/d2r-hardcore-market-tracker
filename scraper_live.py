import json, re, statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin
import requests

ROOT=Path(__file__).parent
DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
CFG=json.loads((ROOT/'config/watchlist.json').read_text(encoding='utf-8'))
FORUM=f"https://forums.d2jsp.org/forum.php?f={CFG['forum_id']}"
RUNE_FORUM=f"https://forums.d2jsp.org/forum.php?f={CFG['forum_id']}&c=2"
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'}
PRICE=r'(\d+(?:\.\d+)?\s*[kK]?)'
COMPLETE=re.compile(r'\b(?:t4t|sold|done|closed|trade complete)\b',re.I)


def nval(s):
    s=s.strip().replace(' ','')
    m=1000 if s.lower().endswith('k') else 1
    if m==1000:s=s[:-1]
    try:v=float(s)*m
    except:return None
    return v if 0<v<100000 else None


def reader(url,timeout=35):
    target='https://r.jina.ai/https://'+url.removeprefix('https://').removeprefix('http://')
    r=requests.get(target,headers=HEADERS,timeout=timeout)
    r.raise_for_status()
    return r.text


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
    t=title.lower()
    if re.search(r'\b(?:iso|wtb|need|buying|paying)\b',t) or re.match(r'^n\b',t): return 'iso'
    if re.search(r'\b(?:ft|wts|selling|sell|bin)\b',t) or re.match(r'^o\b',t): return 'ft'
    return 'unknown'


def line_prices(line):
    low=line.lower(); found=[]
    for rune in CFG['runes']:
        rr=re.escape(rune.lower())
        if not re.search(rf'(?<![a-z]){rr}(?![a-z])',low):
            continue
        price=None
        pats=[
            rf'(?<![a-z]){rr}(?![a-z]).{{0,28}}?{PRICE}\s*(?:fg|forum\s*gold)\b',
            rf'{PRICE}\s*(?:fg|forum\s*gold)\b.{{0,28}}?(?<![a-z]){rr}(?![a-z])',
            rf'(?<![a-z]){rr}(?![a-z])(?:\s+rune)?\s*(?:=|:|-|vs|for|@)?\s*{PRICE}\b'
        ]
        for p in pats:
            m=re.search(p,low,re.I)
            if m:
                price=nval(m.group(1));
                if price is not None: break
        if price is None:
            # If the line names one rune and exactly one explicit FG amount, pair them.
            rune_hits=sum(bool(re.search(rf'(?<![a-z]){re.escape(x.lower())}(?![a-z])',low)) for x in CFG['runes'])
            fgs=[nval(x) for x in re.findall(rf'{PRICE}\s*(?:fg|forum\s*gold)\b',low,re.I)]
            fgs=[x for x in fgs if x is not None]
            if rune_hits==1 and len(fgs)==1: price=fgs[0]
        if price is not None: found.append((rune,price))
    return found


def item_prices(line):
    low=line.lower(); result=[]
    for item in CFG.get('items',[]):
        if not any(a.lower() in low for a in item['aliases']): continue
        m=re.search(rf'{PRICE}\s*(?:fg|forum\s*gold)\b',low,re.I)
        if not m and re.search(r'\b(?:bin|price|pay|offer)\b',low):
            nums=re.findall(PRICE,low); m=None
            if nums:
                v=nval(nums[-1]);
                if v is not None: result.append((item,v)); continue
        if m:
            v=nval(m.group(1))
            if v is not None: result.append((item,v))
    return result


def parse_topic(title,url):
    try: md=reader(url)
    except Exception as e:
        return {'error':str(e),'url':url,'title':title,'samples':[]}
    side=side_of(title)
    completed=bool(COMPLETE.search(md))
    samples=[]; per_rune={}
    for raw in md.splitlines():
        line=re.sub(r'\s+',' ',raw).strip()
        if not line or len(line)>600: continue
        for rune,price in line_prices(line):
            per_rune.setdefault(rune,[]).append(price)
            samples.append({'kind':'rune','id':rune,'label':rune,'side':side,'price_fg':price,'title':title,'url':url})
        for item,price in item_prices(line):
            samples.append({'kind':'item','id':item['id'],'label':item['label'],'side':side,'price_fg':price,'title':title,'url':url})
    if side=='ft' and completed:
        for rune,vals in per_rune.items():
            samples.append({'kind':'rune','id':rune,'label':rune,'side':'trade','price_fg':statistics.median(vals),'title':title+' · T4T/sold signal','url':url})
    return {'url':url,'title':title,'samples':samples}


def summarize(samples):
    groups={}
    for s in samples: groups.setdefault((s['kind'],s['id'],s['label']),[]).append(s)
    out=[]
    for (kind,id_,label),rows in groups.items():
        vals=[r['price_fg'] for r in rows if r['price_fg'] is not None]
        iso=[r['price_fg'] for r in rows if r['side']=='iso']
        ft=[r['price_fg'] for r in rows if r['side']=='ft']
        tr=[r['price_fg'] for r in rows if r['side']=='trade']
        conf='high' if len(vals)>=10 else 'medium' if len(vals)>=4 else 'low'
        out.append({'kind':kind,'id':id_,'label':label,'fair_fg':round(statistics.median(vals),2) if vals else None,'iso_fg':round(statistics.median(iso),2) if iso else None,'ft_fg':round(statistics.median(ft),2) if ft else None,'trade_fg':round(statistics.median(tr),2) if tr else None,'samples':len(vals),'confidence':conf,'sources':rows[:24]})
    return out


def main():
    links=[]; diagnostics=[]
    # Four rune-filter pages plus one unfiltered page for watched items.
    pages=[RUNE_FORUM+('' if i==0 else f'&o={i*25}') for i in range(4)] + [FORUM]
    for u in pages:
        try:
            md=reader(u); ls=topic_links(md); links.extend(ls)
            diagnostics.append({'url':u,'topics':len(ls),'bytes':len(md)})
        except Exception as e: diagnostics.append({'url':u,'error':str(e)})
    dedup={}
    for title,url in links: dedup.setdefault(url,title)
    topics=[(t,u) for u,t in dedup.items()][:60]
    samples=[]; errors=[]
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(parse_topic,t,u) for t,u in topics]
        for f in as_completed(futs):
            r=f.result(); samples.extend(r.get('samples',[]))
            if r.get('error'): errors.append({'url':r['url'],'error':r['error']})
    now=datetime.now(timezone.utc).isoformat(); rows=summarize(samples)
    market={'updated_at':now,'forum':FORUM,'topic_count':len(dedup),'parsed_topics':len(topics)-len(errors),'sample_count':len(samples),'market':rows}
    (DATA/'market.json').write_text(json.dumps(market,ensure_ascii=False,indent=2),encoding='utf-8')
    (DATA/'diagnostic.json').write_text(json.dumps({'forum_pages':diagnostics,'topic_errors':errors[:20]},ensure_ascii=False,indent=2),encoding='utf-8')
    hp=DATA/'history.json'
    try: hist=json.loads(hp.read_text(encoding='utf-8'))
    except: hist=[]
    cutoff=datetime.now(timezone.utc)-timedelta(days=7)
    hist=[h for h in hist if datetime.fromisoformat(h['at'])>=cutoff]
    hist.append({'at':now,'prices':{m['id']:m['fair_fg'] for m in rows}})
    hp.write_text(json.dumps(hist,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"topics={len(dedup)} parsed={len(topics)-len(errors)} samples={len(samples)} market={len(rows)} errors={len(errors)}")

if __name__=='__main__': main()
