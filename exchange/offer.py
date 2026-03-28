"""OFFER handler for the Cambio exchange protocol."""

from __future__ import annotations

import json

from agentmail import AgentMail

from exchange.config import MAX_FIAT_CENTS, MIN_FIAT_CENTS, SPREAD
from exchange.db import create_transaction
from exchange.rate import apply_spread, usd_cents_to_lamports
from exchange.reply import _oops
from exchange.routes import _parse_json_from_text
from exchange.verify import is_valid_base58


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
