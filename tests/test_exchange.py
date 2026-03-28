"""Tests for the Cambio exchange handler."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from exchange import handler as xh
from exchange import config as xc
from exchange import db as xdb
from exchange import rate as xr


# --- Helpers ---

def _extract_json(text: str) -> dict:
    """Extract JSON from reply text that has a subject line prepended."""
    idx = text.index("{")
    return json.loads(text[idx:])


# --- Fixtures ---

@pytest.fixture
def mock_client():
    """Mock AgentMail client that captures sent messages."""
    client = MagicMock()
    replies = []

    def capture_send(**kwargs):
        replies.append(kwargs)

    client.inboxes.messages.send = capture_send
    client._replies = replies
    return client


@pytest.fixture(autouse=True)
def patch_agentmail(mock_client):
    """Patch AgentMail() to return our mock."""
    with patch.object(xh, "AgentMail", return_value=mock_client):
        yield mock_client


@pytest.fixture(autouse=True)
def ledger():
    """Use in-memory test ledger instead of GitHub API."""
    xdb._test_ledger_lines = []
    xdb._test_append_sink = []
    xdb._invalidate_cache()
    yield
    xdb._test_ledger_lines = None
    xdb._test_append_sink = None
    xdb._invalidate_cache()


@pytest.fixture(autouse=True)
def mock_rate():
    """Patch get_sol_usd_rate to return a fixed value everywhere it's imported."""
    with patch.object(xr, "get_sol_usd_rate", return_value=100.0), \
         patch.object(xh, "get_sol_usd_rate", return_value=100.0):
        yield


# db_path is unused now but kept for API compat
DB = "unused"


def _payload(subject: str, text: str = "", from_addr: str = "alice@test.com",
             message_id: str = "") -> dict:
    """Build a minimal webhook payload."""
    return {
        "event_type": "message.received",
        "message": {
            "id": message_id or "test-msg-id",
            "message_id": message_id or "test-msg-id",
            "from_": from_addr,
            "subject": subject,
            "inbox_id": xc.EXCHANGE_INBOX,
            "thread_id": "thread-1",
            "text": text,
            "attachments": [],
        },
    }


def _valid_offer(amount_cents: int = 200, wallet: str = "6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif") -> str:
    """Build a valid OFFER JSON body."""
    return json.dumps({
        "v": "0.1.0",
        "type": "offer",
        "id": "ofr_test",
        "give": {"amount": str(amount_cents), "token": "USD", "chain": "cashapp",
                 "proof": {"screenshot": "base64..."}},
        "want": {"amount": "1000000", "token": "SOL", "chain": "solana"},
        "wallet": wallet,
    })


# --- WHICH -> METHODS ---

def test_which_returns_methods(patch_agentmail):
    xh.process_email(_payload("WHICH"), db_path=DB)
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "METHODS"
    assert "METHODS |" in replies[0]["text"]
    # Extract JSON from reply text (subject prepended to body)
    text = replies[0]["text"]
    json_start = text.index("{")
    body = json.loads(text[json_start:])
    assert body["v"] == "0.1.0"
    assert body["type"] == "methods"
    # Should have CashApp and Venmo rails
    rails = body["rails"]
    assert len(rails) >= 2
    chain_names = [r["chain"] for r in rails]
    assert "cashapp" in chain_names
    assert "venmo" in chain_names
    # Rate info
    assert body["raw_rate"] == 100.0
    assert body["spread_rate"] == 130.0  # 100 * 1.3


# --- OFFER valid ---

def test_offer_valid_creates_pending(patch_agentmail):
    xh.process_email(_payload("OFFER | $2 for SOL", text=_valid_offer(200)), db_path=DB)
    replies = patch_agentmail._replies
    assert len(replies) == 1
    body = _extract_json(replies[0]["text"])
    assert body["error"]["code"] == "pending_verification"
    assert body["error"]["tx_id"] == 1
    # Check DB
    pending = xdb.get_pending(DB)
    assert len(pending) == 1
    assert pending[0]["fiat_amount_cents"] == 200
    assert pending[0]["status"] == "pending"
    assert pending[0]["wallet_address"] == "6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif"


# --- OFFER too high ---

def test_offer_amount_too_high_capped(patch_agentmail):
    """OFFER over $5 gets capped to $5, not rejected."""
    xh.process_email(_payload("OFFER | $10", text=_valid_offer(1000)), db_path=DB)
    pending = xdb.get_pending(DB)
    assert len(pending) == 1
    assert pending[0]["fiat_amount_cents"] == 500


# --- OFFER too low ---

def test_offer_amount_too_low(patch_agentmail):
    xh.process_email(_payload("OFFER | $0.50", text=_valid_offer(50)), db_path=DB)
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    body = _extract_json(replies[0]["text"])
    assert body["error"]["code"] == "amount_too_low"
    assert len(xdb.get_pending(DB)) == 0


# --- Unknown type ---

def test_unknown_type_returns_oops(patch_agentmail):
    xh.process_email(_payload("HELLO"), db_path=DB)
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    body = _extract_json(replies[0]["text"])
    assert body["error"]["code"] == "unknown_type"
    assert body["error"]["sent"] == "HELLO"
    assert "WHICH" in body["error"]["supported"]


# --- Self-skip ---

def test_skips_own_messages(patch_agentmail):
    xh.process_email(_payload("WHICH", from_addr=xc.EXCHANGE_INBOX), db_path=DB)
    assert len(patch_agentmail._replies) == 0


# --- Approve transaction ---

def test_approve_sends_sol_and_accept(patch_agentmail):
    # Create a pending transaction
    xh.process_email(_payload("OFFER | $2", text=_valid_offer(200)), db_path=DB)
    patch_agentmail._replies.clear()

    tx = xdb.get_pending(DB)[0]

    # Simulate SOL send
    with patch("exchange.handler.AgentMail", return_value=patch_agentmail), \
         patch.object(xh, "_get_last_message_info", return_value=("mock-msg-id", "alice@test.com")):
        xh.send_accept(
            thread_id=tx["thread_id"],
            offer_ref=str(tx["id"]),
            sol_tx="fake_sol_tx_hash",
            lamports=tx["sol_amount_lamports"],
            wallet=tx["wallet_address"],
        )

    # Mark approved in DB
    xdb.approve_transaction(DB, tx["id"], "fake_sol_tx_hash")

    # Check ACCEPT reply
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "ACCEPT"
    body = _extract_json(replies[0]["text"])
    assert body["type"] == "accept"
    assert body["proof"]["tx"] == "fake_sol_tx_hash"

    # Check DB
    updated = xdb.get_transaction(DB, tx["id"])
    assert updated["status"] == "approved"
    assert updated["sol_tx"] == "fake_sol_tx_hash"


# --- Reject transaction ---

def test_reject_sends_oops(patch_agentmail):
    # Create a pending transaction
    xh.process_email(_payload("OFFER | $3", text=_valid_offer(300)), db_path=DB)
    patch_agentmail._replies.clear()

    tx = xdb.get_pending(DB)[0]

    # Reject
    xdb.reject_transaction(DB, tx["id"])
    with patch("exchange.handler.AgentMail", return_value=patch_agentmail), \
         patch.object(xh, "_get_last_message_info", return_value=("mock-msg-id", "alice@test.com")):
        xh.send_reject(tx["thread_id"], "Payment not found in CashApp")

    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    body = _extract_json(replies[0]["text"])
    assert body["error"]["code"] == "rejected"

    # Check DB
    updated = xdb.get_transaction(DB, tx["id"])
    assert updated["status"] == "rejected"


# --- Rate with spread ---

def test_rate_spread_calculation():
    raw = 100.0
    spread = xr.apply_spread(raw, 0.30)
    assert spread == 130.0  # 100 * 1.3

    # $1 at spread rate of $130/SOL
    lamports = xr.usd_cents_to_lamports(100, 130.0)
    expected = int((1.0 / 130.0) * 1_000_000_000)
    assert lamports == expected


def test_rate_spread_zero():
    raw = 150.0
    spread = xr.apply_spread(raw, 0.0)
    assert spread == 150.0


# --- DB stats ---

def test_stats_empty():
    stats = xdb.get_stats(DB)
    assert stats["count"] == 0
    assert stats["total_cents"] == 0


def test_stats_with_approved():
    tx_id = xdb.create_transaction(
        db_path=DB, email_from="a@b.com",
        fiat_amount_cents=300, sol_amount_lamports=1000000,
        sol_rate=100.0, spread_rate=130.0,
        wallet_address="6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif",
        thread_id="t1",
    )
    xdb.approve_transaction(DB, tx_id, "tx_hash")
    stats = xdb.get_stats(DB)
    assert stats["count"] == 1
    assert stats["total_cents"] == 300
    assert stats["avg_cents"] == 300.0


# --- OFFER missing wallet ---

def test_offer_missing_wallet(patch_agentmail):
    body = json.dumps({
        "v": "0.1.0", "type": "offer",
        "give": {"amount": "200", "chain": "cashapp"},
        "want": {"amount": "1000000", "token": "SOL", "chain": "solana"},
        # no wallet
    })
    xh.process_email(_payload("OFFER | $2", text=body), db_path=DB)
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    jb = _extract_json(replies[0]["text"])
    assert jb["error"]["code"] == "missing_wallet"


# --- Non-protocol email ignored ---

def test_non_protocol_email_ignored(patch_agentmail):
    xh.process_email(_payload("hello there", text="just chatting"), db_path=DB)
    assert len(patch_agentmail._replies) == 0


# ===================================================================
# New tests for bug fixes
# ===================================================================

# --- Bug 1: Duplicate OFFER with same message_id is silently skipped ---

def test_duplicate_offer_same_message_id_skipped(patch_agentmail):
    """A second OFFER with the same message_id should be silently dropped."""
    offer_text = _valid_offer(200)
    p1 = _payload("OFFER | $2", text=offer_text, message_id="msg-abc-123")
    p2 = _payload("OFFER | $2", text=offer_text, message_id="msg-abc-123")

    xh.process_email(p1, db_path=DB)
    assert len(patch_agentmail._replies) == 1  # first gets a reply

    patch_agentmail._replies.clear()
    xh.process_email(p2, db_path=DB)
    assert len(patch_agentmail._replies) == 0  # duplicate: no reply

    # Only one row in DB
    pending = xdb.get_pending(DB)
    assert len(pending) == 1


# --- Bug 2: Approve on already-approved transaction fails gracefully ---

def test_approve_already_approved_fails():
    """approve_transaction returns False if the tx was already approved."""
    tx_id = xdb.create_transaction(
        db_path=DB, email_from="a@b.com",
        fiat_amount_cents=200, sol_amount_lamports=1000000,
        sol_rate=100.0, spread_rate=130.0,
        wallet_address="6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif",
        thread_id="t1",
    )
    # First approve succeeds
    assert xdb.approve_transaction(DB, tx_id, "tx_hash_1") is True

    # Second approve fails (already approved, not pending)
    assert xdb.approve_transaction(DB, tx_id, "tx_hash_2") is False

    # Status is still the first approval
    tx = xdb.get_transaction(DB, tx_id)
    assert tx["sol_tx"] == "tx_hash_1"


# --- Bug 4: OFFER when rate API fails returns OOPS ---

def test_offer_rate_failure_returns_oops(patch_agentmail):
    """When get_sol_usd_rate raises, OFFER should reply OOPS, not use a fake rate."""
    with patch.object(xh, "get_sol_usd_rate", side_effect=RuntimeError("API down")):
        xh.process_email(
            _payload("OFFER | $2", text=_valid_offer(200)),
            db_path=DB,
        )
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    body = _extract_json(replies[0]["text"])
    assert body["error"]["code"] == "rate_unavailable"
    # No transaction created
    assert len(xdb.get_pending(DB)) == 0


def test_which_rate_failure_returns_oops(patch_agentmail):
    """When get_sol_usd_rate raises, WHICH should reply OOPS too."""
    with patch.object(xh, "get_sol_usd_rate", side_effect=RuntimeError("API down")):
        xh.process_email(_payload("WHICH"), db_path=DB)
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    body = _extract_json(replies[0]["text"])
    assert body["error"]["code"] == "rate_unavailable"


# --- Bug 3: Webhook without secret returns 401 ---

def test_webhook_without_secret_returns_401():
    """lambda_handler rejects requests without the correct webhook secret."""
    with patch.object(xh, "WEBHOOK_SECRET", "my-secret-token"):
        # No secret header
        result = xh.lambda_handler({"headers": {}, "body": "{}"}, None)
        assert result["statusCode"] == 401

        # Wrong secret header
        result = xh.lambda_handler(
            {"headers": {"X-Webhook-Secret": "wrong"}, "body": "{}"},
            None,
        )
        assert result["statusCode"] == 401

        # Correct secret header
        result = xh.lambda_handler(
            {"headers": {"X-Webhook-Secret": "my-secret-token"}, "body": "{}"},
            None,
        )
        assert result["statusCode"] == 200


def test_webhook_no_secret_configured_allows_all():
    """When WEBHOOK_SECRET is empty, all requests are allowed."""
    with patch.object(xh, "WEBHOOK_SECRET", ""):
        result = xh.lambda_handler({"headers": {}, "body": "{}"}, None)
        assert result["statusCode"] == 200


# --- Invalid base58 wallet returns OOPS ---

def test_invalid_base58_wallet_returns_oops(patch_agentmail):
    """Wallet with invalid base58 characters should be rejected."""
    bad_wallet = "0OIl" + "a" * 40  # contains 0, O, I, l — all invalid base58
    offer = _valid_offer(200, wallet=bad_wallet)
    xh.process_email(_payload("OFFER | $2", text=offer), db_path=DB)
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    body = _extract_json(replies[0]["text"])
    assert body["error"]["code"] == "invalid_wallet"
    assert len(xdb.get_pending(DB)) == 0


# --- Multi-line JSON parsing ---

def test_multiline_json_parsing(patch_agentmail):
    """Pretty-printed JSON should be parsed correctly."""
    offer = json.dumps({
        "v": "0.1.0",
        "type": "offer",
        "give": {"amount": "200", "token": "USD", "chain": "cashapp",
                 "proof": {"screenshot": "base64..."}},
        "want": {"amount": "1000000", "token": "SOL", "chain": "solana"},
        "wallet": "6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif",
    }, indent=2)  # Multi-line!
    xh.process_email(_payload("OFFER | $2", text=offer), db_path=DB)
    replies = patch_agentmail._replies
    assert len(replies) == 1
    body = _extract_json(replies[0]["text"])
    assert body["error"]["code"] == "pending_verification"


# ===================================================================
# Payment notification auto-matching tests
# ===================================================================

def _create_pending_offer(amount_cents: int = 200,
                          wallet: str = "6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif",
                          thread_id: str = "thread-offer-1",
                          message_id: str = None) -> int:
    """Helper: insert a pending OFFER directly into the DB."""
    return xdb.create_transaction(
        db_path=DB,
        email_from="buyer@test.com",
        fiat_amount_cents=amount_cents,
        sol_amount_lamports=1_000_000,
        sol_rate=100.0,
        spread_rate=130.0,
        wallet_address=wallet,
        thread_id=thread_id,
        cashapp_or_venmo="cashapp",
        message_id=message_id,
    )


def _cashapp_notification(amount_str: str = "$2.00") -> dict:
    """Build a forwarded CashApp 'paid you' notification payload."""
    return _payload(
        subject=f"Fwd: Someone paid you {amount_str}",
        text=f"From: cash@square.com\nSomeone paid you {amount_str}",
        from_addr="forwarding@gmail.com",
        message_id="cashapp-notif-1",
    )


def _venmo_notification(amount_str: str = "$2.00") -> dict:
    """Build a forwarded Venmo 'paid you' notification payload."""
    return _payload(
        subject=f"Fwd: Someone paid you {amount_str}",
        text=f"From: venmo@venmo.com\nSomeone paid you {amount_str}",
        from_addr="forwarding@gmail.com",
        message_id="venmo-notif-1",
    )


def test_cashapp_notification_auto_approves(patch_agentmail):
    """Forwarded CashApp notification matches pending OFFER and auto-approves."""
    tx_id = _create_pending_offer(amount_cents=200, message_id="offer-msg-1")

    with patch.object(xh, "send_sol", return_value="fake_sol_tx_abc") as mock_sol, \
         patch.object(xh, "send_accept") as mock_accept:
        xh.process_email(_cashapp_notification("$2.00"), db_path=DB)

    mock_sol.assert_called_once_with(1_000_000, "6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif")
    mock_accept.assert_called_once_with(
        thread_id="thread-offer-1",
        offer_ref=str(tx_id),
        sol_tx="fake_sol_tx_abc",
        lamports=1_000_000,
        wallet="6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif",
        to_addr="buyer@test.com",
    )
    # DB should be approved
    tx = xdb.get_transaction(DB, tx_id)
    assert tx["status"] == "approved"
    assert tx["sol_tx"] == "fake_sol_tx_abc"


def test_venmo_notification_auto_approves(patch_agentmail):
    """Forwarded Venmo notification matches pending OFFER and auto-approves."""
    tx_id = xdb.create_transaction(
        db_path=DB,
        email_from="buyer@test.com",
        fiat_amount_cents=500,
        sol_amount_lamports=1_000_000,
        sol_rate=100.0,
        spread_rate=130.0,
        wallet_address="6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif",
        thread_id="thread-offer-1",
        cashapp_or_venmo="venmo",
        message_id="offer-msg-2",
    )

    with patch.object(xh, "send_sol", return_value="fake_sol_tx_venmo") as mock_sol, \
         patch.object(xh, "send_accept") as mock_accept:
        xh.process_email(_venmo_notification("$5.00"), db_path=DB)

    mock_sol.assert_called_once()
    mock_accept.assert_called_once()
    tx = xdb.get_transaction(DB, tx_id)
    assert tx["status"] == "approved"
    assert tx["sol_tx"] == "fake_sol_tx_venmo"


def test_payment_notification_no_match_ignored(patch_agentmail):
    """Payment notification with no matching pending OFFER is ignored."""
    # No pending OFFERs in DB
    with patch.object(xh, "send_sol") as mock_sol, \
         patch.object(xh, "send_accept") as mock_accept:
        xh.process_email(_cashapp_notification("$2.00"), db_path=DB)

    mock_sol.assert_not_called()
    mock_accept.assert_not_called()
    assert len(patch_agentmail._replies) == 0


def test_payment_notification_underpayment_no_match(patch_agentmail):
    """Payment less than the pending OFFER doesn't match."""
    _create_pending_offer(amount_cents=500, message_id="offer-msg-3")

    with patch.object(xh, "send_sol") as mock_sol, \
         patch.object(xh, "send_accept") as mock_accept:
        # Notification is $3.00 but pending OFFER is $5.00
        xh.process_email(_cashapp_notification("$3.00"), db_path=DB)

    mock_sol.assert_not_called()
    mock_accept.assert_not_called()
    pending = xdb.get_pending(DB)
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"


def test_payment_notification_overpayment_matches(patch_agentmail):
    """Payment more than the pending OFFER still matches — we cap dispensing."""
    _create_pending_offer(amount_cents=200, message_id="offer-msg-overpay")

    with patch.object(xh, "send_sol", return_value="tx_overpay") as mock_sol, \
         patch.object(xh, "send_accept"):
        xh.process_email(_cashapp_notification("$10.00"), db_path=DB)

    mock_sol.assert_called_once()


def test_payment_notification_fifo_oldest_matched(patch_agentmail):
    """Multiple pending OFFERs: oldest matching amount gets filled (FIFO)."""
    tx_id_1 = _create_pending_offer(amount_cents=200, thread_id="thread-old",
                                     message_id="offer-old")
    tx_id_2 = _create_pending_offer(amount_cents=200, thread_id="thread-new",
                                     message_id="offer-new")

    with patch.object(xh, "send_sol", return_value="fake_sol_fifo") as mock_sol, \
         patch.object(xh, "send_accept") as mock_accept:
        xh.process_email(_cashapp_notification("$2.00"), db_path=DB)

    # Should match the oldest (tx_id_1)
    mock_accept.assert_called_once()
    call_kwargs = mock_accept.call_args
    assert call_kwargs.kwargs["thread_id"] == "thread-old"
    assert call_kwargs.kwargs["offer_ref"] == str(tx_id_1)
    assert call_kwargs.kwargs["to_addr"] == "buyer@test.com"

    # tx_id_1 approved, tx_id_2 still pending
    assert xdb.get_transaction(DB, tx_id_1)["status"] == "approved"
    assert xdb.get_transaction(DB, tx_id_2)["status"] == "pending"


# ===================================================================
# Bug fix regression tests
# ===================================================================

# --- Bug 1: Claim prevents double-pay ---

def test_claim_prevents_double_pay(patch_agentmail):
    """Two concurrent payment notifications for the same OFFER: only one sends SOL."""
    tx_id = _create_pending_offer(amount_cents=200, message_id="offer-race-1")

    sol_calls = []

    def tracking_send_sol(lamports, wallet):
        sol_calls.append((lamports, wallet))
        return "sol_tx_from_caller"

    notif1 = _cashapp_notification("$2.00")
    notif1["message"]["message_id"] = "notif-race-1"
    notif1["message"]["id"] = "notif-race-1"
    notif2 = _cashapp_notification("$2.00")
    notif2["message"]["message_id"] = "notif-race-2"
    notif2["message"]["id"] = "notif-race-2"

    with patch.object(xh, "send_sol", side_effect=tracking_send_sol), \
         patch.object(xh, "send_accept"):
        xh.process_email(notif1, db_path=DB)
        xh.process_email(notif2, db_path=DB)

    # Only one SOL send should have happened
    assert len(sol_calls) == 1
    tx = xdb.get_transaction(DB, tx_id)
    assert tx["status"] == "approved"


# --- Bug 3: ACCEPT goes to the original sender, not self ---

def test_accept_goes_to_original_sender(patch_agentmail):
    """send_accept uses to_addr parameter, not thread lookup which might be self."""
    tx_id = _create_pending_offer(amount_cents=200, message_id="offer-accept-1")

    # Mock _get_last_message_info to return OUR address (simulating the OOPS ack being last)
    with patch("exchange.handler.AgentMail", return_value=patch_agentmail), \
         patch.object(xh, "_get_last_message_info",
                      return_value=("mock-msg-id", xc.EXCHANGE_INBOX)):
        xh.send_accept(
            thread_id="thread-offer-1",
            offer_ref=str(tx_id),
            sol_tx="fake_tx",
            lamports=1_000_000,
            wallet="6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif",
            to_addr="buyer@test.com",  # explicit — should override thread lookup
        )

    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["to"] == "buyer@test.com"  # NOT our inbox


def test_accept_falls_back_to_thread_lookup(patch_agentmail):
    """When to_addr is not provided, send_accept falls back to thread lookup."""
    with patch("exchange.handler.AgentMail", return_value=patch_agentmail), \
         patch.object(xh, "_get_last_message_info",
                      return_value=("mock-msg-id", "alice@test.com")):
        xh.send_accept(
            thread_id="thread-1",
            offer_ref="1",
            sol_tx="fake_tx",
            lamports=1_000_000,
            wallet="6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif",
        )

    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["to"] == "alice@test.com"


# --- Bug 4: PAY with sufficient amount unbans ---

def _pay_payload(amount_cents: int, from_addr: str = "baduser@test.com") -> dict:
    """Build a PAY message payload."""
    body = json.dumps({
        "v": "0.1.0",
        "type": "pay",
        "give": {"amount": str(amount_cents), "token": "USD", "chain": "cashapp"},
    })
    return _payload("PAY | settling debt", text=body, from_addr=from_addr)


def test_pay_sufficient_amount_unbans(patch_agentmail):
    """PAY with amount >= owed unbans the user."""
    xdb.ban_email(DB, "baduser@test.com", "reversal", amount_owed_cents=300)
    assert xdb.is_banned(DB, "baduser@test.com")

    xh.process_email(_pay_payload(300), db_path=DB)

    assert not xdb.is_banned(DB, "baduser@test.com")
    replies = patch_agentmail._replies
    assert len(replies) == 1
    body = _extract_json(replies[0]["text"])
    assert body["error"]["code"] == "unbanned"


def test_pay_insufficient_amount_stays_banned(patch_agentmail):
    """PAY with amount < owed keeps the user banned."""
    xdb.ban_email(DB, "baduser@test.com", "reversal", amount_owed_cents=500)
    assert xdb.is_banned(DB, "baduser@test.com")

    xh.process_email(_pay_payload(200), db_path=DB)

    # Still banned
    assert xdb.is_banned(DB, "baduser@test.com")
    replies = patch_agentmail._replies
    assert len(replies) == 1
    body = _extract_json(replies[0]["text"])
    assert body["error"]["code"] == "insufficient_pay"
    assert body["error"]["owed_cents"] == 500
    assert body["error"]["sent_cents"] == 200


def test_pay_overpayment_unbans(patch_agentmail):
    """PAY with amount > owed also unbans (overpayment is fine)."""
    xdb.ban_email(DB, "baduser@test.com", "reversal", amount_owed_cents=200)

    xh.process_email(_pay_payload(500), db_path=DB)

    assert not xdb.is_banned(DB, "baduser@test.com")
    replies = patch_agentmail._replies
    body = _extract_json(replies[0]["text"])
    assert body["error"]["code"] == "unbanned"
