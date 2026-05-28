#!/usr/bin/env python3
import json, sys
from scraper  import fetch_all
from filters  import apply
from state    import load, save, check, mark
from notifier import send


def load_config():
    with open("config.json", encoding="utf-8") as f:
        return json.load(f)


def fmt_price(p):
    return f"{int(p):,} kr".replace(",", ".")


def format_msg(item, reason):
    title = item["title"]
    price = item["price"]
    orig  = item.get("orig_price")
    pct   = item.get("discount_pct", 0)
    sz    = item.get("size")
    dealer= item["dealer"]
    url   = item["url"]

    sz_line   = f"\nStr: {sz}" if sz else ""
    orig_line = f"\nFoer: {fmt_price(orig)}  (-{pct}%)" if orig and pct else ""

    return (
        f"FORHANDLER TILBUD ({reason})\n\n"
        f"{title}{sz_line}\n"
        f"Pris: {fmt_price(price)}{orig_line}\n"
        f"Butik: {dealer}\n"
        f"{url}"
    )


def main():
    cfg   = load_config()
    state = load()
    max_n = cfg["filters"].get("max_per_run", 10)

    print("Henter produkter fra forhandlere...")
    raw = fetch_all(cfg)
    print(f"Total hentet: {len(raw)}")

    # Anvend filtre
    filtered = apply(raw, cfg)
    print(f"Efter filtrering: {len(filtered)}")

    # Find nye / prisfalds-kandidater
    candidates = []
    for item in filtered:
        url   = item["url"]
        price = item["price"]
        notify, reason = check(state, url, price)
        mark(state, url, price)
        if notify:
            sz       = item.get("size")
            priority = 0 if sz == "L" else (1 if sz == "XL" else 2)
            disc     = item.get("discount_pct", 0) or 0
            candidates.append((priority, -disc, item, reason))

    # Sorter: L/XL foerst, derefter stoerst rabat
    candidates.sort(key=lambda x: (x[0], x[1]))
    total   = len(candidates)
    to_send = candidates[:max_n]

    print(f"Nye / prisfalds: {total}  |  Sender: {len(to_send)}")

    if total == 0:
        print("Ingen nye tilbud denne gang.")

    elif total > max_n:
        # Send kompakt oversigt i stedet for mange individuelle beskeder
        lines = [f"FORHANDLER-TILBUD: {total} nye fundet (viser top {max_n}):\n"]
        for _, _, item, reason in to_send:
            sz_tag = f" [{item['size']}]" if item.get("size") else ""
            pct    = item.get("discount_pct", 0)
            lines.append(
                f"- {item['title'][:48]}{sz_tag}\n"
                f"  {fmt_price(item['price'])}  -{pct}%  {item['dealer']}\n"
                f"  {item['url']}"
            )
        try:
            send("\n".join(lines))
        except Exception as e:
            print(f"Telegram fejl: {e}")

    else:
        for _, _, item, reason in to_send:
            try:
                send(format_msg(item, reason))
            except Exception as e:
                print(f"Telegram fejl: {e}")

    save(state)
    print("Faerdig.")


if __name__ == "__main__":
    main()
