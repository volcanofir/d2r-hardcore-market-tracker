import json
import random
import re
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
MANUAL_PATH = ROOT / "config" / "watchlist.json"
SOURCE_PATH = DATA / "d2r_world_uniques.json"
CATALOG_PATH = DATA / "catalog.json"
BASE_URL = "https://d2r.world/zh-TW/info/item/unique"
JINA_PREFIX = "https://r.jina.ai/https://"
STALE_DAYS = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

# Exact category slugs are taken from the site's category links.
CATEGORIES = [
    ("helms", "頭盔"),
    ("armors", "護甲"),
    ("shields", "盾牌"),
    ("belts", "腰帶"),
    ("boots", "鞋子"),
    ("gloves", "手套"),
    ("rings", "戒指"),
    ("amulets", "護身符"),
    ("charms", "咒符"),
    ("jewels", "珠寶"),
    ("swords", "刀劍"),
    ("daggers", "匕首"),
    ("axes", "斧"),
    ("polearms", "長柄武器"),
    ("spears", "長矛"),
    ("clubs", "短棒"),
    ("puremaces", "釘鎚"),
    ("hammers", "重槌"),
    ("scepters", "權杖"),
    ("staves", "法杖"),
    ("orbs", "法珠"),
    ("wands", "魔杖"),
    ("katars", "拳刃"),
    ("bows", "弓"),
    ("crossbows", "弩"),
    ("javelins", "標槍"),
    ("throwings", "投擲武器"),
]

# The first capture is the Traditional-Chinese name, the second is the English
# canonical name. Keep the English side broad because a few uniques contain
# punctuation beyond apostrophes/hyphens.
ITEM_RE = re.compile(r"^(.{1,100}?)\s*\(([^()]{2,100})\)$")
OLD_RE = re.compile(r"^舊名[：:]\s*(.+)$")
QLVL_RE = re.compile(r"Qlvl\s*[：:]\s*(\d+)", re.I)
TC_RE = re.compile(r"^TC\s*[：:]\s*([0-9]+|-)\s*$", re.I)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def now():
    return datetime.now(timezone.utc)


def normalize(text):
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text):
    value = normalize(text)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "unique-item"


def clean_markdown_line(raw):
    line = str(raw or "").strip()
    # Preserve visible link text and remove Markdown decoration.
    line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"^[\s#>*-]+", "", line)
    line = line.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", line).strip()


def readable_lines(url, retries=6):
    target = JINA_PREFIX + url.removeprefix("https://").removeprefix("http://")
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.get(target, headers=HEADERS, timeout=45)
            if response.status_code == 429:
                last_error = f"429 Too Many Requests ({attempt + 1}/{retries})"
                time.sleep(min(35, 3 * (2 ** attempt)) + random.uniform(0.3, 1.2))
                continue
            response.raise_for_status()
            text = response.text
            if len(text) < 500:
                raise RuntimeError(f"reader returned only {len(text)} bytes")
            lines = [clean_markdown_line(x) for x in text.splitlines()]
            return [x for x in lines if x]
        except Exception as exc:
            last_error = str(exc)
            if attempt < retries - 1:
                time.sleep(min(20, 2 * (attempt + 1)) + random.uniform(0.2, 0.8))
    raise RuntimeError(last_error or "D2R World reader failed")


def alias_variants(english, chinese=None, old_chinese=None):
    aliases = []

    def add(value):
        value = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(value) >= 2 and value.lower() not in {x.lower() for x in aliases}:
            aliases.append(value)

    add(english)
    add(english.replace("’", "'"))
    add(english.replace("'", ""))
    add(english.replace("’", ""))
    add(english.replace("-", " "))
    if english.lower().startswith("the ") and len(english) > 7:
        add(english[4:])
    add(chinese)
    add(old_chinese)
    return aliases


def extract_value(lines, index, pattern):
    m = pattern.search(lines[index])
    if m:
        return m.group(1)
    for j in range(index + 1, min(len(lines), index + 4)):
        if re.fullmatch(r"\d+|-", lines[j]):
            return lines[j]
        if ITEM_RE.match(lines[j]):
            break
    return None


def looks_like_item(zh, en):
    zh = zh.strip()
    en = en.strip()
    if zh in {"搜尋", "Search"} or len(en) < 3:
        return False
    if not re.search(r"[A-Za-z]", en):
        return False
    # UI/common non-item labels seen around the page shell.
    if normalize(en) in {"search", "qlvl", "tc", "privacy policy", "terms of service"}:
        return False
    return True


def parse_category(slug, category):
    url = f"{BASE_URL}/{slug}"
    lines = readable_lines(url)

    items = []
    current = None
    seen = set()

    for i, line in enumerate(lines):
        m = ITEM_RE.match(line)
        if m:
            zh, en = (x.strip() for x in m.groups())
            if not looks_like_item(zh, en):
                continue
            key = normalize(en)
            if key in seen:
                current = next((x for x in items if normalize(x["name_en"]) == key), None)
                continue
            seen.add(key)
            current = {
                "name_zh": zh,
                "name_en": en,
                "old_name_zh": None,
                "category": category,
                "category_slug": slug,
                "qlvl": None,
                "tc": None,
                "source_url": url,
            }
            items.append(current)
            continue

        if current is None:
            continue

        old = OLD_RE.match(line)
        if old and not current.get("old_name_zh"):
            current["old_name_zh"] = old.group(1).strip()
            continue

        if "Qlvl" in line and current.get("qlvl") is None:
            value = extract_value(lines, i, QLVL_RE)
            if value and value.isdigit():
                current["qlvl"] = int(value)
            continue

        if re.match(r"^TC\s*[：:]", line, re.I) and current.get("tc") is None:
            value = extract_value(lines, i, TC_RE)
            if value:
                current["tc"] = int(value) if value.isdigit() else value

    if not items:
        raise RuntimeError(f"No unique items parsed from {url}")
    return items


def source_is_fresh(payload):
    try:
        updated = datetime.fromisoformat(payload.get("updated_at", ""))
        if not updated.tzinfo:
            updated = updated.replace(tzinfo=timezone.utc)
        return now() - updated < timedelta(days=STALE_DAYS) and bool(payload.get("items"))
    except Exception:
        return False


def fetch_all(force=False):
    existing = load_json(SOURCE_PATH, {})
    if not force and source_is_fresh(existing):
        print(f"D2R World snapshot is fresh: {len(existing.get('items', []))} items")
        return existing

    all_items = []
    diagnostics = []
    for slug, category in CATEGORIES:
        try:
            rows = parse_category(slug, category)
            all_items.extend(rows)
            diagnostics.append({"slug": slug, "category": category, "items": len(rows), "ok": True})
            print(f"d2r.world {category}: {len(rows)}")
            # Be gentle with the text gateway; this full sync only runs monthly.
            time.sleep(0.45 + random.uniform(0.0, 0.35))
        except Exception as exc:
            diagnostics.append({"slug": slug, "category": category, "items": 0, "ok": False, "error": str(exc)})
            print(f"d2r.world {category}: ERROR {exc}")

    # Deduplicate across categories by canonical English name before validation.
    dedup = {}
    for item in all_items:
        dedup.setdefault(normalize(item["name_en"]), item)

    if len(dedup) < 250:
        # Never replace a healthy snapshot with a partial/blocked scrape.
        if existing.get("items"):
            print(f"Only parsed {len(dedup)} items; keeping existing snapshot with {len(existing['items'])}")
            return existing
        raise RuntimeError(f"D2R World scrape incomplete: only {len(dedup)} unique items")

    failed_categories = [x for x in diagnostics if not x.get("ok")]
    if failed_categories:
        if existing.get("items"):
            print(f"{len(failed_categories)} categories failed; keeping existing complete snapshot")
            return existing
        raise RuntimeError(f"D2R World category sync incomplete: {len(failed_categories)} categories failed")

    payload = {
        "updated_at": now().isoformat(),
        "source": BASE_URL,
        "category_count": len(CATEGORIES),
        "item_count": len(dedup),
        "categories": diagnostics,
        "items": list(dedup.values()),
    }
    save_json(SOURCE_PATH, payload)
    return payload


def merge_catalog(source):
    manual_cfg = load_json(MANUAL_PATH, {})
    manual_items = [dict(x) for x in manual_cfg.get("items", [])]

    # Existing hand-curated items win IDs/labels/categories because market history
    # already refers to those IDs and their JSP abbreviations are more specific.
    alias_index = {}
    for idx, item in enumerate(manual_items):
        candidates = list(item.get("aliases", [])) + [item.get("label", "")]
        for value in candidates:
            n = normalize(value)
            if n:
                alias_index.setdefault(n, idx)

    merged = manual_items
    added = 0
    merged_existing = 0
    for unique in source.get("items", []):
        en = unique["name_en"]
        zh = unique["name_zh"]
        old_zh = unique.get("old_name_zh")
        variants = alias_variants(en, zh, old_zh)
        match_idx = None
        for alias in variants:
            key = normalize(alias)
            if key in alias_index:
                match_idx = alias_index[key]
                break

        metadata = {
            "name_zh": zh,
            "name_en": en,
            "old_name_zh": old_zh,
            "category": unique.get("category"),
            "category_slug": unique.get("category_slug"),
            "qlvl": unique.get("qlvl"),
            "tc": unique.get("tc"),
            "source_url": unique.get("source_url"),
        }

        if match_idx is not None:
            item = merged[match_idx]
            aliases = list(item.get("aliases", []))
            for alias in variants:
                if alias.lower() not in {x.lower() for x in aliases}:
                    aliases.append(alias)
            item["aliases"] = aliases
            item["d2r_world"] = metadata
            merged_existing += 1
            continue

        item = {
            "id": "unique-" + slugify(en),
            "label": f"{zh} ({en})",
            "category": unique.get("category", "暗金裝備"),
            "aliases": variants,
            "d2r_world": metadata,
        }
        idx = len(merged)
        merged.append(item)
        for alias in variants:
            key = normalize(alias)
            if key:
                alias_index.setdefault(key, idx)
        added += 1

    payload = {
        "updated_at": now().isoformat(),
        "source": source.get("source"),
        "source_item_count": source.get("item_count", 0),
        "manual_item_count": len(manual_items),
        "merged_existing_count": merged_existing,
        "added_unique_count": added,
        "item_count": len(merged),
        "items": merged,
    }
    save_json(CATALOG_PATH, payload)
    print(
        f"catalog manual={len(manual_items)} source={source.get('item_count', 0)} "
        f"merged_existing={merged_existing} added={added} total={len(merged)}"
    )
    return payload


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="refresh D2R World even if snapshot is fresh")
    args = parser.parse_args()
    source = fetch_all(force=args.force)
    merge_catalog(source)


if __name__ == "__main__":
    main()
