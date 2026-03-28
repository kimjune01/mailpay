"""Type handlers for the Cambio exchange protocol."""

from __future__ import annotations

import json
import logging
import re

from agentmail import AgentMail

from exchange.config import (
    CASHAPP_HANDLE,
    LOW_BALANCE_LAMPORTS,
    MAX_FIAT_CENTS,
    MIN_FIAT_CENTS,
    SOL_WALLET,
    SPREAD,
    VENMO_HANDLE,
)
from exchange.db import (
    _hash_pii,
    approve_transaction,
    ban_email,
    claim_transaction,
    create_transaction,
    get_most_recent_approved,
    get_pending,
    unban_email,
)
from exchange.rate import apply_spread, usd_cents_to_lamports
from exchange.reply import (
    _alert_low_balance,
    _oops,
    _reply,
    _set_low_balance_alerted,
    get_low_balance_alerted,
)
from exchange.settle import get_balance
from exchange.verify import is_valid_base58

PROTOCOL_RE = re.compile(r"^([A-Z]+)(\s*\|.*)?$")
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
                 from_addr: str, text: str, db_path: str) -> None:
    """Reply METHODS with CashApp/Venmo rails and live SOL rate."""
    # Import from handler so tests can patch xh.get_sol_usd_rate
    from exchange import handler as _h
    try:
        raw_rate = _h.get_sol_usd_rate()
    except Exception:
        _oops(client, inbox_id, reply_to_msg_id,
              "Rate unavailable, try again later",
              {"code": "rate_unavailable"},
              to=from_addr)
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
           to=from_addr)


def handle_offer(client: AgentMail, inbox_id: str, reply_to_msg_id: str,
                 from_addr: str, text: str, db_path: str,
                 message_id: str = "", thread_id: str = "", to: str = "") -> None:
    """Validate OFFER, log pending transaction, reply acknowledgment."""
    # Import from handler so tests can patch xh.get_sol_usd_rate
    from exchange import handler as _h

    body = _parse_json_from_text(text)

    amount_cents = 0
    give = body.get("give", {})
    if isinstance(give, dict):
        try:
            amount_cents = int(give.get("amount", 0))
        except (ValueError, TypeError):
            amount_cents = 0

    if not amount_cents:
        try:
            amount_cents = int(body.get("amount", 0))
        except (ValueError, TypeError):
            amount_cents = 0

    if amount_cents < MIN_FIAT_CENTS:
        _oops(client, inbox_id, reply_to_msg_id,
              f"Minimum is ${MIN_FIAT_CENTS/100:.2f}",
              {"code": "amount_too_low", "min_cents": MIN_FIAT_CENTS,
               "sent_cents": amount_cents},
              to=to)
        return

    if amount_cents > MAX_FIAT_CENTS:
        amount_cents = MAX_FIAT_CENTS

    wallet = body.get("wallet", "")
    if not wallet or len(wallet) < 32 or len(wallet) > 44:
        _oops(client, inbox_id, reply_to_msg_id,
              "Missing or invalid Solana wallet address",
              {"code": "missing_wallet",
               "expected": '{"wallet": "your_solana_address", "give": {"amount": 100, ...}}'},
              to=to)
        return

    if not is_valid_base58(wallet):
        _oops(client, inbox_id, reply_to_msg_id,
              "Invalid Solana wallet address (bad characters)",
              {"code": "invalid_wallet",
               "expected": "base58-encoded Solana address"},
              to=to)
        return

    try:
        raw_rate = _h.get_sol_usd_rate()
    except Exception:
        _oops(client, inbox_id, reply_to_msg_id,
              "Rate unavailable, try again later",
              {"code": "rate_unavailable"},
              to=to)
        return

    spread_rate = apply_spread(raw_rate, SPREAD)
    sol_lamports = usd_cents_to_lamports(amount_cents, spread_rate)

    proof = give.get("proof", {}) if isinstance(give, dict) else {}
    rail = give.get("chain", "") if isinstance(give, dict) else ""
    payment_proof = json.dumps(proof) if proof else None

    tx_id = create_transaction(
        db_path=db_path,
        email_from=from_addr,
        fiat_amount_cents=amount_cents,
        sol_amount_lamports=sol_lamports,
        sol_rate=raw_rate,
        spread_rate=spread_rate,
        wallet_address=wallet,
        thread_id=thread_id,
        cashapp_or_venmo=rail or None,
        payment_proof=payment_proof,
        message_id=message_id or None,
    )

    if tx_id is None:
        return

    # Silence. The user gets ACCEPT when payment matches, or nothing.
    # Pending isn't an error — don't OOPS it.


def handle_pay(client: AgentMail, inbox_id: str, reply_to_msg_id: str,
               from_addr: str, text: str, db_path: str,
               message_id: str = "") -> None:
    """Accept a PAY (donation). Verify on-chain, log to ledger, say thanks."""
    from exchange.db import _append_event
    from exchange.settle import _rpc

    body = _parse_json_from_text(text)
    proof = body.get("proof", {})
    tx_hash = proof.get("tx", "") if isinstance(proof, dict) else ""

    if not tx_hash:
        _oops(client, inbox_id, reply_to_msg_id,
              "PAY requires a proof with a tx hash",
              {"code": "missing_proof"},
              to=from_addr)
        return

    try:
        result = _rpc("getTransaction", [
            tx_hash,
            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
        ])
        if not result.get("result"):
            _oops(client, inbox_id, reply_to_msg_id,
                  "Transaction not found on-chain",
                  {"code": "tx_not_found", "tx": tx_hash},
                  to=from_addr)
            return
    except Exception:
        _oops(client, inbox_id, reply_to_msg_id,
              "Could not verify transaction, try again later",
              {"code": "verification_failed"},
              to=from_addr)
        return

    amount = body.get("amount", "0")
    note = body.get("note", "")

    _append_event({
        "event": "donation",
        "from": _hash_pii(from_addr),
        "amount": amount,
        "token": body.get("token", "SOL"),
        "chain": body.get("chain", "solana"),
        "proof": {"tx": tx_hash},
        "note": note,
        "message_id": message_id,
    })

    _reply(client, inbox_id, reply_to_msg_id,
           subject="OOPS | Thank you",
           text=json.dumps({"v": "0.1.0", "type": "oops",
                            "note": "Thank you for keeping the machine running.",
                            "error": {"code": "donation_received"}}, indent=2),
           headers={"X-Envelopay-Type": "OOPS"},
           to=from_addr)
    print(f"DONATION from {from_addr}: {amount} {body.get('token', 'SOL')} (tx: {tx_hash})")


def handle_payment_notification(client: AgentMail, inbox_id: str, from_addr: str,
                                subject: str, text: str, db_path: str) -> None:
    """Auto-match a forwarded CashApp/Venmo payment notification to a pending OFFER."""
    # Import from handler so tests can patch xh.send_sol and xh.send_accept
    from exchange import handler as _h

    combined = f"{subject} {text}"
    match = AMOUNT_RE.search(combined)
    if not match:
        logger.info("Payment notification but no dollar amount found — ignoring")
        return

    dollars = float(match.group(1))
    amount_cents = int(round(dollars * 100))

    combined_lower = combined.lower()
    notif_rail = None
    if "cash@square.com" in combined_lower or "square.com" in combined_lower:
        notif_rail = "cashapp"
    elif "venmo@venmo.com" in combined_lower or "venmo.com" in combined_lower:
        notif_rail = "venmo"

    pending = get_pending(db_path)
    matched_tx = None
    for tx in pending:
        if amount_cents < tx["fiat_amount_cents"]:
            continue
        if notif_rail and tx["cashapp_or_venmo"] and tx["cashapp_or_venmo"] != notif_rail:
            continue
        matched_tx = tx
        break

    if not matched_tx:
        logger.info("Payment notification for $%.2f but no matching pending OFFER — ignoring", dollars)
        return

    if not claim_transaction(db_path, matched_tx["id"]):
        logger.warning("Transaction %d was already claimed — skipping", matched_tx["id"])
        return

    sol_tx_hash = _h.send_sol(matched_tx["sol_amount_lamports"], matched_tx["wallet_address"])
    approve_transaction(db_path, matched_tx["id"], sol_tx_hash)

    # Look up the original sender from the thread (ledger only has hash)
    _, original_sender = _h._get_last_message_info(client, matched_tx["thread_id"])
    _h.send_accept(
        thread_id=matched_tx["thread_id"],
        offer_ref=str(matched_tx["id"]),
        sol_tx=sol_tx_hash,
        lamports=matched_tx["sol_amount_lamports"],
        wallet=matched_tx["wallet_address"],
        to_addr=original_sender,
    )
    logger.info(
        "Auto-approved tx #%d: $%.2f -> %d lamports to %s (sol_tx: %s)",
        matched_tx["id"], dollars, matched_tx["sol_amount_lamports"],
        matched_tx["wallet_address"], sol_tx_hash,
    )

    try:
        balance = get_balance()
        if balance < LOW_BALANCE_LAMPORTS and not get_low_balance_alerted():
            _alert_low_balance(client, inbox_id, balance)
            _set_low_balance_alerted(True)
        elif balance >= LOW_BALANCE_LAMPORTS:
            _set_low_balance_alerted(False)
    except Exception:
        pass


def handle_banned(client, inbox_id, reply_to_msg_id, from_addr, subject, text, db_path, ban_row, message) -> bool:
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
                   to=from_addr)
            return True
        else:
            _oops(client, inbox_id, reply_id,
                  f"You owe ${owed/100:.2f}, you sent ${pay_amount_cents/100:.2f}.",
                  {"code": "insufficient_pay", "owed_cents": owed, "sent_cents": pay_amount_cents},
                  to=from_addr)
            return True

    print(f"BANNED user attempt: {from_addr} — {subject}")
    reply_id = message.get("message_id", "") or message.get("id", "")
    _oops(client, inbox_id, reply_id,
          "Fuck you, pay me.",
          {"code": "banned"},
          to=from_addr)
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
