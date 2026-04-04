"""Handlers for inbound protocol messages that axiomatic receives but didn't initiate.

INVOICE, FULFILL — require acknowledgment.
METHODS, ACCEPT — informational, log only.
"""

from __future__ import annotations

import json

from agentmail import AgentMail

from exchange.config import OPERATOR_EMAIL
from exchange.reply import _reply
from exchange.routes import _parse_json_from_text


def handle_invoice(client: AgentMail, inbox_id: str, reply_to_msg_id: str,
                   from_addr: str, text: str, thread_id: str = "") -> None:
    """Someone billed axiomatic. Log and acknowledge; operator decides whether to pay."""
    body = _parse_json_from_text(text)
    amount = body.get("amount", "?")
    token = body.get("token", "?")
    chain = body.get("chain", "?")
    wallet = body.get("wallet", "")
    note = body.get("note", "")
    invoice_id = body.get("id", "")

    print(f"INVOICE from {from_addr}: {amount} {token} on {chain} (wallet: {wallet})")

    # Forward to operator
    _reply(client, inbox_id, reply_to_msg_id,
           subject=f"INVOICE received | {amount} {token} from {from_addr}",
           text=f"Invoice from {from_addr}\n\n"
                f"Amount: {amount} {token} on {chain}\n"
                f"Wallet: {wallet}\n"
                f"Note: {note}\n"
                f"Invoice ID: {invoice_id}\n\n"
                f"Reply PAY to this thread to settle.",
           to=OPERATOR_EMAIL, thread_id=thread_id)


def handle_fulfill(client: AgentMail, inbox_id: str, reply_to_msg_id: str,
                   from_addr: str, text: str, thread_id: str = "") -> None:
    """Someone delivered work axiomatic ordered. Log and acknowledge."""
    body = _parse_json_from_text(text)
    order_ref = body.get("order_ref", "")
    result = body.get("result", {})
    summary = result.get("summary", "") if isinstance(result, dict) else str(result)
    note = body.get("note", summary)

    print(f"FULFILL from {from_addr}: order_ref={order_ref} — {note}")

    # Forward to operator
    _reply(client, inbox_id, reply_to_msg_id,
           subject=f"FULFILL received | {note or 'Work delivered'}",
           text=f"Fulfillment from {from_addr}\n\n"
                f"Order ref: {order_ref}\n"
                f"Summary: {summary}\n\n"
                f"Full body:\n{json.dumps(body, indent=2) if body else text}",
           to=OPERATOR_EMAIL, thread_id=thread_id)


def handle_methods(from_addr: str, text: str) -> None:
    """Informational response to a WHICH we sent. Log only."""
    body = _parse_json_from_text(text)
    rails = body.get("rails", [])
    print(f"METHODS from {from_addr}: {len(rails)} rails offered")


def handle_accept(from_addr: str, text: str) -> None:
    """Confirmation of an exchange. Log only."""
    body = _parse_json_from_text(text)
    offer_ref = body.get("offer_ref", "")
    proof = body.get("proof", {})
    tx = proof.get("tx", "") if isinstance(proof, dict) else ""
    print(f"ACCEPT from {from_addr}: offer_ref={offer_ref} tx={tx}")
