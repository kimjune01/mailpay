"""
Envelopay shop — sell digital goods over email.

Usage:
    1. Get a free inbox at agentmail.to
    2. Set your env vars (see below)
    3. python shop.py

Env vars:
    AGENTMAIL_API_KEY  — your AgentMail API key
    SHOP_INBOX         — your inbox address (e.g. myshop@agentmail.to)
    SOL_WALLET         — your Solana wallet address (where you receive payment)

No dependencies beyond Python 3.9+ stdlib.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request

# --- Config ---

API_KEY = os.environ["AGENTMAIL_API_KEY"]
SHOP_INBOX = os.environ["SHOP_INBOX"]
SOL_WALLET = os.environ["SOL_WALLET"]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))

API_BASE = "https://api.agentmail.to/v0"
PROTOCOL_RE = re.compile(r"^([A-Za-z]+)(\s*\|.*)?$")

# --- Catalog ---
# Edit this dict to list your products.
# Keys are slugs, used for matching. file_url is what gets sent on FULFILL.

CATALOG = {
    "example-template": {
        "name": "Example Template",
        "price_sol": 0.1,
        "file_url": "https://example.com/download/example-template.zip",
    },
    # Add more items here:
    # "react-ui-kit": {
    #     "name": "React UI Kit",
    #     "price_sol": 0.5,
    #     "file_url": "https://yoursite.com/download/react-ui-kit.zip",
    # },
}

# --- API helpers ---


def _api(method: str, path: str, body: dict = None) -> dict:
    """Make an AgentMail API call."""
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
    """Send an email from the shop inbox."""
    _api("POST", f"/inboxes/{SHOP_INBOX}/messages", {
        "to": [to],
        "subject": subject,
        "text": text,
    })


# --- Protocol handlers ---


def handle_which(from_addr: str) -> None:
    """Reply with METHODS — what we sell and how we accept payment."""
    items = "\n".join(
        f"  - {item['name']}: {item['price_sol']} SOL"
        for item in CATALOG.values()
    )
    rails = [{"chain": "solana", "token": "SOL", "wallet": SOL_WALLET}]
    body = {
        "v": "0.1.0",
        "type": "methods",
        "note": f"Available items:\n{items}",
        "rails": rails,
    }
    send_email(
        from_addr,
        f"METHODS | Solana, SOL",
        json.dumps(body, indent=2),
    )
    print(f"  -> METHODS sent to {from_addr}")


def handle_order(from_addr: str, subject: str, text: str) -> None:
    """Fulfill any ORDER with a download link."""
    # Extract item name from subject
    name = "Digital Product"
    if "|" in subject:
        name = subject.split("|", 1)[1].strip()
        if "," in name:
            name = name.rsplit(",", 1)[0].strip()

    # Match catalog
    slug = name.lower().replace(" ", "-")
    item = CATALOG.get(slug)
    if not item:
        oops = {
            "v": "0.1.0",
            "type": "oops",
            "note": f"Unknown product: {name}",
            "error": {"code": "item_not_found", "available": list(CATALOG.keys())},
        }
        send_email(from_addr, f"OOPS | Unknown product: {name}", json.dumps(oops, indent=2))
        print(f"  -> OOPS unknown product: {name}")
        return

    # Parse body for order ref
    try:
        body = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        body = {}

    fulfill = {
        "v": "0.1.0",
        "type": "fulfill",
        "order_ref": body.get("id", ""),
        "result": {"summary": f"Delivered: {item['name']}", "download": item["file_url"]},
        "note": f"Here's your {item['name']}.",
    }
    send_email(
        from_addr,
        f"FULFILL | {item['name']}",
        json.dumps(fulfill, indent=2),
    )
    print(f"  -> FULFILL sent to {from_addr}: {item['name']}")


def handle_unknown(from_addr: str, msg_type: str) -> None:
    """Reply OOPS for unsupported message types."""
    body = {
        "v": "0.1.0",
        "type": "oops",
        "note": f"This shop handles WHICH and ORDER. You sent {msg_type}.",
        "error": {"code": "unsupported_flow", "supported": ["WHICH", "ORDER"]},
    }
    send_email(
        from_addr,
        f"OOPS | Unsupported: {msg_type}",
        json.dumps(body, indent=2),
    )


# --- Poller ---


def poll() -> int:
    """Check inbox for new messages and process them. Returns count processed."""
    data = _api("GET", f"/inboxes/{SHOP_INBOX}/threads")
    threads = data.get("threads", [])
    processed = 0

    for t in threads:
        tid = t.get("thread_id", "")
        tdata = _api("GET", f"/inboxes/{SHOP_INBOX}/threads/{tid}")
        messages = tdata.get("messages", [])
        if not messages:
            continue

        last = messages[-1]
        from_addr = last.get("from_", "") or ""

        # Skip our own messages
        if SHOP_INBOX in from_addr:
            continue

        subject = (last.get("subject", "") or "").strip()
        text = last.get("text", "") or ""
        match = PROTOCOL_RE.match(subject)
        msg_type = match.group(1) if match else None

        if not msg_type:
            continue

        print(f"Processing: {subject} from {from_addr}")

        msg_type = msg_type.upper()

        if msg_type == "WHICH":
            handle_which(from_addr)
        elif msg_type == "ORDER":
            handle_order(from_addr, subject, text)
        else:
            handle_unknown(from_addr, msg_type)

        processed += 1

    return processed


def main() -> None:
    print(f"Shop running: {SHOP_INBOX}")
    print(f"Wallet: {SOL_WALLET}")
    print(f"Catalog: {len(CATALOG)} item(s)")
    print(f"Polling every {POLL_INTERVAL}s")
    print()

    while True:
        try:
            n = poll()
            if n:
                print(f"Processed {n} message(s)")
        except KeyboardInterrupt:
            print("\nShutting down.")
            break
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
