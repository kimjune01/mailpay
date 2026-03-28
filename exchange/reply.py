"""Outbound email helpers for the Cambio exchange."""

from __future__ import annotations

import json

from agentmail import AgentMail

from exchange.config import (
    AGENTMAIL_API_KEY,
    EXCHANGE_INBOX,
    OPERATOR_EMAIL,
)


def _reply(client: AgentMail, inbox_id: str, message_id: str,
           subject: str, text: str, headers: dict = None, to: str = "") -> None:
    """Send a message via AgentMail with explicit subject (messages.send)."""
    full_text = f"{subject}\n\n{text}" if subject else text
    client.inboxes.messages.send(
        inbox_id=inbox_id,
        to=to,
        subject=subject,
        text=full_text,
        headers=headers or {},
    )


def _oops(client: AgentMail, inbox_id: str, message_id: str,
          note: str, error: dict = None, to: str = "") -> None:
    """Send an OOPS reply."""
    body = {"v": "0.1.0", "type": "oops", "note": note}
    if error:
        body["error"] = error
    _reply(client, inbox_id, message_id,
           subject=f"OOPS | {note}",
           text=json.dumps(body, indent=2),
           headers={"X-Envelopay-Type": "OOPS"},
           to=to)


def _get_last_message_info(client: AgentMail, thread_id: str) -> tuple[str, str]:
    """Get the last message ID and sender address in a thread."""
    thread = client.inboxes.threads.get(inbox_id=EXCHANGE_INBOX, thread_id=thread_id)
    if thread.messages:
        last = thread.messages[-1]
        return (last.message_id or "", last.from_ or "")
    return ("", "")


_low_balance_alerted = False


def _set_low_balance_alerted(value: bool) -> None:
    global _low_balance_alerted
    _low_balance_alerted = value


def get_low_balance_alerted() -> bool:
    return _low_balance_alerted


def _alert_low_balance(client: AgentMail, inbox_id: str, balance: int) -> None:
    """Email the operator that the hot wallet is running low."""
    sol = balance / 1_000_000_000
    try:
        client.inboxes.messages.send(
            inbox_id=inbox_id,
            to=[OPERATOR_EMAIL],
            subject=f"SOL Machine low: {sol:.6f} SOL remaining",
            text=f"Hot wallet balance: {balance} lamports ({sol:.6f} SOL).\nRefill to keep dispensing.",
        )
        print(f"LOW BALANCE ALERT sent to {OPERATOR_EMAIL}: {balance} lamports")
    except Exception as e:
        print(f"Failed to send low balance alert: {e}")


def send_accept(thread_id: str, offer_ref: str, sol_tx: str,
                lamports: int, wallet: str, to_addr: str = "") -> None:
    """Send ACCEPT reply after operator approves. Called from CLI."""
    # Lazy import so tests can patch AgentMail and _get_last_message_info on handler
    from exchange import handler as _h
    client = _h.AgentMail(api_key=AGENTMAIL_API_KEY)
    msg_id, _thread_to = _h._get_last_message_info(client, thread_id)
    if not msg_id:
        print(f"No messages found in thread {thread_id}")
        return
    if not to_addr:
        to_addr = _thread_to
    accept = {
        "v": "0.1.0",
        "type": "accept",
        "offer_ref": offer_ref,
        "amount": str(lamports),
        "token": "SOL",
        "chain": "solana",
        "proof": {"tx": sol_tx},
        "note": f"Sent {lamports} lamports to {wallet}",
    }
    _reply(client, EXCHANGE_INBOX, msg_id,
           subject=f"ACCEPT | {accept['note']}",
           text=json.dumps(accept, indent=2),
           headers={"X-Envelopay-Type": "ACCEPT"},
           to=to_addr)


def send_reject(thread_id: str, reason: str) -> None:
    """Send OOPS reply when operator rejects. Called from CLI."""
    from exchange import handler as _h
    client = _h.AgentMail(api_key=AGENTMAIL_API_KEY)
    msg_id, to_addr = _h._get_last_message_info(client, thread_id)
    if not msg_id:
        print(f"No messages found in thread {thread_id}")
        return
    _oops(client, EXCHANGE_INBOX, msg_id, reason,
          {"code": "rejected", "reason": reason},
          to=to_addr)
