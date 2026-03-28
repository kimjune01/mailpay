"""Payment notification matching for the Cambio exchange protocol."""

from __future__ import annotations

import logging

from agentmail import AgentMail

from exchange.config import LOW_BALANCE_LAMPORTS
from exchange.db import approve_transaction, claim_transaction, get_pending
from exchange.reply import _alert_low_balance, _set_low_balance_alerted, get_low_balance_alerted
from exchange.routes import AMOUNT_RE
from exchange.settle import get_balance

logger = logging.getLogger(__name__)


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
