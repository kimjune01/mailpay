"""AgentMail webhook handler for the Cambio exchange.

Routes incoming emails by envelopay subject type:
  WHICH  -> reply METHODS with CashApp/Venmo rails and live SOL rate
  OFFER  -> validate, log pending transaction, reply acknowledgment
  Others -> OOPS with supported types

Operator approval (via CLI) triggers SOL send and ACCEPT reply.
"""

from __future__ import annotations

import json
import os
import re

from agentmail import AgentMail

from exchange.config import (
    AGENTMAIL_API_KEY,
    CASHAPP_HANDLE,
    EXCHANGE_INBOX,
    KNOWN_TYPES,
    MAX_FIAT_CENTS,
    MIN_FIAT_CENTS,
    SOL_WALLET,
    SPREAD,
    VENMO_HANDLE,
    WEBHOOK_SECRET,
)
from exchange.db import (
    approve_transaction,
    ban_email,
    claim_transaction,
    create_transaction,
    get_ban,
    get_most_recent_approved,
    get_pending,
    init_db,
    is_banned,
    unban_email,
)
from exchange.settle import send_sol
from exchange.rate import apply_spread, get_sol_usd_rate, usd_cents_to_lamports

PROTOCOL_RE = re.compile(r"^([A-Z]+)(\s*\|.*)?$")
AMOUNT_RE = re.compile(r"\$(\d+\.\d{2})")

# Base58 alphabet used by Solana
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")

# Extract sender name from CashApp/Venmo notification ("X paid you $Y")
_SENDER_RE = re.compile(r"(.+?)\s+(?:paid|sent)\s+you\s+\$", re.IGNORECASE)

# DB path — use /tmp on Lambda (read-only filesystem), local dir otherwise
if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    DB_PATH = "/tmp/exchange.db"
else:
    DB_PATH = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "exchange.db"))


def _check_webhook_secret(headers: dict) -> bool:
    """Return True if the webhook secret is valid (or if no secret is configured)."""
    if not WEBHOOK_SECRET:
        return True
    # Case-insensitive header lookup (API Gateway lowercases headers)
    for key, value in headers.items():
        if key.lower() == "x-webhook-secret" and value == WEBHOOK_SECRET:
            return True
    return False


def process_email(payload: dict, db_path: str = DB_PATH) -> None:
    """Process an incoming email from the webhook."""
    client = AgentMail(api_key=AGENTMAIL_API_KEY)
    init_db(db_path)

    message = payload.get("message", {})
    from_addr = message.get("from_", "")
    subject = message.get("subject", "")
    inbox_id = message.get("inbox_id", EXCHANGE_INBOX)
    thread_id = message.get("thread_id", "")
    reply_to_msg_id = message.get("message_id", "") or message.get("id", "")
    text = message.get("text", "") or ""
    message_id = message.get("id", "") or payload.get("message_id", "")

    # Skip our own sent messages
    if EXCHANGE_INBOX in from_addr:
        return

    # Banned users: PAY lifts the ban only if amount covers the debt
    ban_row = get_ban(db_path, from_addr)
    if ban_row:
        stripped_check = subject.strip()
        if PROTOCOL_RE.match(stripped_check) and PROTOCOL_RE.match(stripped_check).group(1) == "PAY":
            # Parse PAY amount from JSON body
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
            if pay_amount_cents >= owed:
                unban_email(db_path, from_addr)
                print(f"UNBANNED {from_addr} — sent PAY, debt settled")
                reply_to_msg_id = message.get("message_id", "") or message.get("id", "")
                _reply(client, inbox_id, reply_to_msg_id,
                       subject="OOPS | Debt settled, you're back",
                       text=json.dumps({"v": "0.1.0", "type": "oops",
                                        "note": "Debt settled. You're unbanned. Don't do it again.",
                                        "error": {"code": "unbanned"}}, indent=2),
                       headers={"X-Envelopay-Type": "OOPS"},
                       to=from_addr)
                return
            else:
                reply_to_msg_id = message.get("message_id", "") or message.get("id", "")
                _oops(client, inbox_id, reply_to_msg_id,
                      f"You owe ${owed/100:.2f}, you sent ${pay_amount_cents/100:.2f}.",
                      {"code": "insufficient_pay", "owed_cents": owed, "sent_cents": pay_amount_cents},
                      to=from_addr)
                return
        print(f"BANNED user attempt: {from_addr} — {subject}")
        reply_to_msg_id = message.get("message_id", "") or message.get("id", "")
        _oops(client, inbox_id, reply_to_msg_id,
              "Fuck you, pay me.",
              {"code": "banned"},
              to=from_addr)
        return

    # Parse subject for protocol type
    stripped = subject.strip()
    match = PROTOCOL_RE.match(stripped)
    msg_type = match.group(1) if match else None

    # Unknown protocol type
    if msg_type and msg_type not in KNOWN_TYPES:
        types = " | ".join(sorted(KNOWN_TYPES))
        _oops(client, inbox_id, reply_to_msg_id,
              f"Unknown type: {msg_type}",
              {"code": "unknown_type",
               "sent": msg_type,
               "supported": sorted(KNOWN_TYPES),
               "spec": "https://june.kim/envelopay-spec.md"},
              to=from_addr)
        return

    # WHICH -> reply METHODS with rails and rate
    if msg_type == "WHICH" or stripped.upper() == "WHICH":
        _handle_which(client, inbox_id, reply_to_msg_id, from_addr)
        return

    # OFFER -> validate and log
    if msg_type == "OFFER":
        _handle_offer(client, inbox_id, reply_to_msg_id, from_addr, text, db_path, message_id, thread_id, from_addr)
        return

    # Anything else we don't handle
    if msg_type:
        _oops(client, inbox_id, reply_to_msg_id,
              "This exchange only handles WHICH and OFFER",
              {"code": "unsupported_flow",
               "sent": msg_type,
               "supported": ["WHICH", "OFFER"]},
              to=from_addr)
        return

    # Check for forwarded CashApp/Venmo payment notifications
    combined = f"{subject} {text}".lower()
    is_cashapp = "cash@square.com" in combined or "square.com" in combined
    is_venmo = "venmo@venmo.com" in combined or "venmo.com" in combined
    is_payment = (is_cashapp or is_venmo) and ("paid you" in combined or "sent you" in combined)
    is_reversal = any(w in combined for w in ("reversed", "dispute", "chargeback", "payment canceled", "payment returned", "declined"))
    if is_payment and not is_reversal:
        _handle_payment_notification(client, inbox_id, from_addr, subject, text, db_path)
        return
    if is_reversal:
        print(f"REVERSAL DETECTED from {from_addr}: {subject}")
        # Look up the most recent approved transaction from this sender for the owed amount
        recent_tx = get_most_recent_approved(db_path, from_addr)
        owed_cents = recent_tx["fiat_amount_cents"] if recent_tx else 0
        ban_email(db_path, from_addr, f"reversal: {subject}", amount_owed_cents=owed_cents)
        return

    # Non-protocol email — ignore silently
    return


def _handle_which(client: AgentMail, inbox_id: str, reply_to_msg_id: str, to: str = "") -> None:
    """Reply METHODS with CashApp/Venmo rails and live SOL rate."""
    try:
        raw_rate = get_sol_usd_rate()
    except Exception:
        _oops(client, inbox_id, reply_to_msg_id,
              "Rate unavailable, try again later",
              {"code": "rate_unavailable"},
              to=to)
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
           to=to)


def _is_valid_base58(address: str) -> bool:
    """Check if a string contains only valid base58 characters."""
    return bool(_BASE58_RE.match(address))


def _handle_offer(
    client: AgentMail, inbox_id: str, reply_to_msg_id: str,
    from_addr: str, text: str, db_path: str, message_id: str = "", thread_id: str = "",
    to: str = "",
) -> None:
    """Validate OFFER, log pending transaction, reply acknowledgment."""
    body = _parse_json_from_text(text)

    # Extract amount in cents
    amount_cents = 0
    give = body.get("give", {})
    if isinstance(give, dict):
        # give.amount is in cents (smallest USD unit)
        try:
            amount_cents = int(give.get("amount", 0))
        except (ValueError, TypeError):
            amount_cents = 0

    # Fallback: top-level amount field
    if not amount_cents:
        try:
            amount_cents = int(body.get("amount", 0))
        except (ValueError, TypeError):
            amount_cents = 0

    # Validate range
    if amount_cents < MIN_FIAT_CENTS:
        _oops(client, inbox_id, reply_to_msg_id,
              f"Minimum is ${MIN_FIAT_CENTS/100:.2f}",
              {"code": "amount_too_low", "min_cents": MIN_FIAT_CENTS,
               "sent_cents": amount_cents},
              to=to)
        return

    if amount_cents > MAX_FIAT_CENTS:
        _oops(client, inbox_id, reply_to_msg_id,
              f"Maximum is ${MAX_FIAT_CENTS/100:.2f}",
              {"code": "amount_too_high", "max_cents": MAX_FIAT_CENTS,
               "sent_cents": amount_cents},
              to=to)
        return

    # Extract wallet address
    wallet = body.get("wallet", "")
    if not wallet or len(wallet) < 32 or len(wallet) > 44:
        _oops(client, inbox_id, reply_to_msg_id,
              "Missing or invalid Solana wallet address",
              {"code": "missing_wallet",
               "expected": '{"wallet": "your_solana_address", "give": {"amount": 100, ...}}'},
              to=to)
        return

    # Validate base58
    if not _is_valid_base58(wallet):
        _oops(client, inbox_id, reply_to_msg_id,
              "Invalid Solana wallet address (bad characters)",
              {"code": "invalid_wallet",
               "expected": "base58-encoded Solana address"},
              to=to)
        return

    # Get rate and compute SOL amount
    try:
        raw_rate = get_sol_usd_rate()
    except Exception:
        _oops(client, inbox_id, reply_to_msg_id,
              "Rate unavailable, try again later",
              {"code": "rate_unavailable"},
              to=to)
        return

    spread_rate = apply_spread(raw_rate, SPREAD)
    sol_lamports = usd_cents_to_lamports(amount_cents, spread_rate)

    # Detect rail
    proof = give.get("proof", {}) if isinstance(give, dict) else {}
    rail = give.get("chain", "") if isinstance(give, dict) else ""
    payment_proof = json.dumps(proof) if proof else None

    # Log to DB (deduplicate on message_id)
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

    # Duplicate message — silently skip
    if tx_id is None:
        return

    # Reply acknowledgment (not ACCEPT yet — operator must verify)
    ack = {
        "v": "0.1.0",
        "type": "oops",
        "note": f"Payment received, verifying. You'll get ${amount_cents/100:.2f} worth of SOL "
                f"({sol_lamports} lamports) to {wallet} once confirmed. Ref #{tx_id}.",
        "error": {"code": "pending_verification", "tx_id": tx_id},
    }
    _reply(client, inbox_id, reply_to_msg_id,
           subject=f"OOPS | Payment received, verifying (ref #{tx_id})",
           text=json.dumps(ack, indent=2),
           headers={"X-Envelopay-Type": "OOPS"},
           to=to)


def _handle_payment_notification(
    client: AgentMail, inbox_id: str, from_addr: str,
    subject: str, text: str, db_path: str,
) -> None:
    """Auto-match a forwarded CashApp/Venmo payment notification to a pending OFFER."""
    import logging
    logger = logging.getLogger(__name__)

    combined = f"{subject} {text}"
    match = AMOUNT_RE.search(combined)
    if not match:
        logger.info("Payment notification but no dollar amount found — ignoring")
        return

    dollars = float(match.group(1))
    amount_cents = int(round(dollars * 100))

    # Detect rail from the notification
    combined_lower = combined.lower()
    notif_rail = None
    if "cash@square.com" in combined_lower or "square.com" in combined_lower:
        notif_rail = "cashapp"
    elif "venmo@venmo.com" in combined_lower or "venmo.com" in combined_lower:
        notif_rail = "venmo"

    # Find oldest pending transaction matching amount AND rail (FIFO)
    pending = get_pending(db_path)
    matched_tx = None
    for tx in pending:
        if tx["fiat_amount_cents"] != amount_cents:
            continue
        # Match rail if both notification and offer specify one
        if notif_rail and tx["cashapp_or_venmo"] and tx["cashapp_or_venmo"] != notif_rail:
            continue
        matched_tx = tx
        break

    if not matched_tx:
        logger.info("Payment notification for $%.2f but no matching pending OFFER — ignoring", dollars)
        return

    # Bug 1 fix: claim BEFORE sending SOL to prevent double-pay
    if not claim_transaction(db_path, matched_tx["id"]):
        logger.warning("Transaction %d was already claimed — skipping", matched_tx["id"])
        return

    sol_tx_hash = send_sol(matched_tx["sol_amount_lamports"], matched_tx["wallet_address"])
    approve_transaction(db_path, matched_tx["id"], sol_tx_hash)

    # Bug 3 fix: pass to_addr from the transaction, not from thread lookup
    send_accept(
        thread_id=matched_tx["thread_id"],
        offer_ref=str(matched_tx["id"]),
        sol_tx=sol_tx_hash,
        lamports=matched_tx["sol_amount_lamports"],
        wallet=matched_tx["wallet_address"],
        to_addr=matched_tx["email_from"],
    )
    logger.info(
        "Auto-approved tx #%d: $%.2f -> %d lamports to %s (sol_tx: %s)",
        matched_tx["id"], dollars, matched_tx["sol_amount_lamports"],
        matched_tx["wallet_address"], sol_tx_hash,
    )


def _get_last_message_info(client: AgentMail, thread_id: str) -> tuple[str, str]:
    """Get the last message ID and sender address in a thread."""
    thread = client.inboxes.threads.get(inbox_id=EXCHANGE_INBOX, thread_id=thread_id)
    if thread.messages:
        last = thread.messages[-1]
        return (last.message_id or "", last.from_ or "")
    return ("", "")


def send_accept(thread_id: str, offer_ref: str, sol_tx: str,
                lamports: int, wallet: str, to_addr: str = "") -> None:
    """Send ACCEPT reply after operator approves. Called from CLI."""
    client = AgentMail(api_key=AGENTMAIL_API_KEY)
    msg_id, _thread_to = _get_last_message_info(client, thread_id)
    if not msg_id:
        print(f"No messages found in thread {thread_id}")
        return
    # Use explicit to_addr if provided (from DB); fall back to thread lookup
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
    client = AgentMail(api_key=AGENTMAIL_API_KEY)
    msg_id, to_addr = _get_last_message_info(client, thread_id)
    if not msg_id:
        print(f"No messages found in thread {thread_id}")
        return
    _oops(client, EXCHANGE_INBOX, msg_id, reason,
          {"code": "rejected", "reason": reason},
          to=to_addr)


def _parse_json_from_text(text: str) -> dict:
    """Try to parse JSON from a text body.

    Handles both single-line and multi-line pretty-printed JSON.
    """
    # Try the full text first (handles multi-line pretty-printed JSON)
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # Fall back to line-by-line scan
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    return {}


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


def _reply(client: AgentMail, inbox_id: str, message_id: str,
           subject: str, text: str, headers: dict = None, to: str = "") -> None:
    """Send a message via AgentMail with explicit subject (messages.send).

    Uses send() instead of reply() so the protocol type appears in the subject line.
    The protocol uses typed refs (order_ref, offer_ref) for correlation, so email
    threading is not required.
    """
    full_text = f"{subject}\n\n{text}" if subject else text
    client.inboxes.messages.send(
        inbox_id=inbox_id,
        to=to,
        subject=subject,
        text=full_text,
        headers=headers or {},
    )


# --- Lambda handler ---

def lambda_handler(event, context):
    """AWS Lambda entry point."""
    # Check webhook secret
    headers = event.get("headers", {})
    if not _check_webhook_secret(headers):
        return {"statusCode": 401, "body": "Unauthorized"}

    body = json.loads(event.get("body", "{}"))
    if body.get("event_type") == "message.received":
        process_email(body)
    return {"statusCode": 200}


# --- Local Flask server ---

if __name__ == "__main__":
    from flask import Flask, request, Response
    app = Flask(__name__)

    @app.route("/webhook", methods=["POST"])
    def webhook():
        # Check webhook secret
        if not _check_webhook_secret(dict(request.headers)):
            return Response(status=401)
        payload = request.json
        if payload.get("event_type") == "message.received":
            process_email(payload)
        return Response(status=200)

    print(f"Cambio exchange listening on http://localhost:3001/webhook")
    print(f"Inbox: {EXCHANGE_INBOX}")
    app.run(port=3001)
