import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

import scraper_live as s

ROOT = Path(__file__).parent
DATA = ROOT / "data"
CACHE_PATH = DATA / "item_topic_cache.json"
DIAGNOSTIC_PATH = DATA / "item_diagnostic.json"
CATALOG_PATH = DATA / "catalog.json"
START_DATE = datetime(2026, 8, 22).date()
START_DT = datetime(2026, 8, 22, tzinfo=timezone.utc)
SOURCE_POLICY = "season15-items-all-uniques-v2"
MAX_WORKERS = 2
RECHECK_AFTER_HOURS = 6
CACHE_DAYS = 30
DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})\s+(\d{4})\s+(\d{1,2}:\d{2})(am|pm)\b",
    re.I,
)


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def now():
    return datetime.now(timezone.utc)


def iso_now():
    return now().isoformat()


def parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def topic_date(markdown):
    m = DATE_RE.search(markdown or "")
    if not m:
        return None
    month, day, year, clock, ampm = m.groups()
    try:
        return datetime.strptime(
            f"{month} {day} {year} {clock}{ampm.lower()}", "%b %d %Y %I:%M%p"
        ).date()
    except ValueError:
        return None


def tracked_items():
    catalog = load(CATALOG_PATH, {})
    items = catalog.get("items", [])
    if items:
        return items
    return s.CFG.get("items", [])


TRACKED_ITEMS = tracked_items()
ITEM_BY_ID = {item["id"]: item for item in TRACKED_ITEMS if item.get("id")}


def alias_regex(alias):
    escaped = re.escape(alias.lower()).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.I)


ITEM_PATTERNS = []
for item in TRACKED_ITEMS:
    patterns = [(alias, alias_regex(alias)) for alias in item.get("aliases", []) if alias.strip()]
    patterns.sort(key=lambda pair: len(pair[0]), reverse=True)
    ITEM_PATTERNS.append((item, patterns))


def item_hits(line):
    low = line.lower()
    hits = []
    for item, patterns in ITEM_PATTERNS:
        best = None
        for alias, pattern in patterns:
            m = pattern.search(low)
            if m:
                candidate = (m.start(), m.end(), alias)
                if best is None or len(alias) > len(best[2]):
                    best = candidate
        if best:
            hits.append((best[0], best[1], item, best[2]))

    # When two catalog entries overlap the same text, keep the most specific
    # (longest) match. This protects curated variants from generic names.
    hits.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    filtered = []
    for hit in hits:
        start, end = hit[0], hit[1]
        if any(not (end <= prev[0] or start >= prev[1]) for prev in filtered):
            continue
        filtered.append(hit)
    return sorted(filtered, key=lambda x: x[0])


def explicit_prices(line):
    prices = []
    for m in re.finditer(rf"{s.PRICE}\s*(?:fg|forum\s*gold)\b", line, re.I):
        value = s.nval(m.group(1))
        if value is not None:
            prices.append((m.start(), m.end(), value))
    return prices


def line_item_prices(line):
    hits = item_hits(line)
    prices = explicit_prices(line)
    if not hits or not prices:
        return []

    # One named item + one explicit FG amount is a high-confidence pairing.
    if len(hits) == 1 and len(prices) == 1:
        return [(hits[0][2], prices[0][2])]

    # Multi-item shop lines: pair every item with the nearest still-unused FG
    # amount, but only within a tight local window to avoid cross-assignment.
    result = []
    used = set()
    for start, end, item, _alias in hits:
        best = None
        for i, (pstart, pend, value) in enumerate(prices):
            if i in used:
                continue
            if pstart >= end:
                distance = pstart - end
            elif pend <= start:
                distance = start - pend
            else:
                distance = 0
            if distance <= 80 and (best is None or distance < best[0]):
                best = (distance, i, value)
        if best:
            used.add(best[1])
            result.append((item, best[2]))
    return result


def parse_topic(title, url):
    markdown = s.reader(url, retries=5)
    created = topic_date(markdown)
    checked_at = iso_now()
    if created is None or created < START_DATE:
        return {
            "title": title,
            "url": url,
            "topic_date": created.isoformat() if created else None,
            "completed": True,
            "samples": [],
            "checked_at": checked_at,
        }

    side = s.side_of(title)
    samples = []
    seen = set()
    unique_item_ids = set()
    prices_by_item = {}

    for raw in markdown.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or len(line) > 700:
            continue
        for item, value in line_item_prices(line):
            key = (item["id"], side, value)
            if key in seen:
                continue
            seen.add(key)
            unique_item_ids.add(item["id"])
            prices_by_item.setdefault(item["id"], []).append(value)
            samples.append({
                "kind": "item",
                "id": item["id"],
                "label": item["label"],
                "category": item.get("category", "其他"),
                "side": side,
                "price_fg": value,
                "title": title,
                "url": url,
                "observed_at": checked_at,
                "topic_date": created.isoformat(),
                "item_parser_v2": True,
            })

    # A thread-wide sold/T4T signal is only safe when exactly one tracked item
    # was price-matched in the whole topic. Multi-item shops are not promoted to
    # trades merely because one line says sold.
    completed = bool(s.COMPLETE.search(markdown))
    if completed and len(unique_item_ids) == 1:
        item_id = next(iter(unique_item_ids))
        vals = prices_by_item.get(item_id, [])
        if vals:
            item = ITEM_BY_ID.get(item_id)
            if item:
                trade_value = sorted(vals)[len(vals) // 2]
                samples.append({
                    "kind": "item",
                    "id": item_id,
                    "label": item["label"],
                    "category": item.get("category", "其他"),
                    "side": "trade",
                    "price_fg": trade_value,
                    "title": title + " · T4T/sold signal",
                    "url": url,
                    "observed_at": checked_at,
                    "topic_date": created.isoformat(),
                    "item_parser_v2": True,
                })

    return {
        "title": title,
        "url": url,
        "topic_date": created.isoformat(),
        "completed": completed,
        "samples": samples,
        "checked_at": checked_at,
    }


def discover_topics():
    diagnostics = []
    discovered = {}
    pages = max(1, int(s.CFG.get("item_pages", 8)))
    for offset in range(0, pages * 25, 25):
        url = s.FORUM if offset == 0 else s.FORUM + f"&o={offset}"
        try:
            markdown = s.reader(url, retries=4)
            found = s.topic_links(markdown)
            diagnostics.append({"url": url, "offset": offset, "topics": len(found), "bytes": len(markdown)})
            for title, topic_url in found:
                discovered.setdefault(topic_url, title)
        except Exception as exc:
            diagnostics.append({"url": url, "offset": offset, "error": str(exc)})
    return discovered, diagnostics


def prune(cache):
    cutoff = now() - timedelta(days=CACHE_DAYS)
    keep = {}
    for url, entry in cache.get("topics", {}).items():
        first = parse_dt(entry.get("first_seen_at")) or parse_dt(entry.get("last_checked_at"))
        if first is None or first >= cutoff:
            keep[url] = entry
    cache["topics"] = keep
    return cache


def selected_topics(cache):
    current = now()
    pending = []
    recheck = []
    for url, entry in cache.get("topics", {}).items():
        if entry.get("status") != "parsed":
            pending.append((entry.get("first_seen_at", ""), entry.get("title", "d2jsp topic"), url))
            continue
        if entry.get("completed"):
            continue
        checked = parse_dt(entry.get("last_checked_at"))
        if checked and current - checked >= timedelta(hours=RECHECK_AFTER_HOURS):
            recheck.append((entry.get("first_seen_at", ""), entry.get("title", "d2jsp topic"), url))
    pending.sort(reverse=True)
    recheck.sort(reverse=True)
    # Full pending backfill on the first catalog run; later runs are naturally
    # incremental because parsed topics remain cached.
    return [(title, url, "new") for _, title, url in pending] + [
        (title, url, "recheck") for _, title, url in recheck[:20]
    ]


def aggregate(cache):
    dedup = {}
    for entry in cache.get("topics", {}).values():
        if entry.get("status") != "parsed":
            continue
        for sample in entry.get("samples", []):
            if sample.get("kind") != "item" or not sample.get("item_parser_v2"):
                continue
            key = (sample.get("id"), sample.get("side"), sample.get("price_fg"), sample.get("url"))
            dedup[key] = sample
    return list(dedup.values())


def main():
    market = load(s.MARKET_PATH, {"market": []})
    cache = prune(load(CACHE_PATH, {"version": 2, "topics": {}}))
    if cache.get("source_policy") != SOURCE_POLICY:
        cache = {"version": 2, "source_policy": SOURCE_POLICY, "topics": {}}

    discovered, forum_pages = discover_topics()
    stamp = iso_now()
    topics = cache.setdefault("topics", {})
    for url, title in discovered.items():
        if url not in topics:
            topics[url] = {
                "title": title,
                "url": url,
                "first_seen_at": stamp,
                "last_checked_at": None,
                "completed": False,
                "status": "pending",
                "samples": [],
            }
        else:
            topics[url]["title"] = title or topics[url].get("title")

    selected = selected_topics(cache)
    errors = []
    parsed_now = 0
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
                entry["topic_date"] = result.get("topic_date")
                entry["completed"] = result["completed"]
                entry["status"] = "parsed"
                entry["samples"] = result["samples"]
                entry.pop("last_error", None)
                parsed_now += 1
            except Exception as exc:
                entry = topics[url]
                entry["last_attempt_at"] = iso_now()
                entry["last_error"] = str(exc)
                errors.append({"url": url, "title": title, "reason": reason, "error": str(exc)})

    cache = prune(cache)
    cache["source_policy"] = SOURCE_POLICY
    cache["updated_at"] = iso_now()
    save(CACHE_PATH, cache)

    samples = aggregate(cache)
    item_rows = [row for row in s.summarize(samples) if row.get("kind") == "item"]
    categories = {item["id"]: item.get("category", "其他") for item in TRACKED_ITEMS}
    for row in item_rows:
        row["category"] = categories.get(row.get("id"), "其他")

    rune_rows = [row for row in market.get("market", []) if row.get("kind") == "rune"]
    market["market"] = rune_rows + item_rows
    market["updated_at"] = iso_now()
    market["item_source_policy"] = SOURCE_POLICY
    market["item_catalog_count"] = len(TRACKED_ITEMS)
    market["item_topic_count"] = len(discovered)
    market["item_cached_topics"] = len(cache.get("topics", {}))
    market["item_parsed_topics"] = sum(1 for x in cache.get("topics", {}).values() if x.get("status") == "parsed")
    market["item_sample_count"] = sum(row.get("samples", 0) for row in item_rows)
    save(s.MARKET_PATH, market)

    save(DIAGNOSTIC_PATH, {
        "updated_at": iso_now(),
        "source_policy": SOURCE_POLICY,
        "catalog_items": len(TRACKED_ITEMS),
        "forum_pages": forum_pages,
        "discovered_topics": len(discovered),
        "cached_topics": len(cache.get("topics", {})),
        "selected_topics": len(selected),
        "parsed_this_run": parsed_now,
        "combined_samples": len(samples),
        "market_items": len(item_rows),
        "topic_errors": errors[:30],
    })

    history = load(s.HISTORY_PATH, [])
    history.append({
        "at": market["updated_at"],
        "prices": {row["id"]: row.get("fair_fg") for row in market["market"] if row.get("fair_fg") is not None},
    })
    cutoff = now() - timedelta(days=60)
    history = [h for h in history if (parse_dt(h.get("at")) or cutoff) >= cutoff]
    save(s.HISTORY_PATH, history)

    print(
        f"items catalog={len(TRACKED_ITEMS)} discovered={len(discovered)} selected={len(selected)} "
        f"parsed_now={parsed_now} cache_parsed={market['item_parsed_topics']} "
        f"samples={len(samples)} market_items={len(item_rows)} errors={len(errors)}"
    )


if __name__ == "__main__":
    main()
