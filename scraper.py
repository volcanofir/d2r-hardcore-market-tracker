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
RUNE_FORUM = f"https://forums.d2jsp.org/forum.php?c=2&f={CFG['forum_id']}"

# d2jsp serves a different/empty response to some obvious bot user agents.
# Use ordinary browser headers first, then fall back to a text-reader endpoint if
# GitHub-hosted runners are blocked by the origin.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

PRICE_TOKEN = r"(\d+(?:\.\d+)?\s*[kK]?)"
COMPLETION = re.compile(r"\b(?:t4t|sold|done|closed|trade complete|thanks|thank you|ty)\b", re.I)


def parse_num(raw):
    raw = raw.strip().replace(" ", "")
    mult = 1000 if raw.lower().endswith("k") else 1
    if mult == 1000:
        raw = raw[:-1]
    try:
        value = float(raw) * mult
    except ValueError:
        return None
    return value if 0 < value < 100000 else None


def _blocked(text):
    low = text.lower()
    return (
        len(text) < 300
        or "access denied" in low
        or "captcha" in low
        or "cloudflare" in low
        or "enable javascript" in low
    )


def get(url, expect_topic_links=False):
    direct_error = None
    try:
        r = SESSION.get(url, timeout=25, allow_redirects=True)
        r.raise_for_status()
        text = r.text
        valid = not _blocked(text)
        if expect_topic_links:
            valid = valid and "topic.php" in text
        if valid:
            return text, "html"
        direct_error = f"unexpected response status={r.status_code} bytes={len(text)}"
    except Exception as e:
        direct_error = repr(e)

    # Reader fallback is useful when a public site blocks cloud-hosted runner IPs.
    reader_url = "https://r.jina.ai/http://" + url.removeprefix("https://").removeprefix("http://")
    try:
        rr = SESSION.get(reader_url, timeout=40)
        rr.raise_for_status()
        text = rr.text
        if _blocked(text):
            raise RuntimeError(f"reader returned unusable response bytes={len(text)}")
        print(f"reader fallback used: {url} ({direct_error})")
        return text, "text"
    except Exception as e:
        raise RuntimeError(f"direct={direct_error}; reader={e}") from e


def topic_links(payload, mode):
    out, seen = [], set()
    if mode == "html":
        soup = BeautifulSoup(payload, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "topic.php" not in href:
                continue
            url = urljoin(BASE, href).replace("&amp;", "&")
            title = " ".join(a.stripped_strings).strip()
            if not title or title in {">>", "»"} or url in seen:
                continue
            seen.add(url)
            out.append((title, url))
    else:
        # Jina-style Markdown links.
        for title, url in re.findall(r"\[([^\]]+)\]\((https?://forums\.d2jsp\.org/topic\.php\?[^)\s]+)\)", payload, re.I):
            url = url.replace("&amp;", "&")
            title = re.sub(r"\s+", " ", title).strip()
            if url not in seen and title:
                seen.add(url)
                out.append((title, url))
        # Fallback for plain URLs in text-reader output.
        for url in re.findall(r"https?://forums\.d2jsp\.org/topic\.php\?[^\s)\]>]+", payload, re.I):
            url = url.replace("&amp;", "&")
            if url not in seen:
                seen.add(url)
                out.append(("d2jsp topic", url))
    return out


def classify_topic(title, text):
    sample = (title + "\n" + text[:2500]).lower()
    if re.search(r"(?:^|\s|>)iso(?:\s|<|>|$)", sample) or re.search(r"\b(?:wtb|need|buying|paying|iso)\b", title, re.I):
        return "iso"
    if re.search(r"(?:^|\s|>)ft(?:\s|<|>|$)", sample) or re.search(r"\b(?:wts|selling|sell|ft|bin)\b", title, re.I):
        return "ft"
    return "unknown"


def page_lines(payload, mode):
    if mode == "html":
        soup = BeautifulSoup(payload, "html.parser")
        # Preserve natural post/line boundaries instead of joining the entire page.
        text = soup.get_text("\n", strip=True)
    else:
        text = payload
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line and len(line) <= 500:
            lines.append(line)
    return lines


def rune_prices_from_line(line):
    found = []
    low = line.lower()
    for rune in CFG["runes"]:
        r = re.escape(rune.lower())
        # Strongest/common patterns: "Ber 150", "Ber = 150fg", "Vex here 170fg".
        patterns = [
            rf"(?<![a-z]){r}(?![a-z])(?:\s+rune)?\s*(?:here\s*)?(?:vs\s*|@\s*|=\s*|[-:]\s*|for\s*|bin\s*)?{PRICE_TOKEN}\s*(?:fg|forum\s*gold)?\b",
            # Price-before-rune variants such as "Paying 15 fg each Um rune".
            rf"\b(?:paying|pay|bin|offer|price)\D{{0,12}}{PRICE_TOKEN}\s*(?:fg)?\D{{0,16}}(?<![a-z]){r}(?![a-z])",
        ]
        price = None
        for pat in patterns:
            m = re.search(pat, low, re.I)
            if m:
                # PRICE_TOKEN is the only capture group in each full pattern.
                price = parse_num(m.group(1))
                if price is not None:
                    break
        if price is not None:
            # Avoid treating quantity-only phrases like "2x Ber" as a price.
            around = low[max(0, low.find(rune.lower()) - 8): low.find(rune.lower()) + len(rune) + 25]
            if re.search(rf"\b{re.escape(str(int(price)))}\s*x\s*{r}\b", around) and "fg" not in around:
                continue
            found.append((rune, price))
    return found


def item_targets(line):
    low = line.lower()
    out = []
    for item in CFG.get("items", []):
        if any(alias.lower() in low for alias in item["aliases"]):
            out.append(item)
    return out


def generic_price(line):
    # For monitored items: accept explicit FG or pricing-keyword numbers.
    m = re.search(rf"{PRICE_TOKEN}\s*(?:fg|forum\s*gold)\b", line, re.I)
    if m:
        return parse_num(m.group(1))
    if re.search(r"\b(?:bin|price|pay|paying|offer)\b", line, re.I):
        nums = re.findall(PRICE_TOKEN, line)
        return parse_num(nums[-1]) if nums else None
    return None


def summarize(samples):
    grouped = {}
    for s in samples:
        key = (s["kind"], s["id"], s["label"])
        grouped.setdefault(key, []).append(s)

    result = []
    for (kind, id_, label), rows in grouped.items():
        priced = [r for r in rows if r["price_fg"] is not None]
        def vals(side):
            return [r["price_fg"] for r in priced if r["side"] == side]
        allv = [r["price_fg"] for r in priced]
        iso, ft, trade = vals("iso"), vals("ft"), vals("trade")
        confidence = "low"
        if len(allv) >= 10:
            confidence = "high"
        elif len(allv) >= 4:
            confidence = "medium"
        result.append({
            "kind": kind,
            "id": id_,
            "label": label,
            "fair_fg": round(statistics.median(allv), 2) if allv else None,
            "iso_fg": round(statistics.median(iso), 2) if iso else None,
            "ft_fg": round(statistics.median(ft), 2) if ft else None,
            "trade_fg": round(statistics.median(trade), 2) if trade else None,
            "samples": len(allv),
            "confidence": confidence,
            "sources": rows[:24],
        })
    return result


def collect_forum(base_url, pages):
    links = []
    for p in range(pages):
        # d2jsp currently shows 25 topics per page.
        url = base_url if p == 0 else base_url + f"&o={p * 25}"
        try:
            payload, mode = get(url, expect_topic_links=True)
            page = topic_links(payload, mode)
            print(f"forum page {p + 1}: mode={mode} topics={len(page)} url={url}")
            links.extend(page)
        except Exception as e:
            print("forum page error", url, e)
        time.sleep(0.7)
    return links


def main():
    # Rune-filtered pages provide much better signal density. Also scan a few
    # unfiltered pages so custom watched items continue to work.
    links = collect_forum(RUNE_FORUM, min(CFG.get("pages", 8), 6))
    links += collect_forum(FORUM, 2)

    dedup = {}
    for title, url in links:
        dedup.setdefault(url, title)
    links = [(title, url) for url, title in dedup.items()]

    samples = []
    parsed_topics = 0
    for title, url in links[:200]:
        try:
            payload, mode = get(url)
            lines = page_lines(payload, mode)
            full_text = "\n".join(lines)
            side = classify_topic(title, full_text)
            completed = bool(COMPLETION.search(full_text))
            parsed_topics += 1

            topic_rune_prices = {}
            for line in lines:
                for rune, price in rune_prices_from_line(line):
                    topic_rune_prices.setdefault(rune, []).append(price)
                    samples.append({
                        "kind": "rune", "id": rune, "label": rune,
                        "side": side, "price_fg": price,
                        "title": title, "url": url,
                    })

                for item in item_targets(line):
                    price = generic_price(line)
                    if price is not None:
                        samples.append({
                            "kind": "item", "id": item["id"], "label": item["label"],
                            "side": side, "price_fg": price,
                            "title": title, "url": url,
                        })

            # A priced FT topic that later contains a clear completion signal is
            # treated as a transaction signal. This is intentionally separate
            # from the asking-price FT sample.
            if side == "ft" and completed:
                for rune, prices in topic_rune_prices.items():
                    if prices:
                        samples.append({
                            "kind": "rune", "id": rune, "label": rune,
                            "side": "trade", "price_fg": statistics.median(prices),
                            "title": title + " · completed signal", "url": url,
                        })
        except Exception as e:
            print("topic error", url, e)
        time.sleep(0.25)

    now = datetime.now(timezone.utc).isoformat()
    market_rows = summarize(samples)
    market = {
        "updated_at": now,
        "forum": FORUM,
        "topic_count": len(links),
        "parsed_topics": parsed_topics,
        "sample_count": len(samples),
        "market": market_rows,
    }
    (DATA / "market.json").write_text(json.dumps(market, ensure_ascii=False, indent=2), encoding="utf-8")

    hist_path = DATA / "history.json"
    try:
        hist = json.loads(hist_path.read_text(encoding="utf-8"))
    except Exception:
        hist = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    hist = [h for h in hist if datetime.fromisoformat(h["at"]) >= cutoff]
    hist.append({"at": now, "prices": {m["id"]: m["fair_fg"] for m in market_rows}})
    hist_path.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"topics={len(links)} parsed={parsed_topics} samples={len(samples)} market={len(market_rows)}")


if __name__ == "__main__":
    main()
