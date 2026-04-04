"""Type handlers for the Cambio exchange protocol."""

from __future__ import annotations

import json
import logging
import re

from agentmail import AgentMail

from exchange.config import (
    CASHAPP_HANDLE,
    MAX_FIAT_CENTS,
    MIN_FIAT_CENTS,
    SOL_WALLET,
    SPREAD,
    VENMO_HANDLE,
)
from exchange.db import (
    _hash_pii,
    ban_email,
    get_most_recent_approved,
    unban_email,
)
from exchange.rate import apply_spread
from exchange.reply import _oops, _reply

PROTOCOL_RE = re.compile(r"^([A-Z]+)(\s*\|.*)?$")
RE_PREFIX = re.compile(r"^(Re:\s*)+", re.IGNORECASE)
AMOUNT_RE = re.compile(r"\$(\d+\.\d{2})")

logger = logging.getLogger(__name__)


def _parse_json_from_text(text: str) -> dict:
    """Try to parse JSON from a text body."""
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    return {}


def handle_which(client: AgentMail, inbox_id: str, reply_to_msg_id: str,
                 from_addr: str, text: str, db_path: str,
                 thread_id: str = "") -> None:
    """Reply METHODS with CashApp/Venmo rails and live SOL rate."""
    # Import from handler so tests can patch xh.get_sol_usd_rate
    from exchange import handler as _h
    try:
        raw_rate = _h.get_sol_usd_rate()
    except Exception:
        _oops(client, inbox_id, reply_to_msg_id,
              "Rate unavailable, try again later",
              {"code": "rate_unavailable"},
              to=from_addr, thread_id=thread_id)
        return

    spread_rate = apply_spread(raw_rate, SPREAD)

    terms = {
        "v": "0.1.0",
        "type": "methods",
        "note": f"SOL for USD. ${MIN_FIAT_CENTS/100:.0f}-${MAX_FIAT_CENTS/100:.0f} range. "
                f"Rate: ${spread_rate:.2f}/SOL (market ${raw_rate:.2f} + {SPREAD*100:.0f}% spread)",
        "rails": [
            {"chain": "cashapp", "token": "USD",
             "wallet": CASHAPP_HANDLE,
             "url": f"https://cash.app/{CASHAPP_HANDLE}",
             "price": str(int(spread_rate * 100))},
            {"chain": "venmo", "token": "USD",
             "wallet": VENMO_HANDLE,
             "url": f"https://venmo.com/u/{VENMO_HANDLE.lstrip('@')}",
             "price": str(int(spread_rate * 100))},
            {"chain": "solana", "token": "SOL", "wallet": SOL_WALLET},
        ],
        "min_cents": MIN_FIAT_CENTS,
        "max_cents": MAX_FIAT_CENTS,
        "raw_rate": raw_rate,
        "spread_rate": spread_rate,
    }
    note = terms["note"]
    _reply(client, inbox_id, reply_to_msg_id,
           subject=f"METHODS | {note}",
           text=json.dumps(terms, indent=2),
           headers={"X-Envelopay-Type": "METHODS"},
           to=from_addr, thread_id=thread_id)


def handle_banned(client, inbox_id, reply_to_msg_id, from_addr, subject, text, db_path, ban_row, message, thread_id="") -> bool:
    """Handle a banned user's message. Returns True if handled (caller should return)."""
    stripped_check = subject.strip()
    if PROTOCOL_RE.match(stripped_check) and PROTOCOL_RE.match(stripped_check).group(1) == "PAY":
        pay_body = _parse_json_from_text(text)
        pay_give = pay_body.get("give", {})
        pay_amount_cents = 0
        if isinstance(pay_give, dict):
            try:
                pay_amount_cents = int(pay_give.get("amount", 0))
            except (ValueError, TypeError):
                pay_amount_cents = 0
        if not pay_amount_cents:
            try:
                pay_amount_cents = int(pay_body.get("amount", 0))
            except (ValueError, TypeError):
                pay_amount_cents = 0

        owed = ban_row["amount_owed_cents"]
        reply_id = message.get("message_id", "") or message.get("id", "")
        if pay_amount_cents >= owed:
            unban_email(db_path, from_addr)
            print(f"UNBANNED {from_addr} — sent PAY, debt settled")
            _reply(client, inbox_id, reply_id,
                   subject="OOPS | Debt settled, you're back",
                   text=json.dumps({"v": "0.1.0", "type": "oops",
                                    "note": "Debt settled. You're unbanned. Don't do it again.",
                                    "error": {"code": "unbanned"}}, indent=2),
                   headers={"X-Envelopay-Type": "OOPS"},
                   to=from_addr, thread_id=thread_id)
            return True
        else:
            _oops(client, inbox_id, reply_id,
                  f"You owe ${owed/100:.2f}, you sent ${pay_amount_cents/100:.2f}.",
                  {"code": "insufficient_pay", "owed_cents": owed, "sent_cents": pay_amount_cents},
                  to=from_addr, thread_id=thread_id)
            return True

    print(f"BANNED user attempt: {from_addr} — {subject}")
    reply_id = message.get("message_id", "") or message.get("id", "")
    _oops(client, inbox_id, reply_id,
          "Fuck you, pay me.",
          {"code": "banned"},
          to=from_addr, thread_id=thread_id)
    return True


def handle_reversal(from_addr: str, subject: str, db_path: str) -> None:
    """Ban a user after a payment reversal."""
    print(f"REVERSAL DETECTED from {from_addr}: {subject}")
    recent_tx = get_most_recent_approved(db_path, from_addr)
    owed_cents = recent_tx["fiat_amount_cents"] if recent_tx else 0
    ban_email(db_path, from_addr, f"reversal: {subject}", amount_owed_cents=owed_cents)


def is_payment_notification(subject: str, text: str) -> tuple[bool, bool]:
    """Detect if an email is a forwarded payment notification or reversal.

    Returns (is_payment, is_reversal).
    """
    combined = f"{subject} {text}".lower()
    is_cashapp = "cash@square.com" in combined or "square.com" in combined
    is_venmo = "venmo@venmo.com" in combined or "venmo.com" in combined
    is_payment = (is_cashapp or is_venmo) and ("paid you" in combined or "sent you" in combined)
    is_reversal = any(w in combined for w in (
        "reversed", "dispute", "chargeback", "payment canceled", "payment returned", "declined"))
    return is_payment, is_reversal


# --- Re-exports from submodules so handler.py imports still work ---
from exchange.offer import handle_offer  # noqa: E402, F401
from exchange.match import handle_payment_notification  # noqa: E402, F401
from exchange.donate import handle_pay  # noqa: E402, F401
