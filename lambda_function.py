"""Lambda entry point. Polls inbox for new messages and processes them.

AgentMail API docs: https://docs.agentmail.to/api-reference/inboxes/messages/send
Webhook guide:      https://docs.agentmail.to/webhook-setup

Dedup strategy (defense in depth):

  1. Inbox (primary) — _is_from_exchange skips threads where axiomatic
     already replied. Requires replies to land in the original thread
     via thread_id in the send payload. If thread_id is missing, replies
     create new threads and the poller reprocesses the original forever.

  2. Ledger (OFFER only) — create_transaction deduplicates on message_id.
     Prevents duplicate pending transactions even if the poller calls
     process_email twice for the same OFFER.

  Layer 1 is the source of truth. Layer 2 is a fallback for the
  high-value path. Non-OFFER types (WHICH, PAY, ORDER) rely solely
  on layer 1. _reply() logs a warning when thread_id is absent so
  a layer-1 failure shows up in CloudWatch before it becomes a spam loop.
"""

from __future__ import annotations

import os
import re

from agentmail import AgentMail

AGENTMAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
EXCHANGE_INBOX = os.environ.get("EXCHANGE_INBOX", "axiomatic@agentmail.to")

# Protocol types that signal a thread is done (no further processing needed)
TERMINAL_TYPES = {"METHODS", "FULFILL", "OOPS", "PAY", "ACCEPT"}
PROTOCOL_RE = re.compile(r"^(WHICH|OFFER|PAY|ORDER|INVOICE|FULFILL|METHODS|ACCEPT|OOPS)\b", re.IGNORECASE)
RE_PREFIX = re.compile(r"^(Re:\s*)+", re.IGNORECASE)


def _api_get(path: str) -> dict:
    """Direct API call via urllib (bypasses httpx SDK issues in Lambda)."""
    import json
    import urllib.request
    url = f"https://api.agentmail.to/v0{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {AGENTMAIL_API_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _is_from_exchange(msg: dict) -> bool:
    """Check if a message was sent by the exchange inbox."""
    sender = msg.get("from", "") or msg.get("from_", "") or ""
    return EXCHANGE_INBOX in sender


def lambda_handler(event, context):
    """Poll inbox for unread messages and route to exchange handler."""
    from exchange.handler import process_email

    data = _api_get(f"/inboxes/{EXCHANGE_INBOX}/threads")
    threads = data.get("threads", [])

    processed = 0
    for t in threads:
        tid = t.get("thread_id", "")
        tdata = _api_get(f"/inboxes/{EXCHANGE_INBOX}/threads/{tid}")
        messages = tdata.get("messages", [])
        if not messages:
            continue

        # Skip threads where the exchange already replied
        if any(_is_from_exchange(m) for m in messages):
            continue

        last_msg = messages[-1]

        # Skip terminal protocol types — conversation is over
        subject = RE_PREFIX.sub("", (last_msg.get("subject", "") or "").strip()).strip()
        match = PROTOCOL_RE.match(subject)
        if match and match.group(1).upper() in TERMINAL_TYPES:
            continue

        sender = last_msg.get("from", "") or last_msg.get("from_", "") or ""

        payload = {
            "event_type": "message.received",
            "message": {
                "from_": sender,
                "subject": subject,
                "inbox_id": EXCHANGE_INBOX,
                "thread_id": tid,
                "message_id": last_msg.get("message_id", ""),
                "text": last_msg.get("text", ""),
                "id": last_msg.get("message_id", ""),
            },
        }

        print(f"Processing: {subject} from {sender}")
        try:
            process_email(payload)
        except Exception as e:
            # Stop entire poll on rate limit — no point retrying other messages
            if "429" in str(e) or "RateLimited" in type(e).__name__:
                print(f"Rate limited, stopping poll early: {e}")
                break
            print(f"Error processing message {last_msg.get('message_id')}: {e}")
            continue
        processed += 1

    print(f"Poll complete: {processed} messages processed")
    return {"statusCode": 200}
