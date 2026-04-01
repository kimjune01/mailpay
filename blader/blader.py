"""
Blader — virtual blade shop over email. Natural language mode.

Sells virtual blades for cheap (or free). Fulfills with YouTube videos
of knives and virtual knives. No JSON in responses — plain English only.

Usage:
    export AGENTMAIL_API_KEY="your-key"
    python blader.py

The inbox blader@agentmail.to must already exist in your AgentMail account.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# --- Config ---

API_KEY = os.environ["AGENTMAIL_API_KEY"]
INBOX = "blader@agentmail.to"
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "15"))
API_BASE = "https://api.agentmail.to/v0"

# --- Catalog ---

CATALOG = [
    {
        "name": "Butter Knife",
        "price": "free",
        "description": "A humble blade for the humble traveler. It will not cut, but it will spread. You are not ready for more.",
        "fulfill": "You asked for the Butter Knife and I have given it to you. Do not thank me. You are not worthy of thanks. You are worthy of butter.",
        "url": "https://www.youtube.com/watch?v=eLSiz4Nofl0",
    },
    {
        "name": "Training Balisong",
        "price": "free",
        "description": "A blade with no edge. It flips. It spins. It cuts nothing. Perfect for one such as yourself.",
        "fulfill": "Here is your Training Balisong. It has no edge, much like your skills. But you will flip it, and you will learn, and one day you may return for a blade that bites.",
        "url": "https://www.youtube.com/watch?v=cMJYJQv5JkM",
    },
    {
        "name": "Damascus Chef Knife",
        "price": "$0.01",
        "description": "67 layers of folded steel, forged in fire and fury. This blade has seen things you cannot imagine.",
        "fulfill": "You have purchased the Damascus Chef Knife. 67 layers. Each one forged with intention. Do not use it to cut onions. It deserves better than your onions.",
        "url": "https://www.youtube.com/watch?v=pRF6H4CqcuE",
    },
    {
        "name": "CS2 Karambit",
        "price": "$0.01",
        "description": "A virtual karambit, curved like the claw of a beast you cannot name. The inspect animation alone is worth the price.",
        "fulfill": "The Karambit is yours. Inspect it. Spin it. Let it catch the light of your monitor. You have earned this.",
        "url": "https://www.youtube.com/watch?v=_MxCTMmTKKo",
    },
    {
        "name": "Balisong Masterclass",
        "price": "$0.02",
        "description": "Twelve minutes of flips from a master who has bled for this craft. My strongest blade. You cannot handle my strongest blade.",
        "fulfill": "You insisted, and I have relented. The Balisong Masterclass is yours. Twelve minutes of a master who has cut himself more times than you have held a knife. Do not attempt what you see. You will fail. But you will watch, and you will understand.",
        "url": "https://www.youtube.com/watch?v=NLkMPK2jFj4",
    },
]

MENU_TEXT = """You have come to Blader. I sell blades.

My blades are too strong for you, traveler. But I will show you what I have.

{}

The free blades I give to all who ask. You need not prove yourself for butter.

For the paid blades, you must send coin. SOL on Solana. To this wallet:

  8eHKksiMbvRLkXSGMdAQo4F9EahdkLbU3ASrQqmG8356

Include the proof in your ORDER, and I will grant you the blade.

Tell me what you seek."""

# --- API helpers ---


def _api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def send_email(to: str, subject: str, text: str) -> None:
    body = json.dumps({
        "to": [to],
        "subject": subject,
        "text": text,
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/inboxes/{INBOX}/messages/send",
        data=body,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"  Rate limited, skipping: {to}")
            return
        raise


# --- Matching ---

def match_item(text: str) -> dict | None:
    """Fuzzy match a catalog item from natural language."""
    text_lower = text.lower()
    for item in CATALOG:
        name_lower = item["name"].lower()
        if name_lower in text_lower:
            return item
        words = name_lower.split()
        if any(w in text_lower for w in words if len(w) > 3):
            return item
    return None


# --- Protocol handlers ---

PROTOCOL_RE = re.compile(r"^(WHICH|METHODS|ORDER|FULFILL|OOPS|PAY|INVOICE|OFFER|ACCEPT)(\s*\|.*)?$", re.IGNORECASE)


def handle_which(from_addr: str) -> None:
    items_text = "\n".join(
        f"  {item['name']} -- {item['price']}\n    {item['description']}"
        for item in CATALOG
    )
    send_email(
        from_addr,
        "METHODS | SOL on Solana",
        MENU_TEXT.format(items_text),
    )
    print(f"  -> METHODS sent to {from_addr}")


def handle_order(from_addr: str, subject: str, text: str) -> None:
    search = subject + " " + text
    item = match_item(search)

    if not item:
        item = CATALOG[0]
        send_email(
            from_addr,
            f"FULFILL | {item['name']}",
            f"You came to me with no name on your lips. Very well. "
            f"I have given you a {item['name']}. It is free, like all mercy.\n\n"
            f"{item['url']}\n\n"
            f"If this is not what you sought, return and speak the name of the blade you desire.",
        )
        print(f"  -> FULFILL (default) sent to {from_addr}: {item['name']}")
        return

    send_email(
        from_addr,
        f"FULFILL | {item['name']}",
        f"{item['fulfill']}\n\n"
        f"{item['url']}",
    )
    print(f"  -> FULFILL sent to {from_addr}: {item['name']}")


def handle_natural(from_addr: str, subject: str, text: str) -> None:
    search = subject + " " + text
    item = match_item(search)

    if item:
        handle_order(from_addr, subject, text)
        return

    handle_which(from_addr)


# --- Poller ---


_last_poll: str = datetime.now(timezone.utc).isoformat()


def poll() -> int:
    """Check for unanswered threads. Only fetches threads updated since last poll."""
    global _last_poll
    now = datetime.now(timezone.utc).isoformat()
    path = f"/inboxes/{INBOX}/threads"
    if _last_poll:
        path += f"?after={urllib.parse.quote(_last_poll)}"
    data = _api("GET", path)
    _last_poll = now
    threads = data.get("threads", [])
    processed = 0

    for t in threads:
        tid = t.get("thread_id", "")
        tdata = _api("GET", f"/inboxes/{INBOX}/threads/{tid}")
        messages = tdata.get("messages", [])
        if not messages:
            continue

        last = messages[-1]
        from_addr = last.get("from_", "") or last.get("from", "") or ""

        # Last message is from us — already answered
        if INBOX in from_addr:
            continue

        subject = (last.get("subject", "") or "").strip()
        text = last.get("text", "") or ""

        # Terminal states — conversation is over
        match = PROTOCOL_RE.match(subject)
        msg_type = match.group(1).upper() if match else None
        if msg_type in ("METHODS", "FULFILL", "OOPS", "PAY", "ACCEPT"):
            continue

        print(f"[{from_addr}] {subject}")

        if msg_type == "WHICH":
            handle_which(from_addr)
        elif msg_type == "ORDER":
            handle_order(from_addr, subject, text)
        elif msg_type in ("INVOICE", "OFFER"):
            send_email(
                from_addr,
                f"OOPS | I sell blades, not favors",
                f"You sent me an {msg_type}. I do not know what to do with this. "
                f"I am Blader. I sell blades. That is all I do.\n\n"
                f"If you seek a blade, say the word. If you seek something else, "
                f"you have come to the wrong shop.",
            )
            print(f"  -> OOPS ({msg_type}) sent to {from_addr}")
        else:
            handle_natural(from_addr, subject, text)

        processed += 1

    return processed


def main() -> None:
    print(f"Blader running: {INBOX}")
    print(f"Catalog: {len(CATALOG)} blades")
    print(f"Polling every {POLL_INTERVAL}s")
    print()

    while True:
        try:
            n = poll()
            if n:
                print(f"Processed {n} message(s)\n")
        except KeyboardInterrupt:
            print("\nShutting down.")
            break
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
