"""GitHub-backed JSONL ledger for the exchange."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone


def _protect_email(email: str) -> str:
    """XOR-encrypt email with HMAC key. Reversible with the key, opaque without it."""
    from exchange.config import LEDGER_HMAC_KEY
    key = (LEDGER_HMAC_KEY or "default").encode()
    email_bytes = email.lower().encode()
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(email_bytes))
    return base64.b64encode(encrypted).decode()


def _unprotect_email(token: str) -> str:
    """Reverse XOR-encryption to recover the email."""
    from exchange.config import LEDGER_HMAC_KEY
    key = (LEDGER_HMAC_KEY or "default").encode()
    encrypted = base64.b64decode(token)
    decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted))
    return decrypted.decode()
from typing import Optional

from exchange.config import LEDGER_GITHUB_TOKEN, LEDGER_REPO, LEDGER_PREFIX

DEFAULT_DB = "exchange.db"  # kept for API compat, unused

# --- Cache ---
_cache_lines: Optional[list[dict]] = None
_cache_ts: float = 0.0
_cache_sha: Optional[str] = None
_CACHE_TTL = 5.0  # seconds

# --- Test override ---
# Tests can populate this list to bypass GitHub API entirely.
_test_ledger_lines: Optional[list[dict]] = None
_test_append_sink: Optional[list[dict]] = None


def _github_headers() -> dict:
    return {
        "Authorization": f"Bearer {LEDGER_GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _ledger_url() -> str:
    return f"https://api.github.com/repos/{LEDGER_REPO}/contents/{LEDGER_PREFIX}/ledger.jsonl"


def _read_ledger() -> tuple[list[dict], Optional[str]]:
    """Fetch JSONL from GitHub. Returns (lines, sha).

    Uses a module-level cache (refreshed every 5s).
    If _test_ledger_lines is set, returns that instead (for testing).
    """
    global _cache_lines, _cache_ts, _cache_sha

    if _test_ledger_lines is not None:
        return list(_test_ledger_lines), "test-sha"

    now = time.time()
    if _cache_lines is not None and (now - _cache_ts) < _CACHE_TTL:
        return list(_cache_lines), _cache_sha

    req = urllib.request.Request(_ledger_url(), headers=_github_headers())
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        content = base64.b64decode(data["content"]).decode("utf-8")
        sha = data["sha"]
        lines = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if line:
                lines.append(json.loads(line))
        _cache_lines = lines
        _cache_sha = sha
        _cache_ts = now
        return list(lines), sha
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # File doesn't exist yet
            _cache_lines = []
            _cache_sha = None
            _cache_ts = now
            return [], None
        raise


def _append_event(event: dict) -> bool:
    """Append a JSON event line to the ledger via GitHub Contents API.

    Returns True on success, False on 409 conflict (SHA mismatch).
    If _test_append_sink is set, appends there instead (for testing).
    """
    global _cache_lines, _cache_ts, _cache_sha

    if _test_append_sink is not None:
        _test_append_sink.append(event)
        # Also update the test ledger if it exists
        if _test_ledger_lines is not None:
            _test_ledger_lines.append(event)
        return True

    lines, sha = _read_ledger()
    new_line = json.dumps(event, separators=(",", ":"))

    if lines:
        # Reconstruct existing content and append
        existing_lines = [json.dumps(l, separators=(",", ":")) for l in lines]
        new_content = "\n".join(existing_lines) + "\n" + new_line + "\n"
    else:
        new_content = new_line + "\n"

    encoded = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
    body = {
        "message": f"ledger: {event.get('event', 'unknown')}",
        "content": encoded,
    }
    if sha:
        body["sha"] = sha

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        _ledger_url(),
        data=data,
        headers={**_github_headers(), "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            resp_data = json.loads(resp.read())
        # Update cache
        _cache_sha = resp_data["content"]["sha"]
        lines.append(event)
        _cache_lines = lines
        _cache_ts = time.time()
        return True
    except urllib.error.HTTPError as e:
        if e.code == 409:
            # SHA conflict — someone else wrote concurrently
            _invalidate_cache()
            return False
        raise


def _invalidate_cache() -> None:
    global _cache_lines, _cache_ts, _cache_sha
    _cache_lines = None
    _cache_ts = 0.0
    _cache_sha = None


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
                "email_from": _unprotect_email(ev["from"]) if ev.get("from") else "",
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

    # Check for duplicate message_id
    if message_id:
        for ev in lines:
            if ev.get("event") == "offer" and ev.get("message_id") == message_id:
                return None

    # Auto-increment: count existing offer events + 1
    offer_count = sum(1 for ev in lines if ev.get("event") == "offer")
    new_id = offer_count + 1
    ofr_id = _int_to_ofr(new_id)

    event = {
        "ts": _now_iso(),
        "event": "offer",
        "id": ofr_id,
        "from": _protect_email(email_from),
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
    """Return all pending transactions (offers without approved/rejected/claimed events)."""
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
    """Atomically move a transaction from 'pending' to 'claiming'.

    Uses SHA-based PUT as a lock. Two concurrent claims: first wins, second gets 409.
    Returns True if this caller won the claim.
    """
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

    # Check if already banned (banned without subsequent unbanned)
    if _is_banned_from_lines(lines, email_lower):
        return False

    event = {
        "ts": _now_iso(),
        "event": "banned",
        "email": _protect_email(email_lower),
        "reason": reason,
        "owed_cents": amount_owed_cents,
    }
    return _append_event(event)


def is_banned(db_path: str, email: str) -> bool:
    """Check if an email is banned."""
    lines, _ = _read_ledger()
    return _is_banned_from_lines(lines, _protect_email(email))


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


def get_ban(db_path: str, email: str) -> Optional[dict]:
    """Get the ban details for an email, or None if not banned."""
    email_hash = _protect_email(email)
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
    email_hash = _protect_email(email)
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
        if o["status"] == "approved" and o["email_from"] == email_from
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
