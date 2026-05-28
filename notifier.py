"""
Sender til Telegram.
Virker med bade private chats OG kanaler.

Private chat:  TELEGRAM_CHAT_ID = dit personlige ID (f.eks. 7757224922)
Kanal:         TELEGRAM_CHAT_ID = @kanalnavnet  ELLER  -100XXXXXXXXX
               (Botten skal vaere admin i kanalen med ret til at slaaa op)
"""

import os, requests

TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send(text: str):
    if not TOKEN or not CHAT_ID:
        print(f"[NOTIFIER] {text[:120]}")
        return

    resp = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": False},
        timeout=10,
    )
    if not resp.ok:
        raise RuntimeError(f"Telegram {resp.status_code}: {resp.text[:200]}")
