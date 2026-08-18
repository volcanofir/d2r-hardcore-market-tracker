import json, re, statistics, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
CFG = json.loads((ROOT / "config/watchlist.json").read_text(encoding="utf-8"))
BASE = "https://forums.d2jsp.org/"
FORUM = f"https://forums.d2jsp.org/forum.php?f={CFG['forum_id']}"
HEADERS = {"User-Agent":"Mozilla/5.0 (compatible; D2RMarketTracker/1.0; +https://github.com/volcanofir/d2r-hardcore-market-tracker)"}
FG = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:fg|forum\s*gold)\b", re.I)
NUM = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\b")


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text


def topic_links(html):
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "topic.php" not in href:
            continue
        url = urljoin(BASE, href)
        title = " ".join(a.stripped_strings).strip()
        if not title or url in seen:
            continue
        seen.add(url); out.append((title, url))
    return out


def classify(text):
    t = text.lower()
    if any(x in t for x in ["t4t", "sold", "closed", "done", "trade complete"]): return "trade"
    if any(x in t for x in ["iso", "need ", "n ", "buying", "paying"]): return "iso"
    if any(x in t for x in ["ft", "bin", "selling", "sell "]): return "ft"
    return "unknown"


def extract_price(text):
    m = FG.search(text)
    if m: return float(m.group(1))
    # Only accept a bare number when a pricing keyword is nearby.
    if re.search(r"\b(?:bin|offer|price|pay|paying)\b", text, re.I):
        nums = [float(x) for x in NUM.findall(text)]
        nums = [x for x in nums if 0 < x < 100000]
        return nums[-1] if nums else None
    return None


def targets(text):
    low = text.lower()
    found=[]
    for rune in CFG["runes"]:
        if re.search(rf"(?<![a-z]){re.escape(rune.lower())}(?![a-z])", low): found.append(("rune", rune, rune))
    for item in CFG.get("items",[]):
        if any(alias.lower() in low for alias in item["aliases"]): found.append(("item", item["id"], item["label"]))
    return found


def summarize(samples):
    grouped={}
    for s in samples:
        key=(s["kind"],s["id"],s["label"])
        grouped.setdefault(key,[]).append(s)
    result=[]
    for (kind,id_,label), rows in grouped.items():
        priced=[r for r in rows if r["price_fg"] is not None]
        def vals(side): return [r["price_fg"] for r in priced if r["side"]==side]
        allv=[r["price_fg"] for r in priced]
        iso,ft,tr=vals("iso"),vals("ft"),vals("trade")
        confidence="low"
        if len(allv)>=8: confidence="high"
        elif len(allv)>=3: confidence="medium"
        result.append({
          "kind":kind,"id":id_,"label":label,
          "fair_fg": round(statistics.median(allv),2) if allv else None,
          "iso_fg": round(statistics.median(iso),2) if iso else None,
          "ft_fg": round(statistics.median(ft),2) if ft else None,
          "trade_fg": round(statistics.median(tr),2) if tr else None,
          "samples":len(allv),"confidence":confidence,
          "sources":rows[:20]
        })
    return result


def main():
    links=[]
    for p in range(CFG.get("pages",5)):
        url=FORUM if p==0 else FORUM+f"&o={p*30}"
        try: links += topic_links(get(url))
        except Exception as e: print("forum page error",url,e)
        time.sleep(.8)
    # de-duplicate topic URLs
    links=list(dict((u,t) for t,u in links).items())
    samples=[]
    for url,title in links[:300]:
        text=title
        try:
            soup=BeautifulSoup(get(url),"html.parser")
            text += " " + " ".join(soup.stripped_strings)[:12000]
        except Exception as e: print("topic error",url,e)
        price=extract_price(text); side=classify(text)
        for kind,id_,label in targets(title+" "+text[:5000]):
            samples.append({"kind":kind,"id":id_,"label":label,"side":side,"price_fg":price,"title":title,"url":url})
        time.sleep(.35)
    now=datetime.now(timezone.utc).isoformat()
    market={"updated_at":now,"forum":FORUM,"topic_count":len(links),"market":summarize(samples)}
    (DATA/"market.json").write_text(json.dumps(market,ensure_ascii=False,indent=2),encoding="utf-8")
    hist_path=DATA/"history.json"
    try: hist=json.loads(hist_path.read_text(encoding="utf-8"))
    except Exception: hist=[]
    cutoff=datetime.now(timezone.utc)-timedelta(days=7)
    hist=[h for h in hist if datetime.fromisoformat(h["at"])>=cutoff]
    hist.append({"at":now,"prices":{m["id"]:m["fair_fg"] for m in market["market"]}})
    hist_path.write_text(json.dumps(hist,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"topics={len(links)} samples={len(samples)} market={len(market['market'])}")

if __name__ == "__main__": main()
