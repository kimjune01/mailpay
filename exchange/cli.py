"""Simple CLI for the exchange operator."""

from __future__ import annotations

import argparse
import os
import sys

from exchange.db import (
    approve_transaction,
    claim_transaction,
    get_all,
    get_pending,
    get_stats,
    get_transaction,
    init_db,
    reject_transaction,
    unban_email,
)
from exchange.handler import send_accept, send_reject
from exchange.settle import send_sol

# Absolute DB path — same as handler.py
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "exchange.db")
DB_PATH = os.path.normpath(DB_PATH)


def cmd_pending(args: argparse.Namespace) -> None:
    """List pending transactions."""
    init_db(DB_PATH)
    rows = get_pending(DB_PATH)
    if not rows:
        print("No pending transactions.")
        return
    for r in rows:
        print(f"  #{r['id']}  from={r['email_from']}  "
              f"rail={r['cashapp_or_venmo'] or '?'}  "
              f"fiat=${r['fiat_amount_cents']/100:.2f}  "
              f"sol={r['sol_amount_lamports']} lamports  "
              f"rate={r['spread_rate']:.2f}  "
              f"wallet={r['wallet_address']}  "
              f"proof={r['payment_proof'] or 'none'}  "
              f"({r['created_at']})")


def cmd_approve(args: argparse.Namespace) -> None:
    """Approve a pending transaction: send SOL, reply ACCEPT."""
    init_db(DB_PATH)
    tx = get_transaction(DB_PATH, args.id)
    if not tx:
        print(f"Transaction #{args.id} not found.")
        sys.exit(1)

    # Atomic claim: UPDATE WHERE status='pending' and check rowcount
    # We pass a placeholder sol_tx first to claim the row, then update with real tx.
    # Actually, we need to send SOL first. So we do the atomic claim *before* sending.
    # Use a two-phase approach: claim with a placeholder, send SOL, then update with real hash.
    # Simpler: just attempt the atomic approve. If it fails, someone else got it.
    # But we need the SOL tx hash for the approve call...
    #
    # Solution: atomically move status to 'claiming' first, send SOL, then to 'approved'.
    # For now, use the approve_transaction atomic check: if it returns False, abort.

    # Two-phase claim: atomically move pending -> claiming before sending SOL
    if not claim_transaction(DB_PATH, args.id):
        print(f"Transaction #{args.id} is {tx['status']}, not pending. Already claimed.")
        sys.exit(1)

    # Send SOL (safe — only one caller can reach here per tx)
    print(f"Sending {tx['sol_amount_lamports']} lamports to {tx['wallet_address']}...")
    sol_tx = send_sol(tx["sol_amount_lamports"], tx["wallet_address"])
    print(f"TX: {sol_tx}")

    # Move claiming -> approved
    approve_transaction(DB_PATH, args.id, sol_tx)

    # Reply ACCEPT — use email_from from DB, not thread lookup
    send_accept(
        thread_id=tx["thread_id"],
        offer_ref=str(tx["id"]),
        sol_tx=sol_tx,
        lamports=tx["sol_amount_lamports"],
        wallet=tx["wallet_address"],
        to_addr=tx["email_from"],
    )
    print(f"Approved #{args.id}. ACCEPT sent.")


def cmd_reject(args: argparse.Namespace) -> None:
    """Reject a pending transaction: reply OOPS."""
    init_db(DB_PATH)
    tx = get_transaction(DB_PATH, args.id)
    if not tx:
        print(f"Transaction #{args.id} not found.")
        sys.exit(1)
    if tx["status"] != "pending":
        print(f"Transaction #{args.id} is {tx['status']}, not pending.")
        sys.exit(1)

    reject_transaction(DB_PATH, args.id)
    send_reject(tx["thread_id"], args.reason)
    print(f"Rejected #{args.id}. OOPS sent.")


def cmd_stats(args: argparse.Namespace) -> None:
    """Show exchange stats."""
    init_db(DB_PATH)
    s = get_stats(DB_PATH)
    print(f"Approved transactions: {s['count']}")
    print(f"Total volume: ${s['total_cents']/100:.2f}")
    print(f"Average size: ${s['avg_cents']/100:.2f}")
    all_tx = get_all(DB_PATH)
    pending = sum(1 for t in all_tx if t["status"] == "pending")
    rejected = sum(1 for t in all_tx if t["status"] == "rejected")
    print(f"Pending: {pending}")
    print(f"Rejected: {rejected}")


def cmd_unban(args: argparse.Namespace) -> None:
    """Lift a ban on an email address."""
    init_db(DB_PATH)
    if unban_email(DB_PATH, args.email):
        print(f"Unbanned {args.email}.")
    else:
        print(f"{args.email} was not banned.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cambio exchange operator CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("pending", help="List pending transactions")

    ap = sub.add_parser("approve", help="Approve a transaction")
    ap.add_argument("id", type=int, help="Transaction ID")

    rj = sub.add_parser("reject", help="Reject a transaction")
    rj.add_argument("id", type=int, help="Transaction ID")
    rj.add_argument("reason", type=str, help="Rejection reason")

    sub.add_parser("stats", help="Show exchange stats")

    ub = sub.add_parser("unban", help="Lift a ban on an email")
    ub.add_argument("email", type=str, help="Email address to unban")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {
        "pending": cmd_pending,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "stats": cmd_stats,
        "unban": cmd_unban,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
