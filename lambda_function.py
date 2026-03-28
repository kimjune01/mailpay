"""Lambda entry point. Polls inbox for new messages and processes them."""

from __future__ import annotations

import os

from agentmail import AgentMail

AGENTMAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
EXCHANGE_INBOX = os.environ.get("EXCHANGE_INBOX", "axiomatic@agentmail.to")


def lambda_handler(event, context):
    """Poll inbox for unread messages and route to exchange handler."""
    from exchange.handler import process_email

    client = AgentMail(api_key=AGENTMAIL_API_KEY)
    threads = client.inboxes.threads.list(inbox_id=EXCHANGE_INBOX)

    processed = 0
    for t in threads.threads:
        thread = client.inboxes.threads.get(
            inbox_id=EXCHANGE_INBOX, thread_id=t.thread_id
        )
        if not thread.messages:
            continue

        # Skip threads where the last message is from us (we already replied to the latest).
        # If the last message is from someone else, process it even if we replied earlier.
        last_msg = thread.messages[-1]
        if EXCHANGE_INBOX in (last_msg.from_ or ""):
            continue

        # Get the latest inbound message
        msg = thread.messages[-1]

        # Build payload matching webhook format
        payload = {
            "event_type": "message.received",
            "message": {
                "from_": msg.from_ or "",
                "subject": msg.subject or "",
                "inbox_id": EXCHANGE_INBOX,
                "thread_id": t.thread_id,
                "message_id": msg.message_id or "",
                "text": msg.text or "",
                "id": msg.message_id or "",
            },
        }

        print(f"Processing: {msg.subject} from {msg.from_}")
        try:
            process_email(payload)
        except Exception as e:
            print(f"Error processing message {msg.message_id}: {e}")
            continue
        processed += 1

    print(f"Poll complete: {processed} messages processed")
    return {"statusCode": 200}
