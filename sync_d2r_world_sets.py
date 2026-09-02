import json
import random
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
CATALOG_PATH = DATA / "catalog.json"
SETS_PATH = DATA / "d2r_world_sets.json"
BASE_URL = "https://d2r.world/zh-TW/info/item/sets"
JINA_PREFIX = "https://r.jina.ai/https://"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

CATEGORIES = [
    ("weapons", "套裝武器"),
    ("helms", "套裝頭盔"),
    ("armors", "套裝護甲"),
    ("shields", "套裝盾牌"),
    ("belts", "套裝腰帶"),
    ("boots", "套裝鞋子"),
    ("gloves", "套裝手套"),
    ("rings", "套裝戒指"),
    ("amulets", "套裝護身符"),
]

ITEM_RE = re.compile(r"^(.{1,100}?)\s*\(([^()]{2,100})\)$")
OLD_RE = re.compile(r"^舊名[：:]\s*(.+)$")
QLVL_RE = re.compile(r"Qlvl\s*[：:]\s*(\d+)", re.I)
TC_RE = re.compile(r"^TC\s*[：:]\s*([0-9]+|-)\s*$", re.I)
SET_LINK_RE = re.compile(r"\[([^\]]+?)\]\((https://d2r\.world/zh-TW/info/item/sets/([a-z0-9_]+))\)", re.I)

CATEGORY_SLUGS = {slug for slug, _ in CATEGORIES}
NON_SET_SLUGS = CATEGORY_SLUGS | {"sets"}


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize(text):
    text = unicodedata.normalize("NFKC", str(text or "")).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text):
    value = normalize(text)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "set-item"


def clean_markdown_line(raw):
    line = str(raw or "").strip()
    line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"^[\s#>*-]+", "", line)
    line = line.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", line).strip()


def reader(url, retries=6):
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
            if len(response.text) < 500:
                raise RuntimeError(f"reader returned only {len(response.text)} bytes")
            return response.text
        except Exception as exc:
            last_error = str(exc)
            if attempt < retries - 1:
                time.sleep(min(20, 2 * (attempt + 1)) + random.uniform(0.2, 0.8))
    raise RuntimeError(last_error or "reader failed")


def lines_for(url):
    return [x for x in (clean_markdown_line(row) for row in reader(url).splitlines()) if x]


def looks_like_item(zh, en):
    if zh in {"搜尋", "Search"} or len(en.strip()) < 3:
        return False
    if not re.search(r"[A-Za-z]", en):
        return False
    banned = {"search", "qlvl", "tc", "privacy policy", "terms of service", "normal", "exceptional", "elite"}
    return normalize(en) not in banned


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


def parse_category(slug, category):
    url = f"{BASE_URL}/{slug}"
    lines = lines_for(url)
    items = []
    current = None
    seen = set()
    section_started = False

    for i, line in enumerate(lines):
        if line == category.replace("套裝", "") or line == {"套裝武器":"武器","套裝頭盔":"頭盔","套裝護甲":"護甲","套裝盾牌":"盾牌","套裝腰帶":"腰帶","套裝鞋子":"鞋子","套裝手套":"手套","套裝戒指":"戒指","套裝護身符":"護身符"}[category]:
            section_started = True
            continue
        if not section_started:
            continue

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
        raise RuntimeError(f"No set items parsed from {url}")
    return items


def parse_set_groups():
    markdown = reader(BASE_URL)
    groups = []
    seen = set()
    for text, url, slug in SET_LINK_RE.findall(markdown):
        if slug in NON_SET_SLUGS or slug in seen:
            continue
        seen.add(slug)
        display = re.sub(r"\s+", " ", text).strip()
        # Root links render as Chinese then English (and sometimes a class suffix).
        # Split at the first ASCII capital token.
        m = re.match(r"^(.*?)([A-Z][A-Za-z0-9'’\- ]+?)(?:\s*(?:亞馬遜|刺客|魔法使|德魯伊|死靈法師|野蠻人|術士|聖騎士))?$", display)
        zh = display
        en = display
        if m:
            zh = m.group(1).strip()
            en = m.group(2).strip()
        groups.append({
            "slug": slug,
            "name_zh": zh,
            "name_en": en,
            "source_url": url,
        })
    if len(groups) < 30:
        raise RuntimeError(f"Set group discovery incomplete: {len(groups)}")
    return groups


def aliases_for(en, zh=None, old_zh=None):
    values = []
    def add(value):
        value = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(value) >= 2 and value.lower() not in {x.lower() for x in values}:
            values.append(value)
    add(en)
    add(en.replace("’", "'"))
    add(en.replace("'", ""))
    add(en.replace("-", " "))
    add(zh)
    add(old_zh)
    return values


def merge_into_catalog(source):
    catalog = load_json(CATALOG_PATH, {"items": []})
    items = [dict(x) for x in catalog.get("items", [])]
    alias_index = {}
    for idx, item in enumerate(items):
        for value in list(item.get("aliases", [])) + [item.get("label", "")]:
            key = normalize(value)
            if key:
                alias_index.setdefault(key, idx)

    merged_existing = 0
    added = 0

    def merge_item(new_item, aliases):
        nonlocal merged_existing, added
        match_idx = None
        for alias in aliases:
            key = normalize(alias)
            if key in alias_index:
                match_idx = alias_index[key]
                break
        if match_idx is not None:
            existing = items[match_idx]
            current_aliases = list(existing.get("aliases", []))
            for alias in aliases:
                if alias.lower() not in {x.lower() for x in current_aliases}:
                    current_aliases.append(alias)
            existing["aliases"] = current_aliases
            if new_item.get("d2r_world_set"):
                existing["d2r_world_set"] = new_item["d2r_world_set"]
            if new_item.get("d2r_world_set_group"):
                existing["d2r_world_set_group"] = new_item["d2r_world_set_group"]
            merged_existing += 1
            return
        idx = len(items)
        items.append(new_item)
        for alias in aliases:
            key = normalize(alias)
            if key:
                alias_index.setdefault(key, idx)
        added += 1

    for row in source.get("items", []):
        aliases = aliases_for(row["name_en"], row["name_zh"], row.get("old_name_zh"))
        merge_item({
            "id": "set-" + slugify(row["name_en"]),
            "label": f"{row['name_zh']} ({row['name_en']})",
            "category": row["category"],
            "aliases": aliases,
            "d2r_world_set": row,
        }, aliases)

    for row in source.get("sets", []):
        aliases = aliases_for(row["name_en"], row["name_zh"])
        merge_item({
            "id": "set-group-" + slugify(row["name_en"]),
            "label": f"{row['name_zh']} ({row['name_en']})",
            "category": "完整套裝",
            "aliases": aliases,
            "d2r_world_set_group": row,
        }, aliases)

    catalog.update({
        "updated_at": now_iso(),
        "set_source": BASE_URL,
        "set_piece_count": source.get("item_count", 0),
        "set_group_count": source.get("set_count", 0),
        "set_merged_existing_count": merged_existing,
        "set_added_count": added,
        "item_count": len(items),
        "items": items,
    })
    save_json(CATALOG_PATH, catalog)
    print(f"catalog +sets pieces={source.get('item_count', 0)} groups={source.get('set_count', 0)} merged={merged_existing} added={added} total={len(items)}")


def main():
    category_results = []
    all_items = []
    for slug, category in CATEGORIES:
        rows = parse_category(slug, category)
        all_items.extend(rows)
        category_results.append({"slug": slug, "category": category, "items": len(rows), "ok": True})
        print(f"d2r.world sets {category}: {len(rows)}")
        time.sleep(0.45 + random.uniform(0.0, 0.35))

    dedup = {}
    for row in all_items:
        dedup.setdefault(normalize(row["name_en"]), row)
    if len(dedup) < 100:
        raise RuntimeError(f"D2R World set piece scrape incomplete: {len(dedup)}")

    groups = parse_set_groups()
    payload = {
        "schema": 1,
        "updated_at": now_iso(),
        "source": BASE_URL,
        "category_count": len(CATEGORIES),
        "item_count": len(dedup),
        "set_count": len(groups),
        "categories": category_results,
        "sets": groups,
        "items": list(dedup.values()),
    }
    save_json(SETS_PATH, payload)
    merge_into_catalog(payload)


if __name__ == "__main__":
    main()
