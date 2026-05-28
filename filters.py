"""Filtrerer produkter baseret paa config.json."""

import re
from datetime import datetime

CURRENT_YEAR = datetime.now().year

SIZE_PATTERNS = {
    "L":  re.compile(
        r"\bstr\.?\s*l\b|\bsize\s*l\b|\bl\s+unisex\b|\bunisex\s+str\.?\s*l\b"
        r"|\bstørrelse\s*l\b|\bmtb\s+l\b|\bl\s+mtb\b|\bl\s+29\b|\b29\s+l\b"
        r"|\bl\s+27\b|\bl[,/]xl\b",
        re.IGNORECASE,
    ),
    "XL": re.compile(
        r"\bstr\.?\s*xl\b|\bsize\s*xl\b|\bxl\s+unisex\b|\bunisex\s+str\.?\s*xl\b"
        r"|\bstørrelse\s*xl\b|\bmtb\s+xl\b|\bxl\s+mtb\b|\bxl\s+29\b"
        r"|\bl[,/]xl\b",
        re.IGNORECASE,
    ),
}

FS_KEYWORDS = [
    "fully", "full suspension", "full-suspension",
    "trail", "enduro", "stumpjumper", "fuel ex",
    "trance", "reign", "ripmo", "ripley",
    "santa cruz", "yeti", "pivot", "ibis mojo",
    "scott spark", "scott genius",
    "merida one-sixty", "merida ninety-six",
    "norco optic", "norco sight",
    "canyon spectral", "canyon neuron",
    "cube stereo", "commencal", "orbea occam", "orbea rallon",
    "rocky mountain", "transition sentinel",
    "specialized epic evo", "trek top fuel",
    "giant trance", "giant reign",
    "fuldaffjedret", "vollfederung", "tout suspendu",
]

HARDTAIL_EXCL = [
    "hardtail", "hard tail", " ht ", "xc race",
    "cross-country race", "hardtail mtb",
]

EMTB_WORDS = [
    "e-mtb", "e-bike", "ebike", "elcykel", "elektrisk",
    "bosch", "shimano steps", "bafang", "yamaha motor",
    " ep8", "cx drive", "tq-hpr", "fazua",
    # "e+" er tricky — Giant Trance X E+ er e-MTB
    "trance x e+", "reign e+", "e+ 1", "e+ 2", "e+ 3",
]

BUDGET_BRANDS = [
    "btwin", "rockrider", "nakamura", "yosemite", "sco ",
    "crosswave", "serious ", "whistle ", "voodoo",
    "raleigh wilder", "falcon",
]

NOT_A_BIKE = [
    "dæk", "tyre", "hjul", "wheel", "pedal", "sadel", "saddle",
    "styr", "handlebar", "gaffel", "fork", "kassette", "kæde", "chain",
    "bagskifter", "bremse", "brake", "skive", "rotor", "slange", "tube",
    "hjelm", "helmet", "trøje", "jersey", "bukser", "shorts",
    "sko", "shoe", "handske", "glove", "pumpe", "pump",
    "kit", "tubeless", "taske", "bag", "lås", "lock", "lampe",
    "computer", "rygstykke", "beskytter", "pad ",
]


def detect_size(title):
    for sz, pattern in SIZE_PATTERNS.items():
        if pattern.search(title):
            return sz
    return None


def is_full_suspension(title):
    t = title.lower()
    if any(k in t for k in HARDTAIL_EXCL):
        return False
    return any(k in t for k in FS_KEYWORDS)


def is_emtb(title):
    t = title.lower()
    return any(w in t for w in EMTB_WORDS)


def is_budget(title):
    t = title.lower()
    return any(w in t for w in BUDGET_BRANDS)


def is_accessory(title, price):
    t = title.lower()
    return any(w in t for w in NOT_A_BIKE) and price < 5000


def extract_year(title):
    m = re.findall(r"\b(20\d{2})\b", title)
    if m:
        return int(m[-1])
    m = re.findall(r"[''´`](\d{2})\b", title)
    if m:
        y = int(m[-1])
        if y <= CURRENT_YEAR % 100:
            return 2000 + y
    return None


def is_too_old(title, max_age):
    year = extract_year(title)
    if year is None:
        return False
    return (CURRENT_YEAR - year) > max_age


def apply(items, cfg):
    """Anvend alle filtre fra config og returnér (item, size) par."""
    f          = cfg["filters"]
    min_p      = f.get("min_price", 5000)
    max_p      = f.get("max_price", 30000)
    min_disc   = f.get("min_discount_pct", 10)
    sizes      = [s.upper() for s in f.get("sizes", ["L", "XL"])]
    incl_unkn  = f.get("notify_unknown_size", True)
    excl_emtb  = f.get("exclude_emtb", True)
    max_age    = f.get("max_age_years", 3)

    out = []
    for item in items:
        title = item.get("title", "")
        price = item.get("price", 0) or 0
        pct   = item.get("discount_pct", 0) or 0

        if not is_full_suspension(title):
            continue
        if is_accessory(title, price):
            continue
        if excl_emtb and is_emtb(title):
            continue
        if is_budget(title):
            continue
        if is_too_old(title, max_age):
            continue
        if price < min_p or price > max_p:
            continue
        if pct < min_disc:
            continue

        sz = detect_size(title)
        if sz not in sizes:
            if not (incl_unkn and sz is None):
                continue

        out.append({**item, "size": sz})

    return out
