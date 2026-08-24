import json
import re
from datetime import datetime, timezone

import scraper_live as s

SEASON = 15
SEASON_LABEL = "第 15 季天梯"
DATA_START = "2026-08-22"
START_DATE = datetime(2026, 8, 22).date()
START_DT = datetime(2026, 8, 22, tzinfo=timezone.utc)
DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})\s+(\d{4})\s+(\d{1,2}:\d{2})(am|pm)\b",
    re.I,
)

_topic_dates = {}
_original_reader = s.reader
_original_parse_topic = s.parse_topic


def topic_date_from_markdown(markdown):
    match = DATE_RE.search(markdown)
    if not match:
        return None
    month, day, year, clock, ampm = match.groups()
    try:
        return datetime.strptime(
            f"{month} {day} {year} {clock}{ampm.lower()}",
            "%b %d %Y %I:%M%p",
        ).date()
    except ValueError:
        return None


def season_reader(url, timeout=35, retries=5):
    markdown = _original_reader(url, timeout=timeout, retries=retries)
    if "topic.php" in url:
        created = topic_date_from_markdown(markdown)
        _topic_dates[url] = created
        # Old topics are intentionally converted to a completed/no-price page.
        # parse_topic will therefore cache them once without contributing samples.
        if created is None or created < START_DATE:
            return "sold\n"
    return markdown


def season_parse_topic(title, url):
    result = _original_parse_topic(title, url)
    created = _topic_dates.get(url)
    in_season = created is not None and created >= START_DATE
    result["in_season"] = in_season
    result["topic_date"] = created.isoformat() if created else None
    if not in_season:
        result["samples"] = []
        result["completed"] = True
    else:
        for sample in result.get("samples", []):
            sample["topic_date"] = created.isoformat()
    return result


def season_discover_topics():
    diagnostics = []
    links = []
    urls = [s.RUNE_FORUM]
    urls += [s.RUNE_FORUM + f"&o={offset}" for offset in (25, 50, 75)]
    urls.append(s.FORUM)

    for url in urls:
        try:
            markdown = s.reader(url, retries=4)
            found = s.topic_links(markdown)
            links.extend(found)
            diagnostics.append({"url": url, "topics": len(found), "bytes": len(markdown)})
        except Exception as exc:
            diagnostics.append({"url": url, "error": str(exc)})

    dedup = {}
    for title, url in links:
        dedup.setdefault(url, title)
    return dedup, diagnostics


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_season_state():
    cache = load(s.CACHE_PATH, {})
    market = load(s.MARKET_PATH, {})
    season_changed = cache.get("season") != SEASON or cache.get("data_start") != DATA_START

    if season_changed:
        save(s.CACHE_PATH, {
            "version": 2,
            "season": SEASON,
            "season_label": SEASON_LABEL,
            "data_start": DATA_START,
            "topics": {},
        })
        save(s.MARKET_PATH, {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "season": SEASON,
            "season_label": SEASON_LABEL,
            "data_start": DATA_START,
            "market": [],
        })
        save(s.HISTORY_PATH, [])
    elif market.get("season") != SEASON or market.get("data_start") != DATA_START:
        market["season"] = SEASON
        market["season_label"] = SEASON_LABEL
        market["data_start"] = DATA_START
        save(s.MARKET_PATH, market)


def finalize_season_state():
    market = load(s.MARKET_PATH, {"market": []})
    market.update({
        "season": SEASON,
        "season_label": SEASON_LABEL,
        "data_start": DATA_START,
        "data_policy": "僅統計 d2jsp 於 2026/08/22（含）之後建立的主題",
    })
    save(s.MARKET_PATH, market)

    cache = load(s.CACHE_PATH, {"topics": {}})
    cache.update({
        "season": SEASON,
        "season_label": SEASON_LABEL,
        "data_start": DATA_START,
    })
    save(s.CACHE_PATH, cache)

    diagnostic = load(s.DIAGNOSTIC_PATH, {})
    diagnostic.update({
        "season": SEASON,
        "season_label": SEASON_LABEL,
        "data_start": DATA_START,
    })
    save(s.DIAGNOSTIC_PATH, diagnostic)

    history = load(s.HISTORY_PATH, [])
    filtered = []
    for row in history:
        try:
            at = datetime.fromisoformat(row.get("at", ""))
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if at >= START_DT:
            row["season"] = SEASON
            row["data_start"] = DATA_START
            filtered.append(row)
    save(s.HISTORY_PATH, filtered)


# Patch only the live network/date boundary. Keep the existing price parser intact.
s.reader = season_reader
s.parse_topic = season_parse_topic
s.discover_topics = season_discover_topics
s.legacy_samples = lambda: []
s.merge_with_previous = lambda new_rows, previous_market: new_rows
s.NEW_TOPICS_PER_RUN = 18

prepare_season_state()
s.main()
finalize_season_state()
