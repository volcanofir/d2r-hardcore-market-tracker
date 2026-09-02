import json
import re
import statistics
from datetime import datetime, timezone

import scraper_live as s

SEASON = 15
SEASON_LABEL = "第 15 季天梯"
DATA_START = "2026-08-22"
START_DATE = datetime(2026, 8, 22).date()
START_DT = datetime(2026, 8, 22, tzinfo=timezone.utc)
SOURCE_POLICY = "runes-c2-full-backfill-v4"
PRICE_PARSER = "season15-runes-c2-full-v4"
RUNE_SOURCE = s.RUNE_FORUM
ALT_RUNE_SOURCE = f"https://forums.d2jsp.org/forum.php?c=2&f={s.CFG['forum_id']}"

DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})\s+(\d{4})\s+(\d{1,2}:\d{2})(am|pm)\b",
    re.I,
)

RUNE_MAX_FG = {}
for names, cap in [
    (("El", "Eld", "Tir", "Nef", "Eth", "Ith", "Tal", "Ral", "Ort", "Thul", "Amn"), 250),
    (("Sol", "Shael", "Dol", "Hel", "Io", "Lum", "Ko", "Fal", "Lem"), 500),
    (("Pul", "Um"), 1200),
    (("Mal", "Ist"), 2500),
    (("Gul", "Vex"), 5000),
    (("Ohm", "Lo"), 9000),
    (("Sur", "Ber", "Jah", "Cham", "Zod"), 20000),
]:
    for name in names:
        RUNE_MAX_FG[name] = cap

RUNEWORD_CONTEXT = re.compile(
    r"\b(?:smoke|enigma|spirit|insight|infinity|hoto|heart of the oak|grief|fortitude|"
    r"treachery|lore|stealth|obedience|cta|call to arms|ancients pledge)\b",
    re.I,
)

_topic_dates = {}
_original_reader = s.reader
_original_parse_topic = s.parse_topic
_original_ambiguous = s.ambiguous_rune_context
_original_sample_valid = s.sample_valid
_original_summarize = s.summarize


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def topic_date_from_markdown(markdown):
    match = DATE_RE.search(markdown or "")
    if not match:
        return None
    month, day, year, clock, ampm = match.groups()
    try:
        return datetime.strptime(
            f"{month} {day} {year} {clock}{ampm.lower()}", "%b %d %Y %I:%M%p"
        ).date()
    except ValueError:
        return None


def named_rune_context(rune, text):
    low = (text or "").lower()
    if rune.lower() == "tal" and (
        re.search(r"\btal(?:'s|s)?\s+(?:rasha|set|armor|armour|ammy|amu|amulet|orb|mask|helm|belt|weapon)\b", low)
        or re.search(r"\bfull\s+tal\b", low)
    ):
        return True
    return False


def quantity_for_rune(rune, text):
    low = (text or "").lower()
    token = re.escape(rune.lower())
    for pattern in [
        rf"\b(\d+)\s*x\s*{token}\b",
        rf"\b(\d+)\s+{token}\b",
        rf"\b{token}\s*x\s*(\d+)\b",
        rf"\b{token}\s+(?:runes?\s*)?x\s*(\d+)\b",
    ]:
        match = re.search(pattern, low)
        if match:
            try:
                qty = int(match.group(1))
                return qty if qty > 1 else None
            except Exception:
                pass
    return None


def ambiguous_rune_context(rune, text):
    if _original_ambiguous(rune, text) or named_rune_context(rune, text):
        return True
    low = (text or "").lower()
    if RUNEWORD_CONTEXT.search(low) and not re.search(r"\brunes?\b", low):
        return True
    return False


def sample_valid(sample):
    if not _original_sample_valid(sample):
        return False
    if sample.get("kind") != "rune":
        return False

    rune = sample.get("id")
    value = sample.get("price_fg")
    title = sample.get("title", "")
    if rune not in RUNE_MAX_FG or not isinstance(value, (int, float)):
        return False
    if value > RUNE_MAX_FG[rune] or named_rune_context(rune, title):
        return False

    if sample.get("parser_v4") is True:
        return True
    if sample.get("parser_v3") or sample.get("parser_v2") or sample.get("legacy") or sample.get("topic_date"):
        return False
    return True


def strict_line_prices(line):
    """Extract rune FG prices conservatively, including clear bundle totals."""
    low = line.lower()
    hits = s.rune_mentions(line)
    if not hits:
        return []

    explicit_all = [
        s.nval(raw)
        for raw in re.findall(rf"{s.PRICE}\s*(?:fg|forum\s*gold)\b", low, re.I)
    ]
    explicit_all = [v for v in explicit_all if v is not None]
    found = []

    for index, (start, end, rune) in enumerate(hits):
        next_start = hits[index + 1][0] if index + 1 < len(hits) else len(low)
        before = low[max(0, start - 55):start]
        after = low[end:min(next_start, end + 80)]
        around = low[max(0, start - 45):min(len(low), end + 90)]
        price = None

        qty = quantity_for_rune(rune, around)
        per_unit = bool(re.search(r"\b(?:each|ea|per\s+rune|apiece)\b", around))

        # Clear bundle shorthand such as "2 Ist for 50fg" or "3x Vex 600fg".
        # Only divide when this line mentions one rune type and one explicit FG total.
        if qty and not per_unit:
            if len({hit[2] for hit in hits}) == 1 and len(explicit_all) == 1:
                total = explicit_all[0]
                derived = total / qty
                if 0 < derived <= RUNE_MAX_FG.get(rune, 100000):
                    price = derived
            if price is None:
                continue

        if price is None:
            match = re.search(
                rf"^(?:\s*rune)?\s*(?:=|:|-|@|for|vs|at|bin|price|pay|paying|sell(?:ing)?|ft|is|here|it|fast|quick|\s)*?"
                rf"{s.PRICE}\s*(?:fg|forum\s*gold)\b",
                after,
                re.I,
            )
            if match:
                price = s.nval(match.group(1))

        if price is None:
            match = re.search(
                rf"{s.PRICE}\s*(?:fg|forum\s*gold)\b\s*(?:each|ea|per\s+rune|for|@|=|:|-|paying|pay)?\s*$",
                before,
                re.I,
            )
            if match:
                price = s.nval(match.group(1))

        if price is None and len({hit[2] for hit in hits}) == 1 and len(explicit_all) == 1:
            price = explicit_all[0]

        if price is None:
            match = re.match(
                rf"\s*(?:rune\s*)?(?:=|:|-|@|for|vs|at|bin|price)\s*{s.PRICE}\s*(?:each|ea|per\s+rune|apiece)\b",
                after,
                re.I,
            )
            if match:
                price = s.nval(match.group(1))

        if price is not None and 0 < price <= RUNE_MAX_FG.get(rune, 100000):
            found.append((rune, round(price, 2)))

    dedup = []
    seen = set()
    for pair in found:
        if pair not in seen:
            seen.add(pair)
            dedup.append(pair)
    return dedup


def season_summarize(samples):
    return _original_summarize([sample for sample in samples if sample_valid(sample)])


def season_reader(url, timeout=35, retries=5):
    markdown = _original_reader(url, timeout=timeout, retries=retries)
    if "topic.php" in url:
        created = topic_date_from_markdown(markdown)
        _topic_dates[url] = created
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
        return result

    clean = []
    for sample in result.get("samples", []):
        if sample.get("kind") != "rune":
            continue
        sample["topic_date"] = created.isoformat()
        sample["parser_v4"] = True
        sample["rune_source"] = RUNE_SOURCE
        if sample_valid(sample):
            clean.append(sample)
    result["samples"] = clean
    return result


def read_forum_page(offset):
    suffix = "" if offset == 0 else f"&o={offset}"
    candidates = [RUNE_SOURCE + suffix, ALT_RUNE_SOURCE + suffix]
    attempts = []
    best = ([], "", candidates[0])

    for candidate in candidates:
        try:
            markdown = _original_reader(candidate, retries=5)
            found = s.topic_links(markdown)
            attempts.append({"url": candidate, "topics": len(found), "bytes": len(markdown)})
            if len(found) > len(best[0]):
                best = (found, markdown, candidate)
            if len(found) >= 20:
                break
        except Exception as exc:
            attempts.append({"url": candidate, "error": str(exc)})

    return best[0], best[1], best[2], attempts


def season_discover_topics():
    diagnostics = []
    links = []

    # Backfill enough pages to cover the Season 15 start. Alternate query-order
    # fallback avoids the occasional Jina empty response seen on o=25/o=50.
    for offset in range(0, 326, 25):
        found, markdown, used_url, attempts = read_forum_page(offset)
        links.extend(found)
        diagnostics.append({
            "url": used_url,
            "offset": offset,
            "topics": len(found),
            "bytes": len(markdown),
            "attempts": attempts,
        })

    dedup = {}
    for title, url in links:
        dedup.setdefault(url, title)
    return dedup, diagnostics


def merge_with_previous(new_rows, previous_market):
    # v4 rune data is rebuilt from scratch. Old custom-item samples were polluted
    # by parser v2, so do not carry them into the full-backfill snapshot.
    return [row for row in new_rows if row.get("kind") == "rune"]


def prepare_state():
    cache = load(s.CACHE_PATH, {})
    policy_changed = (
        cache.get("season") != SEASON
        or cache.get("data_start") != DATA_START
        or cache.get("rune_source_policy") != SOURCE_POLICY
    )

    if policy_changed:
        save(s.CACHE_PATH, {
            "version": 4,
            "season": SEASON,
            "season_label": SEASON_LABEL,
            "data_start": DATA_START,
            "rune_source_policy": SOURCE_POLICY,
            "rune_source": RUNE_SOURCE,
            "topics": {},
        })
        save(s.MARKET_PATH, {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "season": SEASON,
            "season_label": SEASON_LABEL,
            "data_start": DATA_START,
            "rune_source_policy": SOURCE_POLICY,
            "rune_source": RUNE_SOURCE,
            "market": [],
        })
        save(s.HISTORY_PATH, [])


def finalize_state():
    market = load(s.MARKET_PATH, {"market": []})
    market.update({
        "season": SEASON,
        "season_label": SEASON_LABEL,
        "data_start": DATA_START,
        "forum": RUNE_SOURCE,
        "rune_source": RUNE_SOURCE,
        "rune_source_policy": SOURCE_POLICY,
        "data_policy": "符文行情僅採用 d2jsp D2:R RotW Hardcore Ladder Trading 的 Runes 分類（f=123&c=2），只統計 2026/08/22（含）後主題；全量回填所有待解析主題，之後每 3 小時增量更新。明確 bundle 總價會換算單顆價格。",
        "price_parser": PRICE_PARSER,
    })
    save(s.MARKET_PATH, market)

    cache = load(s.CACHE_PATH, {"topics": {}})
    cache.update({
        "version": 4,
        "season": SEASON,
        "season_label": SEASON_LABEL,
        "data_start": DATA_START,
        "rune_source": RUNE_SOURCE,
        "rune_source_policy": SOURCE_POLICY,
    })
    save(s.CACHE_PATH, cache)

    diagnostic = load(s.DIAGNOSTIC_PATH, {})
    diagnostic.update({
        "season": SEASON,
        "season_label": SEASON_LABEL,
        "data_start": DATA_START,
        "rune_source": RUNE_SOURCE,
        "rune_source_policy": SOURCE_POLICY,
        "price_parser": PRICE_PARSER,
        "backfill_all_pending": True,
        "max_workers": s.MAX_WORKERS,
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
            row["rune_source"] = RUNE_SOURCE
            filtered.append(row)
    save(s.HISTORY_PATH, filtered)


s.reader = season_reader
s.ambiguous_rune_context = ambiguous_rune_context
s.sample_valid = sample_valid
s.line_prices = strict_line_prices
s.summarize = season_summarize
s.parse_topic = season_parse_topic
s.discover_topics = season_discover_topics
s.legacy_samples = lambda: []
s.merge_with_previous = merge_with_previous

# Full backlog in one run. Once pending is empty, the same setting naturally
# behaves as incremental-only because only newly discovered topics are pending.
s.NEW_TOPICS_PER_RUN = 10000
s.RECHECK_TOPICS_PER_RUN = 12
s.RECHECK_AFTER_HOURS = 6
s.CACHE_DAYS = 60
s.MAX_WORKERS = 4

prepare_state()
s.main()
finalize_state()
