import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scraper_live as s

ROOT = Path(__file__).parent
MARKET_PATH = ROOT / "data" / "market.json"
CACHE_PATH = ROOT / "data" / "source_time_cache.json"
START_DATE = datetime(2026, 8, 22).date()
MAX_NEW_PER_RUN = 240

DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})\s+(\d{4})\s+(\d{1,2}:\d{2})(am|pm)\b",
    re.I,
)
POST1_RE = re.compile(r"#\s*1(?!\d)")


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_matches(markdown):
    matches = []
    for m in DATE_RE.finditer(markdown or ""):
        month, day, year, clock, ampm = m.groups()
        try:
            dt = datetime.strptime(
                f"{month} {day} {year} {clock}{ampm.lower()}", "%b %d %Y %I:%M%p"
            )
        except ValueError:
            continue
        if dt.date() < START_DATE or dt.date() > (datetime.now().date() + timedelta(days=1)):
            continue
        matches.append((m, dt))
    return matches


def original_post_time(markdown):
    matches = parse_matches(markdown)
    if not matches:
        return None

    # d2jsp renders the original post timestamp next to post marker #1.
    # Prefer the timestamp closest to #1 when that marker survives reader conversion.
    markers = [m.start() for m in POST1_RE.finditer(markdown or "")]
    if markers:
        ranked = []
        for match, dt in matches:
            distance = min(abs(match.end() - marker) for marker in markers)
            ranked.append((distance, match.start(), dt))
        ranked.sort(key=lambda x: (x[0], x[1]))
        if ranked[0][0] <= 600:
            return ranked[0][2]

    # Fallback: the original topic post is the earliest full post timestamp on the page.
    return min(dt for _match, dt in matches)


def display_time(dt):
    return f"{dt.year}/{dt.month}/{dt.day} {dt:%H:%M}"


def round_robin_urls(rows):
    sources_by_row = [row.get("sources", []) for row in rows]
    seen = set()
    ordered = []
    depth = 0
    while True:
        added = False
        for sources in sources_by_row:
            if depth >= len(sources):
                continue
            added = True
            src = sources[depth]
            url = src.get("url") if isinstance(src, dict) else None
            if url and url not in seen:
                seen.add(url)
                ordered.append(url)
        if not added:
            break
        depth += 1
    return ordered


def apply_cached_times(market, cache):
    changed = 0
    for row in market.get("market", []):
        for src in row.get("sources", []):
            info = cache.get(src.get("url", ""))
            if not info:
                continue
            if src.get("topic_date") != info.get("topic_date"):
                src["topic_date"] = info.get("topic_date")
                changed += 1
            if src.get("topic_time") != info.get("topic_time"):
                src["topic_time"] = info.get("topic_time")
                changed += 1
    return changed


def main():
    market = load(MARKET_PATH, {"market": []})
    cache = load(CACHE_PATH, {})
    urls = round_robin_urls(market.get("market", []))
    pending = [url for url in urls if url not in cache][:MAX_NEW_PER_RUN]

    ok = 0
    failed = 0
    for index, url in enumerate(pending, 1):
        try:
            markdown = s.reader(url, retries=4)
            dt = original_post_time(markdown)
            if dt is None:
                raise RuntimeError("no original-post timestamp found")
            cache[url] = {
                "topic_date": dt.date().isoformat(),
                "topic_time": display_time(dt),
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            ok += 1
            print(f"[{index}/{len(pending)}] {url} -> {display_time(dt)}")
        except Exception as exc:
            failed += 1
            print(f"[{index}/{len(pending)}] failed {url}: {exc}")

    changed = apply_cached_times(market, cache)
    save(CACHE_PATH, cache)
    save(MARKET_PATH, market)
    print(json.dumps({
        "source_urls": len(urls),
        "cached": len(cache),
        "checked_this_run": len(pending),
        "success": ok,
        "failed": failed,
        "market_fields_updated": changed,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
