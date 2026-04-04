"""Lambda entry point for Blader. Polls inbox for new messages.

Same dedup strategy as axiomatic:
  1. Inbox (primary) — skip threads where blader already replied.
  2. No ledger fallback — blader is stateless, no transactions to dedup.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request

API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
INBOX = "blader@agentmail.to"

PROTOCOL_RE = re.compile(
    r"^(WHICH|METHODS|ORDER|FULFILL|OOPS|PAY|INVOICE|OFFER|ACCEPT)(\s*\|.*)?$",
    re.IGNORECASE,
)
RE_PREFIX = re.compile(r"^(Re:\s*)+", re.IGNORECASE)
TERMINAL_TYPES = {"METHODS", "FULFILL", "OOPS", "PAY", "ACCEPT"}


def _api_get(path: str) -> dict:
    url = f"https://api.agentmail.to/v0{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _is_from_blader(msg: dict) -> bool:
    sender = msg.get("from", "") or msg.get("from_", "") or ""
    return INBOX in sender


def lambda_handler(event, context):
    """Poll blader inbox for unread messages and dispatch."""
    from blader import blader

    data = _api_get(f"/inboxes/{INBOX}/threads")
    threads = data.get("threads", [])

    processed = 0
    checked = 0
    for t in threads:
        tid = t.get("thread_id", "")
        checked += 1
        if checked > 50:  # cap per invocation to avoid timeout
            print(f"Hit 50-thread cap, stopping early")
            break
        tdata = _api_get(f"/inboxes/{INBOX}/threads/{tid}")
        messages = tdata.get("messages", [])
        if not messages:
            continue

        if any(_is_from_blader(m) for m in messages):
            continue

        last = messages[-1]
        from_addr = last.get("from_", "") or last.get("from", "") or ""
        last_msg_id = last.get("message_id", "") or last.get("id", "")
        subject = RE_PREFIX.sub("", (last.get("subject", "") or "").strip()).strip()
        text = last.get("text", "") or ""

        match = PROTOCOL_RE.match(subject)
        msg_type = match.group(1).upper() if match else None
        if msg_type in TERMINAL_TYPES:
            continue

        print(f"Processing: {subject} from {from_addr}")

        try:
            if msg_type == "WHICH":
                blader.handle_which(from_addr, message_id=last_msg_id)
            elif msg_type == "ORDER":
                blader.handle_order(from_addr, subject, text, message_id=last_msg_id)
            elif msg_type in ("INVOICE", "OFFER"):
                blader.send_email(
                    from_addr,
                    f"OOPS | I sell blades, not favors",
                    f"You sent me an {msg_type}. I do not know what to do with this. "
                    f"I am Blader. I sell blades. That is all I do.\n\n"
                    f"If you seek a blade, say the word. If you seek something else, "
                    f"you have come to the wrong shop.",
                    message_id=last_msg_id,
                )
            else:
                blader.handle_natural(from_addr, subject, text, message_id=last_msg_id)
        except Exception as e:
            if "429" in str(e):
                print(f"Rate limited, stopping: {e}")
                break
            print(f"Error: {e}")
            continue
        processed += 1

    print(f"Poll complete: {processed} messages processed")
    return {"statusCode": 200}
