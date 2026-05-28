import json, os
from datetime import date

STATE_FILE = os.path.join(os.path.dirname(__file__), "seen.json")


def load():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"seen": {}}


def save(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def check(state, url, price):
    """Returnerer (skal_notificere, aarsag)."""
    entry = state["seen"].get(url)
    if entry is None:
        return True, "ny"
    old = entry.get("price", price)
    if price < old * 0.95:
        return True, f"prisfald fra {int(old):,} kr".replace(",", ".")
    return False, None


def mark(state, url, price):
    state["seen"][url] = {"price": price, "date": str(date.today())}
