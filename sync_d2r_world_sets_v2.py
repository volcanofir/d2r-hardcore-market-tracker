import re
import sync_d2r_world_sets as base

ITEM_RE = base.ITEM_RE
OLD_RE = base.OLD_RE
QLVL_RE = base.QLVL_RE
TC_RE = base.TC_RE


def parse_category(slug, category):
    url = f"{base.BASE_URL}/{slug}"
    lines = base.lines_for(url)
    items = []
    current = None
    seen = set()

    # Category URLs already contain only that piece type. Do not depend on
    # the rendered section heading; Jina may render it as Markdown (## 武器).
    for i, line in enumerate(lines):
        m = ITEM_RE.match(line)
        if m:
            zh, en = (x.strip() for x in m.groups())
            if not base.looks_like_item(zh, en):
                continue
            key = base.normalize(en)
            if key in seen:
                current = next((x for x in items if base.normalize(x["name_en"]) == key), None)
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
            value = base.extract_value(lines, i, QLVL_RE)
            if value and value.isdigit():
                current["qlvl"] = int(value)
            continue
        if re.match(r"^TC\s*[：:]", line, re.I) and current.get("tc") is None:
            value = base.extract_value(lines, i, TC_RE)
            if value:
                current["tc"] = int(value) if value.isdigit() else value

    if not items:
        raise RuntimeError(f"No set items parsed from {url}")
    return items


def parse_set_groups():
    markdown = base.reader(base.BASE_URL)
    # Accept both absolute and relative links emitted by the text gateway.
    link_re = re.compile(
        r"\[([^\]]+?)\]\(((?:https://d2r\.world)?/zh-TW/info/item/sets/([a-z0-9_]+))\)",
        re.I,
    )
    groups = []
    seen = set()
    for text, href, slug in link_re.findall(markdown):
        if slug in base.NON_SET_SLUGS or slug in seen:
            continue
        seen.add(slug)
        display = re.sub(r"\s+", " ", text).strip()
        m = re.match(
            r"^(.*?)([A-Z][A-Za-z0-9'’\- ]+?)(?:\s*(?:亞馬遜|刺客|魔法使|德魯伊|死靈法師|野蠻人|術士|聖騎士))?$",
            display,
        )
        zh, en = display, display
        if m:
            zh, en = m.group(1).strip(), m.group(2).strip()
        url = href if href.startswith("http") else "https://d2r.world" + href
        groups.append({"slug": slug, "name_zh": zh, "name_en": en, "source_url": url})
    if len(groups) < 30:
        raise RuntimeError(f"Set group discovery incomplete: {len(groups)}")
    return groups


base.parse_category = parse_category
base.parse_set_groups = parse_set_groups
base.main()
