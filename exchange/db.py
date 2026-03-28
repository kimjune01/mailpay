"""SQLite transaction log for the exchange."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

DEFAULT_DB = "exchange.db"


def _connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str = DEFAULT_DB) -> None:
    """Create the transactions table if it doesn't exist."""
    conn = _connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS banned (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            reason TEXT NOT NULL,
            banned_at TEXT NOT NULL,
            amount_owed_cents INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            message_id TEXT UNIQUE,
            email_from TEXT NOT NULL,
            cashapp_or_venmo TEXT,
            fiat_amount_cents INTEGER NOT NULL,
            sol_amount_lamports INTEGER NOT NULL,
            sol_rate REAL NOT NULL,
            spread_rate REAL NOT NULL,
            wallet_address TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            payment_proof TEXT,
            sol_tx TEXT,
            thread_id TEXT NOT NULL,
            verified_at TEXT,
            settled_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def ban_email(db_path: str, email: str, reason: str, amount_owed_cents: int = 0) -> bool:
    """Permaban an email address. Returns True if newly banned."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO banned (email, reason, banned_at, amount_owed_cents) VALUES (?, ?, ?, ?)",
            (email.lower(), reason, datetime.now(timezone.utc).isoformat(), amount_owed_cents),
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def is_banned(db_path: str, email: str) -> bool:
    """Check if an email is banned."""
    conn = _connect(db_path)
    row = conn.execute("SELECT 1 FROM banned WHERE email = ?", (email.lower(),)).fetchone()
    conn.close()
    return row is not None


def get_ban(db_path: str, email: str) -> Optional[dict]:
    """Get the ban row for an email, or None if not banned."""
    conn = _connect(db_path)
    row = conn.execute("SELECT * FROM banned WHERE email = ?", (email.lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def unban_email(db_path: str, email: str) -> bool:
    """Lift a ban. Returns True if was banned."""
    conn = _connect(db_path)
    cur = conn.execute("DELETE FROM banned WHERE email = ?", (email.lower(),))
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


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
    """Insert a pending transaction. Returns the row id, or None if duplicate message_id."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO transactions
               (created_at, message_id, email_from, cashapp_or_venmo, fiat_amount_cents,
                sol_amount_lamports, sol_rate, spread_rate, wallet_address,
                status, payment_proof, thread_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                message_id,
                email_from,
                cashapp_or_venmo,
                fiat_amount_cents,
                sol_amount_lamports,
                sol_rate,
                spread_rate,
                wallet_address,
                payment_proof,
                thread_id,
            ),
        )
        conn.commit()
        row_id = cur.lastrowid
        conn.close()
        return row_id
    except sqlite3.IntegrityError:
        conn.close()
        return None


def get_pending(db_path: str) -> list[dict]:
    """Return all pending transactions."""
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM transactions WHERE status = 'pending' ORDER BY created_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_transaction(db_path: str, tx_id: int) -> Optional[dict]:
    """Get a single transaction by id."""
    conn = _connect(db_path)
    row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def claim_transaction(db_path: str, tx_id: int) -> bool:
    """Atomically move a transaction from 'pending' to 'claiming'.

    Returns True if this caller won the claim. False means another
    caller (concurrent Lambda or CLI) already claimed it.
    """
    conn = _connect(db_path)
    cur = conn.execute(
        "UPDATE transactions SET status = 'claiming' WHERE id = ? AND status = 'pending'",
        (tx_id,),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def approve_transaction(db_path: str, tx_id: int, sol_tx: str) -> bool:
    """Mark a transaction as approved and record the SOL tx hash."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(db_path)
    cur = conn.execute(
        """UPDATE transactions SET status = 'approved', sol_tx = ?,
           verified_at = ?, settled_at = ?
           WHERE id = ? AND status IN ('pending', 'claiming')""",
        (sol_tx, now, now, tx_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def reject_transaction(db_path: str, tx_id: int) -> bool:
    """Mark a transaction as rejected."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(db_path)
    cur = conn.execute(
        """UPDATE transactions SET status = 'rejected', verified_at = ?
           WHERE id = ? AND status = 'pending'""",
        (now, tx_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def get_most_recent_approved(db_path: str, email_from: str) -> Optional[dict]:
    """Return the most recently approved transaction from this sender."""
    conn = _connect(db_path)
    row = conn.execute(
        """SELECT * FROM transactions
           WHERE email_from = ? AND status = 'approved'
           ORDER BY settled_at DESC LIMIT 1""",
        (email_from,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all(db_path: str) -> list[dict]:
    """Return all transactions."""
    conn = _connect(db_path)
    rows = conn.execute("SELECT * FROM transactions ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats(db_path: str) -> dict:
    """Return summary stats: total volume, count, average size."""
    conn = _connect(db_path)
    row = conn.execute("""
        SELECT COUNT(*) as count,
               COALESCE(SUM(fiat_amount_cents), 0) as total_cents,
               COALESCE(AVG(fiat_amount_cents), 0) as avg_cents
        FROM transactions WHERE status = 'approved'
    """).fetchone()
    conn.close()
    return {
        "count": row["count"],
        "total_cents": row["total_cents"],
        "avg_cents": round(row["avg_cents"], 2),
    }
