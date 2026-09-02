import re
import sync_d2r_world_sets as base

ITEM_RE = base.ITEM_RE
OLD_RE = base.OLD_RE
QLVL_RE = base.QLVL_RE
TC_RE = base.TC_RE

# D2R World root index is static. Store all set names explicitly so this one-time
# import does not depend on how the text gateway serializes navigation links.
SET_GROUPS = [
    ("北極裝備", "Arctic Gear"),
    ("海沙魯的鐵禦", "Hsarus' Defense"),
    ("狂戰士的武裝", "Berserker's Arsenal"),
    ("克雷德勞的防備", "Cleglaw's Brace"),
    ("煉獄器具", "Infernal Tools"),
    ("貝恩的衣裝", "Bane's Garments"),
    ("死亡的偽裝", "Death's Disguise"),
    ("西剛的全套鋼甲", "Sigon's Complete Steel"),
    ("依森哈特的軍械", "Isenhart's Armory"),
    ("克維雷布的法衣", "Civerb's Vestments"),
    ("卡珊的衣著", "Cathan's Traps"),
    ("天使的衣裝", "Angelic Raiment"),
    ("維達拉的配備", "Vidala's Rig"),
    ("牛王皮甲", "Cow King's Leathers"),
    ("阿卡娜的詭計", "Arcanna's Tricks"),
    ("山德的愚行", "Sander's Folly"),
    ("依雷撒的華服", "Iratha's Finery"),
    ("馬維娜之戰鬥詩歌", "M'avina's Battle Hymn"),
    ("娜塔亞的非難", "Natalya's Odium"),
    ("米拉伯佳戰裝", "Milabrega's Regalia"),
    ("塔拉夏的外袍", "Tal Rasha's Wrappings"),
    ("坦克雷的戰裝", "Tancred's Battlegear"),
    ("桓因的威嚴", "Hwanin's Majesty"),
    ("艾爾多的守衛", "Aldur's Watchtower"),
    ("塔格奧的化身", "Trang-Oul's Avatar"),
    ("沙薩比的崇高禮讚", "Sazabi's Grand Tribute"),
    ("不朽之王", "Immortal King"),
    ("門徒", "The Disciple"),
    ("赫拉森的輝煌", "Horazon's Splendor"),
    ("孤兒的呼喚", "Orphan's Call"),
    ("娜吉的上古遺物", "Naj's Ancient Vestige"),
    ("格里斯瓦德的傳奇", "Griswold's Legacy"),
    ("布爾凱索的子嗣", "Bul-Kathos' Children"),
    ("天堂的同胞", "Heaven's Brethren"),
]


def parse_category(slug, category):
    url = f"{base.BASE_URL}/{slug}"
    lines = base.lines_for(url)
    items = []
    current = None
    seen = set()

    # Each category URL already contains only that piece type. Parse item cards
    # directly instead of depending on a rendered heading such as "## 武器".
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
    return [
        {
            "slug": base.slugify(en),
            "name_zh": zh,
            "name_en": en,
            "source_url": base.BASE_URL,
        }
        for zh, en in SET_GROUPS
    ]


base.parse_category = parse_category
base.parse_set_groups = parse_set_groups
base.main()
