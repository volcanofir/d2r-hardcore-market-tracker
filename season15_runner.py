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
DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2})\s+(\d{4})\s+(\d{1,2}:\d{2})(am|pm)\b",
    re.I,
)

# Wide sanity ceilings. These are not price targets; they only reject obviously
# mis-parsed totals/item prices (for example a 1000 FG Tal Rasha set as Tal rune).
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

LOW_MID_RUNES = set(s.CFG["runes"][:23])  # El through Mal
GENERIC_TRADE_WORDS = {
    "a", "all", "ball", "bin", "bins", "buy", "buying", "fast", "ft", "iso",
    "list", "low", "n", "need", "o", "offer", "offers", "pay", "paying", "quick",
    "sale", "sell", "selling", "short", "small", "some", "stuff", "trade", "trades",
    "wts", "wtb", "for", "fg", "forum", "gold", "run", "runs", "rune", "runes",
}
RUNEWORD_CONTEXT = re.compile(
    r"\b(?:smoke|enigma|spirit|insight|infinity|hoto|heart of the oak|grief|fortitude|"
    r"treachery|lore|stealth|obedience|cta|call to arms|ancients pledge)\b",
    re.I,
)

_topic_dates = {}
_original_reader = s.reader
_original_parse_topic = s.parse_topic
_original_ambiguous_rune_context = s.ambiguous_rune_context
_original_sample_valid = s.sample_valid
_original_summarize = s.summarize


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


def named_rune_context(rune, text):
    low = (text or "").lower()
    if rune.lower() == "tal":
        if re.search(
            r"\btal(?:'s|s)?\s+(?:rasha|set|armor|armour|ammy|amu|amulet|orb|mask|helm|belt|weapon)\b",
            low,
        ) or re.search(r"\bfull\s+tal\b", low):
            return True
    return False


def ambiguous_bundle_title(rune, title):
    low = (title or "").lower()
    token = re.escape(rune.lower())
    quantity = re.search(rf"\b(\d+)\s*x\s*{token}\b|\b{token}\s*x\s*(\d+)\b", low)
    if not quantity or re.search(r"\b(?:each|ea|per\s+rune)\b", low):
        return False
    # If the title itself has one total price or clearly combines multiple things,
    # the amount is a bundle total, not a per-rune quote.
    return bool(
        re.search(r"\b\d+(?:\.\d+)?\s*[kK]?\s*(?:fg|forum\s*gold)\b", low)
        or re.search(r"(?:\+|\band\b|\bfull\b|\bset\b|\bbundle\b|\bpack\b)", low)
    )


def season_ambiguous_rune_context(rune, text):
    if _original_ambiguous_rune_context(rune, text):
        return True
    if named_rune_context(rune, text):
        return True

    low = (text or "").lower()
    token = re.escape(rune.lower())
    quantity = re.search(rf"\b\d+\s*x\s*{token}\b|\b{token}\s*x\s*\d+\b", low)
    if quantity and not re.search(r"\b(?:each|ea|per\s+rune)\b", low):
        return True

    # Recipes/runeword descriptions are a common source of false rune prices.
    if RUNEWORD_CONTEXT.search(low) and not re.search(r"\brunes?\b", low):
        return True
    return False


def cached_title_supports_rune(rune, title):
    low = (title or "").lower()
    if named_rune_context(rune, title) or ambiguous_bundle_title(rune, title):
        return False
    token = re.escape(rune.lower())
    if re.search(rf"(?<![a-z]){token}(?![a-z])", low) or re.search(r"\brunes?\b", low):
        return True

    # Keep old cache entries from generic trade-list titles such as "Small Ft",
    # but reject specific item posts such as "Gc Warcries Skiller" or "Iso Smoke".
    words = re.findall(r"[a-z]+", low)
    meaningful = [word for word in words if word not in GENERIC_TRADE_WORDS]
    return not meaningful


def season_sample_valid(sample):
    if not _original_sample_valid(sample):
        return False
    if sample.get("kind") != "rune":
        return True

    rune = sample.get("id")
    value = sample.get("price_fg")
    title = sample.get("title", "")
    if rune not in RUNE_MAX_FG or not isinstance(value, (int, float)):
        return False
    if named_rune_context(rune, title) or ambiguous_bundle_title(rune, title):
        return False
    if value > RUNE_MAX_FG[rune]:
        return False

    # Old cached samples did not preserve their source line. Use a high-precision
    # title check for those; newly parsed v2 samples use the strict line parser.
    if not sample.get("parser_v2") and not cached_title_supports_rune(rune, title):
        return False
    return True


def strict_line_prices(line):
    low = line.lower()
    hits = s.rune_mentions(line)
    if not hits:
        return []

    found = []
    has_price_context = bool(re.search(r"\b(?:fg|forum\s*gold|bin|price|pay|paying|offer|vs)\b", low))

    for index, (start, end, rune) in enumerate(hits):
        next_start = hits[index + 1][0] if index + 1 < len(hits) else len(low)
        after = low[end:min(next_start, end + 36)]
        before = low[max(0, start - 36):start]
        price = None

        explicit_after = re.match(
            rf"\s*(?:rune\s*)?(?:=|:|-|@|for|vs|at)?\s*{s.PRICE}\s*(?:fg|forum\s*gold)\b",
            after,
            re.I,
        )
        if explicit_after:
            price = s.nval(explicit_after.group(1))

        if price is None:
            explicit_before = re.search(
                rf"{s.PRICE}\s*(?:fg|forum\s*gold)\b\s*(?:for|@|=|:|-)?\s*$",
                before,
                re.I,
            )
            if explicit_before:
                price = s.nval(explicit_before.group(1))

        if price is None:
            bare_after = re.match(
                rf"\s*(?:rune\s*)?(?:=|:|-|@|for|vs|at)?\s*{s.PRICE}(?!\s*x\b)",
                after,
                re.I,
            )
            if bare_after and (has_price_context or len(hits) >= 2):
                price = s.nval(bare_after.group(1))

        if price is not None and price <= RUNE_MAX_FG.get(rune, 100000):
            found.append((rune, price))

    return found


def season_summarize(samples):
    valid = [sample for sample in samples if season_sample_valid(sample)]

    # Extra robust filter for low/mid runes when enough observations exist.
    grouped = {}
    for sample in valid:
        if sample.get("kind") == "rune" and sample.get("side") != "trade":
            grouped.setdefault(sample.get("id"), []).append(sample.get("price_fg"))

    upper_by_rune = {}
    for rune, values in grouped.items():
        values = [v for v in values if isinstance(v, (int, float)) and v > 0]
        if rune in LOW_MID_RUNES and len(values) >= 5:
            med = statistics.median(values)
            upper_by_rune[rune] = min(RUNE_MAX_FG[rune], max(med * 6, med + 100))

    if upper_by_rune:
        valid = [
            sample for sample in valid
            if sample.get("kind") != "rune"
            or sample.get("id") not in upper_by_rune
            or sample.get("price_fg", 0) <= upper_by_rune[sample.get("id")]
        ]
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
    else:
        for sample in result.get("samples", []):
            sample["topic_date"] = created.isoformat()
            sample["parser_v2"] = True
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


def sanitize_cached_samples():
    cache = load(s.CACHE_PATH, {"topics": {}})
    removed = 0
    for entry in cache.get("topics", {}).values():
        samples = entry.get("samples", [])
        clean = [sample for sample in samples if season_sample_valid(sample)]
        removed += len(samples) - len(clean)
        entry["samples"] = clean
    if removed:
        save(s.CACHE_PATH, cache)
    return removed


def finalize_season_state(removed_cached):
    market = load(s.MARKET_PATH, {"market": []})
    market.update({
        "season": SEASON,
        "season_label": SEASON_LABEL,
        "data_start": DATA_START,
        "data_policy": "僅統計 d2jsp 於 2026/08/22（含）之後建立的主題；排除套裝/符文之語境誤判、整包總價與極端離群值",
        "price_parser": "season15-strict-v2",
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
        "price_parser": "season15-strict-v2",
        "invalid_cached_samples_removed": removed_cached,
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


# Apply Season 15 date boundary and strict rune-price parsing before main() reads cache.
s.reader = season_reader
s.ambiguous_rune_context = season_ambiguous_rune_context
s.sample_valid = season_sample_valid
s.line_prices = strict_line_prices
s.summarize = season_summarize
s.parse_topic = season_parse_topic
s.discover_topics = season_discover_topics
s.legacy_samples = lambda: []
s.merge_with_previous = lambda new_rows, previous_market: new_rows
s.NEW_TOPICS_PER_RUN = 18

prepare_season_state()
removed_cached = sanitize_cached_samples()
s.main()
finalize_season_state(removed_cached)
