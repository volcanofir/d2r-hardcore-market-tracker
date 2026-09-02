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
SOURCE_POLICY = "runes-c2-strict-v3"
RUNE_SOURCE = s.RUNE_FORUM  # https://forums.d2jsp.org/forum.php?f=123&c=2

DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})\s+(\d{4})\s+(\d{1,2}:\d{2})(am|pm)\b",
    re.I,
)

# Sanity ceilings only. They reject obvious item/bundle mis-parses; they are
# deliberately much wider than normal rune market prices.
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
    match = DATE_RE.search(markdown)
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
    """Return an explicit quantity (>1) next to a rune name, else None."""
    low = (text or "").lower()
    token = re.escape(rune.lower())
    patterns = [
        rf"\b(\d+)\s*x\s*{token}\b",
        rf"\b(\d+)\s+{token}\b",
        rf"\b{token}\s*x\s*(\d+)\b",
        rf"\b{token}\s+(?:runes?\s*)?x\s*(\d+)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, low)
        if m:
            try:
                q = int(m.group(1))
                return q if q > 1 else None
            except Exception:
                pass
    return None


def ambiguous_rune_context(rune, text):
    if _original_ambiguous(rune, text) or named_rune_context(rune, text):
        return True
    low = (text or "").lower()
    qty = quantity_for_rune(rune, text)
    if qty and not re.search(r"\b(?:each|ea|per\s+rune|apiece)\b", low):
        return True
    if RUNEWORD_CONTEXT.search(low) and not re.search(r"\brunes?\b", low):
        return True
    return False


def sample_valid(sample):
    if not _original_sample_valid(sample):
        return False
    if sample.get("kind") != "rune":
        return True

    rune = sample.get("id")
    value = sample.get("price_fg")
    title = sample.get("title", "")
    if rune not in RUNE_MAX_FG or not isinstance(value, (int, float)):
        return False
    if value > RUNE_MAX_FG[rune] or named_rune_context(rune, title):
        return False

    # After switching sources, old parser-v1/v2 rune samples are deliberately
    # not trusted. Every rune quote must be rebuilt from the c=2 Runes filter.
    return sample.get("parser_v3") is True


def strict_line_prices(line):
    """High-precision rune price extraction for the d2jsp Runes category.

    Rules:
    - Explicit FG near a rune is accepted.
    - A single-rune line with exactly one explicit FG amount is accepted.
    - Bare prices are only accepted with strong local separators/price words or
      an each/ea/per-rune suffix.
    - Multi-rune lines never use a loose global numeric fallback, preventing a
      price from one rune being assigned to another rune on the same list.
    - Quantities such as '2 Ohm'/'2x Lem' are not prices unless a per-rune cue
      (each/ea/per rune) is present.
    """
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
        after = low[end:min(next_start, end + 70)]
        around = low[max(0, start - 35):min(len(low), end + 70)]
        price = None

        qty = quantity_for_rune(rune, around)
        per_unit = bool(re.search(r"\b(?:each|ea|per\s+rune|apiece)\b", around))
        if qty and not per_unit:
            continue

        # Rune ... 190fg / Rune - 190 fg / Rune vs 190fg / Rune bin 190fg
        m = re.search(
            rf"^(?:\s*rune)?\s*(?:=|:|-|@|for|vs|at|bin|price|pay|paying|sell(?:ing)?|ft|is|here|it|fast|quick|\s)*?"
            rf"{s.PRICE}\s*(?:fg|forum\s*gold)\b",
            after,
            re.I,
        )
        if m:
            price = s.nval(m.group(1))

        # 190fg ... Rune, including 'paying 15fg each Um'.
        if price is None:
            m = re.search(
                rf"{s.PRICE}\s*(?:fg|forum\s*gold)\b\s*(?:each|ea|per\s+rune|for|@|=|:|-|paying|pay)?\s*$",
                before,
                re.I,
            )
            if m:
                price = s.nval(m.group(1))

        # In a single-rune line, one and only one explicit FG amount is safe
        # even if the words between rune and price are conversational.
        if price is None and len(hits) == 1 and len(explicit_all) == 1:
            price = explicit_all[0]

        # Category-specific shorthand: 'Gul - 50 each', 'Um @ 15 ea'.
        if price is None:
            m = re.match(
                rf"\s*(?:rune\s*)?(?:=|:|-|@|for|vs|at|bin|price)\s*{s.PRICE}\s*(?:each|ea|per\s+rune|apiece)\b",
                after,
                re.I,
            )
            if m:
                price = s.nval(m.group(1))

        if price is not None and 0 < price <= RUNE_MAX_FG.get(rune, 100000):
            found.append((rune, price))

    # Same rune can appear more than once in quoted/replied text. Keep unique
    # rune-price pairs per line.
    dedup = []
    seen = set()
    for pair in found:
        if pair not in seen:
            seen.add(pair)
            dedup.append(pair)
    return dedup


def season_summarize(samples):
    valid = [sample for sample in samples if sample_valid(sample)]
    return _original_summarize(valid)


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
        # c=2 is now exclusively the rune source. Do not let a stray item post
        # inside that category update the custom-equipment market.
        if sample.get("kind") != "rune":
            continue
        sample["topic_date"] = created.isoformat()
        sample["parser_v3"] = True
        sample["rune_source"] = RUNE_SOURCE
        if sample_valid(sample):
            clean.append(sample)
    result["samples"] = clean
    return result


def season_discover_topics():
    diagnostics = []
    links = []

    # Runes only. Pull enough category pages to reach back to Season 15 start;
    # cache retains all season samples after they are parsed.
    urls = [RUNE_SOURCE]
    urls += [RUNE_SOURCE + f"&o={offset}" for offset in range(25, 276, 25)]

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


def merge_with_previous(new_rows, previous_market):
    """Rebuild runes from c=2, while leaving custom equipment untouched."""
    merged = {row["id"]: row for row in new_rows if row.get("kind") == "rune"}
    for old in previous_market.get("market", []):
        if old.get("kind") == "item" and old.get("id") not in merged:
            merged[old.get("id")] = old
    return list(merged.values())


def prepare_state():
    cache = load(s.CACHE_PATH, {})
    market = load(s.MARKET_PATH, {"market": []})
    policy_changed = (
        cache.get("season") != SEASON
        or cache.get("data_start") != DATA_START
        or cache.get("rune_source_policy") != SOURCE_POLICY
    )

    if policy_changed:
        preserved_items = [row for row in market.get("market", []) if row.get("kind") == "item"]
        save(s.CACHE_PATH, {
            "version": 3,
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
            "market": preserved_items,
        })
        # Old rune history used mixed-source parser v2, so it must not be shown
        # as Season-15 c=2 history.
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
        "data_policy": "符文行情僅採用 d2jsp D2:R RotW Hardcore Ladder Trading 的 Runes 分類（f=123&c=2），且只統計 2026/08/22（含）後主題；多符文價目表必須能明確配對符文與價格，數量不視為價格。",
        "price_parser": "season15-runes-c2-strict-v3",
    })
    save(s.MARKET_PATH, market)

    cache = load(s.CACHE_PATH, {"topics": {}})
    cache.update({
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
        "price_parser": "season15-runes-c2-strict-v3",
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


# Apply the Season 15 / Runes-category policy before scraper_live.main() reads data.
s.reader = season_reader
s.ambiguous_rune_context = ambiguous_rune_context
s.sample_valid = sample_valid
s.line_prices = strict_line_prices
s.summarize = season_summarize
s.parse_topic = season_parse_topic
s.discover_topics = season_discover_topics
s.legacy_samples = lambda: []
s.merge_with_previous = merge_with_previous
s.NEW_TOPICS_PER_RUN = 24
s.RECHECK_TOPICS_PER_RUN = 6
s.CACHE_DAYS = 60

prepare_state()
s.main()
finalize_state()
