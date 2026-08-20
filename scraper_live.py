import json
import random
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
CFG = json.loads((ROOT / "config/watchlist.json").read_text(encoding="utf-8"))

FORUM = f"https://forums.d2jsp.org/forum.php?f={CFG['forum_id']}"
RUNE_FORUM = f"{FORUM}&c=2"
CACHE_PATH = DATA / "topic_cache.json"
MARKET_PATH = DATA / "market.json"
HISTORY_PATH = DATA / "history.json"
DIAGNOSTIC_PATH = DATA / "diagnostic.json"
LEGACY_PATH = DATA / "legacy_samples.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
}
PRICE = r"(\d+(?:\.\d+)?\s*[kK]?)"
COMPLETE = re.compile(r"\b(?:t4t|sold|closed|trade complete)\b", re.I)

CACHE_DAYS = 7
NEW_TOPICS_PER_RUN = 12
RECHECK_TOPICS_PER_RUN = 4
RECHECK_AFTER_HOURS = 6
MAX_WORKERS = 2


def utcnow():
    return datetime.now(timezone.utc)


def iso_now():
    return utcnow().isoformat()


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def nval(raw):
    raw = raw.strip().replace(" ", "")
    mult = 1000 if raw.lower().endswith("k") else 1
    if mult == 1000:
        raw = raw[:-1]
    try:
        value = float(raw) * mult
    except Exception:
        return None
    return value if 0 < value < 100000 else None


def reader(url, timeout=35, retries=5):
    target = "https://r.jina.ai/https://" + url.removeprefix("https://").removeprefix("http://")
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.get(target, headers=HEADERS, timeout=timeout)
            if response.status_code == 429:
                last_error = f"429 Too Many Requests ({attempt + 1}/{retries})"
                time.sleep(min(30, 3 * (2 ** attempt)) + random.uniform(0.2, 1.2))
                continue
            response.raise_for_status()
            text = response.text
            if len(text) < 150:
                raise RuntimeError(f"reader returned only {len(text)} bytes")
            return text
        except Exception as exc:
            last_error = str(exc)
            if attempt < retries - 1:
                time.sleep(min(15, 2 * (attempt + 1)) + random.uniform(0.2, 0.8))
    raise RuntimeError(last_error or "reader failed")


def topic_links(markdown):
    found = []
    seen = set()
    pattern = r"\[([^\]]+)\]\((https?://forums\.d2jsp\.org/topic\.php\?[^)\s]+)\)"
    for title, url in re.findall(pattern, markdown, re.I):
        title = re.sub(r"[*_`]+", "", title)
        title = re.sub(r"\s+", " ", title).strip()
        url = url.replace("&amp;", "&")
        if title and url not in seen:
            seen.add(url)
            found.append((title, url))
    return found


def side_of(title):
    text = title.lower().strip()
    if re.search(r"\b(?:iso|wtb|need|buying|paying)\b", text) or re.match(r"^n\b", text):
        return "iso"
    if re.search(r"\b(?:ft|wts|selling|sell|bin)\b", text) or re.match(r"^o\b", text):
        return "ft"
    if re.search(r"\d+(?:\.\d+)?\s*[kK]?\s*(?:fg|forum\s*gold)\b", text):
        return "ft"
    return "unknown"


def ambiguous_rune_context(rune, text):
    low = (text or "").lower()
    if rune.lower() == "eth":
        if re.search(
            r"\b(?:merc\s+)?eth(?:ereal)?\s+(?:infinity|insight|fortitude|fort|weapon|armor|polearm|thresher|cryptic axe|giant thresher|colossus voulge|titans|andy|andys|obedience)\b",
            low,
            re.I,
        ):
            return True
        if re.search(r"\beth\s+(?:cv|ca|gt)\b", low, re.I):
            return True
    return False


def sample_valid(sample):
    if sample.get("id") == "Eth" and ambiguous_rune_context("Eth", sample.get("title", "")):
        return False
    value = sample.get("price_fg")
    return isinstance(value, (int, float)) and 0 < value < 100000


def rune_mentions(line):
    low = line.lower()
    hits = []
    for rune in CFG["runes"]:
        for match in re.finditer(rf"(?<![a-z]){re.escape(rune.lower())}(?![a-z])", low):
            if not ambiguous_rune_context(rune, line):
                hits.append((match.start(), match.end(), rune))
    return sorted(hits)


def line_prices(line):
    low = line.lower()
    hits = rune_mentions(line)
    if not hits:
        return []

    found = []
    has_context = bool(re.search(r"\b(?:fg|forum\s*gold|bin|price|pay|paying|offer|vs)\b", low))

    for index, (start, end, rune) in enumerate(hits):
        next_start = hits[index + 1][0] if index + 1 < len(hits) else min(len(low), end + 40)
        segment = low[end:next_start]
        price = None

        explicit = re.search(rf"[^\d]{{0,18}}?{PRICE}\s*(?:fg|forum\s*gold)\b", " " + segment, re.I)
        if explicit:
            price = nval(explicit.group(1))

        if price is None and has_context:
            bare = re.match(rf"\s*(?:rune\s*)?(?:=|:|-|vs|for|@)?\s*{PRICE}(?!\s*x\b)", segment, re.I)
            if bare:
                price = nval(bare.group(1))

        if price is None and len(hits) == 1:
            before = low[max(0, start - 28):start]
            prior = re.search(rf"{PRICE}\s*(?:fg|forum\s*gold)\b[^\d]{{0,18}}$", before, re.I)
            if prior:
                price = nval(prior.group(1))

        if price is None and len(hits) == 1:
            amounts = [nval(x) for x in re.findall(rf"{PRICE}\s*(?:fg|forum\s*gold)\b", low, re.I)]
            amounts = [x for x in amounts if x is not None]
            if len(amounts) == 1:
                price = amounts[0]

        if price is not None:
            found.append((rune, price))

    return found


def item_prices(line):
    low = line.lower()
    result = []
    for item in CFG.get("items", []):
        if not any(alias.lower() in low for alias in item["aliases"]):
            continue
        match = re.search(rf"{PRICE}\s*(?:fg|forum\s*gold)\b", low, re.I)
        if match:
            value = nval(match.group(1))
            if value is not None:
                result.append((item, value))
    return result


def parse_topic(title, url):
    markdown = reader(url)
    side = side_of(title)
    completed = bool(COMPLETE.search(markdown))
    samples = []
    per_rune = {}
    seen = set()
    observed_at = iso_now()

    def add(sample):
        key = (sample["kind"], sample["id"], sample["side"], sample["price_fg"], sample["url"])
        if key not in seen and sample_valid(sample):
            seen.add(key)
            samples.append(sample)

    for raw in markdown.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or len(line) > 600:
            continue

        for rune, price in line_prices(line):
            per_rune.setdefault(rune, []).append(price)
            add({
                "kind": "rune",
                "id": rune,
                "label": rune,
                "side": side,
                "price_fg": price,
                "title": title,
                "url": url,
                "observed_at": observed_at,
            })

        for item, price in item_prices(line):
            add({
                "kind": "item",
                "id": item["id"],
                "label": item["label"],
                "side": side,
                "price_fg": price,
                "title": title,
                "url": url,
                "observed_at": observed_at,
            })

    if completed:
        for rune, values in per_rune.items():
            if values:
                add({
                    "kind": "rune",
                    "id": rune,
                    "label": rune,
                    "side": "trade",
                    "price_fg": statistics.median(values),
                    "title": title + " · T4T/sold signal",
                    "url": url,
                    "observed_at": observed_at,
                })

    return {
        "title": title,
        "url": url,
        "completed": completed,
        "samples": samples,
        "checked_at": observed_at,
    }


def prune_cache(cache):
    cutoff = utcnow() - timedelta(days=CACHE_DAYS)
    keep = {}
    for url, entry in cache.setdefault("topics", {}).items():
        first_seen = parse_dt(entry.get("first_seen_at")) or parse_dt(entry.get("last_checked_at"))
        if first_seen is None or first_seen >= cutoff:
            keep[url] = entry
    cache["topics"] = keep
    return cache


def legacy_samples():
    payload = load_json(LEGACY_PATH, {})
    snapshot_at = parse_dt(payload.get("snapshot_at"))
    if snapshot_at is None or snapshot_at < utcnow() - timedelta(days=CACHE_DAYS):
        return []

    output = []
    for raw in payload.get("samples", []):
        sample = dict(raw)
        sample["observed_at"] = payload["snapshot_at"]
        sample["legacy"] = True
        if sample_valid(sample):
            output.append(sample)
    return output


def aggregate_samples(cache):
    # Historical samples from the last good pre-cache run remain part of the
    # seven-day window. Current cache samples replace exact duplicates.
    dedup = {}
    for sample in legacy_samples():
        key = (sample.get("kind"), sample.get("id"), sample.get("side"), sample.get("price_fg"), sample.get("url"))
        dedup[key] = sample

    for entry in cache.get("topics", {}).values():
        if entry.get("status") != "parsed":
            continue
        for sample in entry.get("samples", []):
            if not sample_valid(sample):
                continue
            key = (sample.get("kind"), sample.get("id"), sample.get("side"), sample.get("price_fg"), sample.get("url"))
            dedup[key] = sample

    return list(dedup.values())


def summarize(samples):
    groups = {}
    for sample in samples:
        groups.setdefault((sample["kind"], sample["id"], sample["label"]), []).append(sample)

    rows = []
    for (kind, item_id, label), group in groups.items():
        base = [x["price_fg"] for x in group if x.get("side") != "trade" and x.get("price_fg") is not None]
        trades = [x["price_fg"] for x in group if x.get("side") == "trade" and x.get("price_fg") is not None]
        iso = [x["price_fg"] for x in group if x.get("side") == "iso" and x.get("price_fg") is not None]
        ft = [x["price_fg"] for x in group if x.get("side") == "ft" and x.get("price_fg") is not None]
        fair_values = base or trades

        confidence = "high" if len(base) >= 10 else "medium" if len(base) >= 4 else "low"
        observed = [parse_dt(x.get("observed_at")) for x in group]
        observed = [x for x in observed if x is not None]
        last_seen_at = max(observed).isoformat() if observed else iso_now()

        rows.append({
            "kind": kind,
            "id": item_id,
            "label": label,
            "fair_fg": round(statistics.median(fair_values), 2) if fair_values else None,
            "iso_fg": round(statistics.median(iso), 2) if iso else None,
            "ft_fg": round(statistics.median(ft), 2) if ft else None,
            "trade_fg": round(statistics.median(trades), 2) if trades else None,
            "samples": len(base),
            "confidence": confidence,
            "last_seen_at": last_seen_at,
            "sources": sorted(group, key=lambda x: x.get("observed_at", ""), reverse=True)[:24],
        })

    return rows


def merge_with_previous(new_rows, previous_market):
    cutoff = utcnow() - timedelta(days=CACHE_DAYS)
    merged = {row["id"]: row for row in new_rows}
    previous_updated = parse_dt(previous_market.get("updated_at")) or utcnow()

    for old in previous_market.get("market", []):
        if old.get("id") in merged:
            continue
        if old.get("id") == "Eth" and old.get("fair_fg", 0) >= 100:
            continue
        last_seen = parse_dt(old.get("last_seen_at")) or previous_updated
        if last_seen >= cutoff:
            carried = dict(old)
            carried["stale"] = True
            merged[old.get("id")] = carried

    return list(merged.values())


def discover_topics():
    diagnostics = []
    links = []
    for url in [RUNE_FORUM, RUNE_FORUM + "&o=25", FORUM]:
        try:
            markdown = reader(url, retries=4)
            found = topic_links(markdown)
            links.extend(found)
            diagnostics.append({"url": url, "topics": len(found), "bytes": len(markdown)})
        except Exception as exc:
            diagnostics.append({"url": url, "error": str(exc)})

    dedup = {}
    for title, url in links:
        dedup.setdefault(url, title)
    return dedup, diagnostics


def select_topics(cache):
    now = utcnow()
    pending = []
    recheck = []

    for url, entry in cache.get("topics", {}).items():
        if entry.get("status") != "parsed":
            pending.append((entry.get("first_seen_at", ""), entry.get("title", "d2jsp topic"), url))
            continue
        if entry.get("completed"):
            continue
        last_checked = parse_dt(entry.get("last_checked_at"))
        if last_checked and now - last_checked >= timedelta(hours=RECHECK_AFTER_HOURS):
            recheck.append((entry.get("first_seen_at", ""), entry.get("title", "d2jsp topic"), url))

    pending.sort(reverse=True)
    recheck.sort(reverse=True)
    selected = [(title, url, "new") for _, title, url in pending[:NEW_TOPICS_PER_RUN]]
    selected += [(title, url, "recheck") for _, title, url in recheck[:RECHECK_TOPICS_PER_RUN]]
    return selected


def main():
    now = iso_now()
    previous_market = load_json(MARKET_PATH, {"market": []})
    cache = prune_cache(load_json(CACHE_PATH, {"version": 1, "topics": {}}))

    discovered, forum_diagnostics = discover_topics()
    topics = cache.setdefault("topics", {})

    for url, title in discovered.items():
        if url not in topics:
            topics[url] = {
                "title": title,
                "url": url,
                "first_seen_at": now,
                "last_checked_at": None,
                "completed": False,
                "status": "pending",
                "samples": [],
            }
        else:
            topics[url]["title"] = title or topics[url].get("title")

    # Remove bad samples generated by older parser versions.
    for entry in topics.values():
        entry["samples"] = [x for x in entry.get("samples", []) if sample_valid(x)]

    selected = select_topics(cache)
    topic_errors = []
    parsed_this_run = 0
    completed_this_run = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(parse_topic, title, url): (title, url, reason)
            for title, url, reason in selected
        }
        for future in as_completed(futures):
            title, url, reason = futures[future]
            try:
                result = future.result()
                entry = topics[url]
                entry["title"] = title
                entry["last_checked_at"] = result["checked_at"]
                entry["completed"] = result["completed"]
                entry["status"] = "parsed"
                entry["samples"] = result["samples"]
                entry.pop("last_error", None)
                parsed_this_run += 1
                if result["completed"]:
                    completed_this_run += 1
            except Exception as exc:
                entry = topics[url]
                entry["last_attempt_at"] = iso_now()
                entry["last_error"] = str(exc)
                topic_errors.append({"url": url, "title": title, "reason": reason, "error": str(exc)})

    cache = prune_cache(cache)
    cache["updated_at"] = iso_now()
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    all_samples = aggregate_samples(cache)
    fresh_rows = summarize(all_samples)
    merged_rows = merge_with_previous(fresh_rows, previous_market)

    parsed_cache_topics = sum(1 for x in cache.get("topics", {}).values() if x.get("status") == "parsed")
    completed_cache_topics = sum(1 for x in cache.get("topics", {}).values() if x.get("completed"))

    if not merged_rows and previous_market.get("market"):
        merged_rows = previous_market["market"]

    market = {
        "updated_at": iso_now(),
        "forum": FORUM,
        "topic_count": len(discovered),
        "cached_topics": len(cache.get("topics", {})),
        "parsed_topics": parsed_cache_topics,
        "completed_topics": completed_cache_topics,
        "parsed_this_run": parsed_this_run,
        "sample_count": sum(row.get("samples", 0) for row in merged_rows),
        "legacy_sample_count": len(legacy_samples()),
        "market": merged_rows,
    }
    MARKET_PATH.write_text(json.dumps(market, ensure_ascii=False, indent=2), encoding="utf-8")

    DIAGNOSTIC_PATH.write_text(json.dumps({
        "updated_at": iso_now(),
        "forum_pages": forum_diagnostics,
        "discovered_topics": len(discovered),
        "cached_topics": len(cache.get("topics", {})),
        "selected_topics": len(selected),
        "parsed_this_run": parsed_this_run,
        "completed_this_run": completed_this_run,
        "legacy_samples": len(legacy_samples()),
        "combined_samples": len(all_samples),
        "topic_errors": topic_errors[:20],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    history = load_json(HISTORY_PATH, [])
    cutoff = utcnow() - timedelta(days=CACHE_DAYS)
    history = [h for h in history if (parse_dt(h.get("at")) or cutoff) >= cutoff]
    history.append({
        "at": market["updated_at"],
        "prices": {row["id"]: row.get("fair_fg") for row in merged_rows if row.get("fair_fg") is not None},
    })
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"discovered={len(discovered)} cached={len(cache.get('topics', {}))} "
        f"selected={len(selected)} parsed_now={parsed_this_run} "
        f"cache_parsed={parsed_cache_topics} legacy={len(legacy_samples())} "
        f"combined={len(all_samples)} market={len(merged_rows)} errors={len(topic_errors)}"
    )


if __name__ == "__main__":
    main()
