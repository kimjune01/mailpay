"""Public API for the exchange ledger."""

from __future__ import annotations

import hashlib
import sys as _sys
from datetime import datetime, timezone
from typing import Optional

from exchange.ledger import (  # noqa: F401 — re-export for tests and other modules
    _append_event,
    _invalidate_cache,
    _read_ledger,
)
import exchange.ledger as _ledger

DEFAULT_DB = "exchange.db"  # kept for API compat, unused


# --- Test hook proxy ---
# Tests do `xdb._test_ledger_lines = []` etc. Python modules don't support
# __setattr__, so we replace this module with a class instance that proxies
# _test_ledger_lines and _test_append_sink writes to exchange.ledger.

class _DbModule:
    """Module replacement that proxies test hook writes to exchange.ledger."""

    def __init__(self, real_module):
        self.__dict__.update({k: v for k, v in real_module.__dict__.items()
                              if not k.startswith("_DbModule")})
        self._real_module = real_module

    def __getattr__(self, name):
        if name == "_test_ledger_lines":
            return _ledger._test_ledger_lines
        if name == "_test_append_sink":
            return _ledger._test_append_sink
        raise AttributeError(f"module 'exchange.db' has no attribute {name!r}")

    def __setattr__(self, name, value):
        if name in ("_real_module",):
            super().__setattr__(name, value)
            return
        if name == "_test_ledger_lines":
            _ledger._test_ledger_lines = value
            return
        if name == "_test_append_sink":
            _ledger._test_append_sink = value
            return
        self.__dict__[name] = value


# --- Helpers ---


def _hash_pii(value: str) -> str:
    """HMAC-SHA256 hash. Correlatable across ledger entries, not reversible."""
    import hmac
    from exchange.config import LEDGER_HMAC_KEY
    key = (LEDGER_HMAC_KEY or "default").encode()
    return hmac.new(key, value.lower().encode(), hashlib.sha256).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replay_offers(lines: list[dict]) -> dict[str, dict]:
    """Replay ledger events into a dict of offer_id -> transaction dict."""
    offers: dict[str, dict] = {}
    for ev in lines:
        event_type = ev.get("event")
        oid = ev.get("id")
        if event_type == "offer":
            offers[oid] = {
                "id": _ofr_to_int(oid),
                "created_at": ev.get("ts", ""),
                "message_id": ev.get("message_id"),
                "email_from": ev.get("from", ""),
                "cashapp_or_venmo": ev.get("rail"),
                "fiat_amount_cents": ev.get("amount_cents", 0),
                "sol_amount_lamports": ev.get("sol_lamports", 0),
                "sol_rate": ev.get("sol_rate", 0.0),
                "spread_rate": ev.get("spread_rate", 0.0),
                "wallet_address": ev.get("wallet", ""),
                "status": "pending",
                "payment_proof": ev.get("payment_proof"),
                "sol_tx": None,
                "thread_id": ev.get("thread_id", ""),
                "verified_at": None,
                "settled_at": None,
            }
        elif event_type == "claimed" and oid in offers:
            offers[oid]["status"] = "claiming"
        elif event_type == "approved" and oid in offers:
            offers[oid]["status"] = "approved"
            offers[oid]["sol_tx"] = ev.get("sol_tx")
            offers[oid]["verified_at"] = ev.get("ts")
            offers[oid]["settled_at"] = ev.get("ts")
        elif event_type == "rejected" and oid in offers:
            offers[oid]["status"] = "rejected"
            offers[oid]["verified_at"] = ev.get("ts")
    return offers


def _ofr_to_int(ofr_id: str) -> int:
    """Convert 'ofr_3' -> 3."""
    return int(ofr_id.split("_")[1])


def _int_to_ofr(n: int) -> str:
    """Convert 3 -> 'ofr_3'."""
    return f"ofr_{n}"


def _is_banned_from_lines(lines: list[dict], email_hash: str) -> bool:
    """Replay ban/unban events to determine current ban status."""
    banned = False
    for ev in lines:
        if ev.get("email", "") == email_hash:
            if ev.get("event") == "banned":
                banned = True
            elif ev.get("event") == "unbanned":
                banned = False
    return banned


# --- Public API (same signatures as before) ---


def init_db(db_path: str = DEFAULT_DB) -> None:
    """No-op. Kept for API compatibility."""
    pass


def create_transaction(
    db_path: str,
    email_from: str,
    fiat_amount_cents: int,
    sol_amount_lamports: int,
    sol_rate: float,
    spread_rate: float,
    wallet_address: str,
    thread_id: str,
    cashapp_or_venmo: Optional[str] = None,
    payment_proof: Optional[str] = None,
    message_id: Optional[str] = None,
) -> Optional[int]:
    """Append an 'offer' event. Returns the numeric id, or None if duplicate message_id."""
    lines, _ = _read_ledger()

    if message_id:
        for ev in lines:
            if ev.get("event") == "offer" and ev.get("message_id") == message_id:
                return None

    offer_count = sum(1 for ev in lines if ev.get("event") == "offer")
    new_id = offer_count + 1
    ofr_id = _int_to_ofr(new_id)

    event = {
        "ts": _now_iso(),
        "event": "offer",
        "id": ofr_id,
        "from": _hash_pii(email_from),
        "amount_cents": fiat_amount_cents,
        "rail": cashapp_or_venmo,
        "wallet": wallet_address,
        "thread_id": thread_id,
        "message_id": message_id,
        "sol_rate": sol_rate,
        "spread_rate": spread_rate,
        "sol_lamports": sol_amount_lamports,
        "payment_proof": payment_proof,
    }
    if _append_event(event):
        return new_id
    return None


def get_pending(db_path: str) -> list[dict]:
    """Return all pending transactions."""
    lines, _ = _read_ledger()
    offers = _replay_offers(lines)
    return sorted(
        [o for o in offers.values() if o["status"] == "pending"],
        key=lambda o: o["created_at"],
    )


def get_transaction(db_path: str, tx_id: int) -> Optional[dict]:
    """Get a single transaction by numeric id."""
    lines, _ = _read_ledger()
    offers = _replay_offers(lines)
    ofr_id = _int_to_ofr(tx_id)
    return offers.get(ofr_id)


def claim_transaction(db_path: str, tx_id: int) -> bool:
    """Atomically move a transaction from 'pending' to 'claiming'."""
    ofr_id = _int_to_ofr(tx_id)
    lines, _ = _read_ledger()
    offers = _replay_offers(lines)

    if ofr_id not in offers or offers[ofr_id]["status"] != "pending":
        return False

    event = {"ts": _now_iso(), "event": "claimed", "id": ofr_id}
    return _append_event(event)


def approve_transaction(db_path: str, tx_id: int, sol_tx: str) -> bool:
    """Mark a transaction as approved and record the SOL tx hash."""
    ofr_id = _int_to_ofr(tx_id)
    lines, _ = _read_ledger()
    offers = _replay_offers(lines)

    if ofr_id not in offers or offers[ofr_id]["status"] not in ("pending", "claiming"):
        return False

    event = {"ts": _now_iso(), "event": "approved", "id": ofr_id, "sol_tx": sol_tx}
    return _append_event(event)


def reject_transaction(db_path: str, tx_id: int) -> bool:
    """Mark a transaction as rejected."""
    ofr_id = _int_to_ofr(tx_id)
    lines, _ = _read_ledger()
    offers = _replay_offers(lines)

    if ofr_id not in offers or offers[ofr_id]["status"] != "pending":
        return False

    event = {"ts": _now_iso(), "event": "rejected", "id": ofr_id}
    return _append_event(event)


def ban_email(db_path: str, email: str, reason: str, amount_owed_cents: int = 0) -> bool:
    """Ban an email address. Returns True if newly banned."""
    email_lower = email.lower()
    lines, _ = _read_ledger()

    if _is_banned_from_lines(lines, email_lower):
        return False

    event = {
        "ts": _now_iso(),
        "event": "banned",
        "email": _hash_pii(email_lower),
        "reason": reason,
        "owed_cents": amount_owed_cents,
    }
    return _append_event(event)


def is_banned(db_path: str, email: str) -> bool:
    """Check if an email is banned."""
    lines, _ = _read_ledger()
    return _is_banned_from_lines(lines, _hash_pii(email))


def get_ban(db_path: str, email: str) -> Optional[dict]:
    """Get the ban details for an email, or None if not banned."""
    email_hash = _hash_pii(email)
    lines, _ = _read_ledger()

    ban_info = None
    for ev in lines:
        if ev.get("email", "") == email_hash:
            if ev.get("event") == "banned":
                ban_info = {
                    "email": email_hash,
                    "reason": ev.get("reason", ""),
                    "banned_at": ev.get("ts", ""),
                    "amount_owed_cents": ev.get("owed_cents", 0),
                }
            elif ev.get("event") == "unbanned":
                ban_info = None
    return ban_info


def unban_email(db_path: str, email: str) -> bool:
    """Lift a ban. Returns True if was banned."""
    email_hash = _hash_pii(email)
    lines, _ = _read_ledger()

    if not _is_banned_from_lines(lines, email_hash):
        return False

    event = {"ts": _now_iso(), "event": "unbanned", "email": email_hash}
    return _append_event(event)


def get_most_recent_approved(db_path: str, email_from: str) -> Optional[dict]:
    """Return the most recently approved transaction from this sender."""
    lines, _ = _read_ledger()
    offers = _replay_offers(lines)

    approved = [
        o for o in offers.values()
        if o["status"] == "approved" and o["email_from"] == _hash_pii(email_from)
    ]
    if not approved:
        return None
    return max(approved, key=lambda o: o["settled_at"] or "")


def get_all(db_path: str) -> list[dict]:
    """Return all transactions."""
    lines, _ = _read_ledger()
    offers = _replay_offers(lines)
    return sorted(offers.values(), key=lambda o: o["created_at"], reverse=True)


def get_stats(db_path: str) -> dict:
    """Return summary stats: total volume, count, average size."""
    lines, _ = _read_ledger()
    offers = _replay_offers(lines)
    approved = [o for o in offers.values() if o["status"] == "approved"]
    count = len(approved)
    total_cents = sum(o["fiat_amount_cents"] for o in approved)
    avg_cents = (total_cents / count) if count > 0 else 0
    return {
        "count": count,
        "total_cents": total_cents,
        "avg_cents": round(avg_cents, 2),
    }


# --- Module replacement for test hook proxying ---
# Must be at the very end, after all functions/classes are defined.

_current_module = _sys.modules[__name__]
_sys.modules[__name__] = _DbModule(_current_module)
