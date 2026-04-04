"""Cambio exchange entry point. Routes emails by type; delegates to submodules."""

from __future__ import annotations

import json

from agentmail import AgentMail

from exchange.config import AGENTMAIL_API_KEY, EXCHANGE_INBOX, KNOWN_TYPES, WEBHOOK_SECRET
from exchange.db import get_ban
from exchange.rate import get_sol_usd_rate  # noqa: F401 — re-export for test patching
from exchange.reply import _get_last_message_info, _oops, _reply, send_accept, send_reject  # noqa: F401
from exchange.routes import (PROTOCOL_RE, RE_PREFIX, handle_banned, handle_offer, handle_pay,
    handle_payment_notification, handle_reversal, handle_which, is_payment_notification)
from exchange.inbound import handle_accept, handle_fulfill, handle_invoice, handle_methods
from exchange.shop import handle_order
from exchange.settle import send_sol  # noqa: F401 — re-export for test patching

DB_PATH = "unused"

def process_email(payload: dict, db_path: str = DB_PATH) -> None:
    """Process an incoming email from the webhook."""
    client = AgentMail(api_key=AGENTMAIL_API_KEY, timeout=15)
    msg = payload.get("message", {})
    from_addr = msg.get("from_", "") or msg.get("from", "")
    subject = msg.get("subject", "")
    inbox_id = msg.get("inbox_id", EXCHANGE_INBOX)
    thread_id = msg.get("thread_id", "")
    reply_to = msg.get("message_id", "") or msg.get("id", "")
    text = msg.get("text", "") or ""
    message_id = msg.get("id", "") or payload.get("message_id", "")

    if EXCHANGE_INBOX in from_addr:
        return

    ban_row = get_ban(db_path, from_addr)
    if ban_row and handle_banned(client, inbox_id, reply_to, from_addr, subject, text, db_path, ban_row, msg, thread_id):
        return

    stripped = RE_PREFIX.sub("", subject.strip()).strip()
    match = PROTOCOL_RE.match(stripped)
    msg_type = match.group(1) if match else None

    if msg_type and msg_type not in KNOWN_TYPES:
        _oops(client, inbox_id, reply_to, f"Unknown type: {msg_type}", {"code": "unknown_type",
              "sent": msg_type, "supported": sorted(KNOWN_TYPES),
              "spec": "https://june.kim/envelopay-spec.md"}, to=from_addr, thread_id=thread_id)
        return
    if msg_type == "WHICH" or stripped.upper() == "WHICH":
        handle_which(client, inbox_id, reply_to, from_addr, text, db_path, thread_id)
        return
    if msg_type == "OFFER":
        handle_offer(client, inbox_id, reply_to, from_addr, text, db_path, message_id, thread_id, from_addr)
        return
    if msg_type == "PAY":
        handle_pay(client, inbox_id, reply_to, from_addr, text, db_path, message_id, thread_id)
        return
    if msg_type == "ORDER":
        handle_order(client, inbox_id, reply_to, from_addr, text, subject, thread_id)
        return
    if msg_type == "INVOICE":
        handle_invoice(client, inbox_id, reply_to, from_addr, text, thread_id)
        return
    if msg_type == "FULFILL":
        handle_fulfill(client, inbox_id, reply_to, from_addr, text, thread_id)
        return
    if msg_type == "METHODS":
        handle_methods(from_addr, text)
        return
    if msg_type == "ACCEPT":
        handle_accept(from_addr, text)
        return
    if msg_type == "OOPS":
        print(f"OOPS from {from_addr}: {stripped}")
        return

    is_payment, is_reversal = is_payment_notification(subject, text)
    if is_payment and not is_reversal:
        handle_payment_notification(client, inbox_id, from_addr, subject, text, db_path)
    elif is_reversal:
        handle_reversal(from_addr, subject, db_path)

def _check_webhook_secret(headers: dict) -> bool:
    if not WEBHOOK_SECRET:
        return True
    return any(k.lower() == "x-webhook-secret" and v == WEBHOOK_SECRET for k, v in headers.items())


def lambda_handler(event, context):
    """AWS Lambda entry point."""
    if not _check_webhook_secret(event.get("headers", {})):
        return {"statusCode": 401, "body": "Unauthorized"}
    body = json.loads(event.get("body", "{}"))
    if body.get("event_type") == "message.received":
        process_email(body)
    return {"statusCode": 200}
