"""PAY (donation) handler for the Cambio exchange protocol."""

from __future__ import annotations

import json

from agentmail import AgentMail

from exchange.db import _hash_pii, _append_event
from exchange.reply import _oops, _reply
from exchange.routes import _parse_json_from_text


def handle_pay(client: AgentMail, inbox_id: str, reply_to_msg_id: str,
               from_addr: str, text: str, db_path: str,
               message_id: str = "") -> None:
    """Accept a PAY (donation). Verify on-chain, log to ledger, say thanks."""
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
