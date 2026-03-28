"""Test webhook handler message routing and OOPS responses."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# Import the handler module
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "demo"))
import webhook_handler as wh


@pytest.fixture
def mock_client():
    """Mock AgentMail client that captures replies."""
    client = MagicMock()
    replies = []

    def capture_reply(**kwargs):
        replies.append(kwargs)

    client.inboxes.threads.reply = capture_reply
    client._replies = replies
    return client


@pytest.fixture(autouse=True)
def patch_agentmail(mock_client):
    """Patch AgentMail() to return our mock."""
    with patch.object(wh, "AgentMail", return_value=mock_client):
        yield mock_client


def _payload(subject: str, text: str = "", from_addr: str = "alice@test.com") -> dict:
    """Build a minimal webhook payload."""
    return {
        "event_type": "message.received",
        "message": {
            "from_": from_addr,
            "subject": subject,
            "inbox_id": wh.INBOX,
            "thread_id": "thread-1",
            "text": text,
            "attachments": [],
        },
    }


# --- WHICH ---

def test_which_returns_methods(patch_agentmail):
    wh.process_email(_payload("WHICH"))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "METHODS"
    assert "METHODS |" in replies[0]["subject"]
    body = json.loads(replies[0]["text"])
    assert body["v"] == "0.1.0"
    assert body["type"] == "methods"
    assert len(body["rails"]) >= 1
    assert body["rails"][0]["wallet"] == wh.WALLET


def test_which_case_insensitive(patch_agentmail):
    wh.process_email(_payload("  which  "))
    assert len(patch_agentmail._replies) == 1
    assert patch_agentmail._replies[0]["headers"]["X-Envelopay-Type"] == "METHODS"


# --- INVOICE ---

def test_invoice_missing_wallet_returns_oops(patch_agentmail):
    wh.process_email(_payload("INVOICE", text="no json here"))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    assert "OOPS |" in replies[0]["subject"]
    body = json.loads(replies[0]["text"])
    assert body["type"] == "oops"
    assert body["error"]["code"] == "missing_wallet"


def test_invoice_invalid_wallet_returns_oops(patch_agentmail):
    # Too short
    wh.process_email(_payload("INVOICE", text='{"wallet": "abc"}'))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"


@patch.object(wh, "_get_balance", return_value=0)
def test_invoice_insufficient_funds_returns_oops(mock_bal, patch_agentmail):
    wallet = "6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif"
    wh.process_email(_payload("INVOICE", text=json.dumps({"wallet": wallet})))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    body = json.loads(replies[0]["text"])
    assert body["error"]["code"] == "insufficient_funds"


@patch.object(wh, "_refund", return_value={"tx": "abc123", "amount": 95000, "to": "someone"})
@patch.object(wh, "_get_balance", return_value=100000)
def test_invoice_success_returns_fulfill(mock_bal, mock_refund, patch_agentmail):
    wallet = "6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif"
    wh.process_email(_payload("INVOICE", text=json.dumps({"wallet": wallet})))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "FULFILL"
    body = json.loads(replies[0]["text"])
    assert body["type"] == "fulfill"
    assert body["v"] == "0.1.0"


# --- ORDER (replies with INVOICE) ---

def test_order_returns_invoice(patch_agentmail):
    wh.process_email(_payload("ORDER", text="do something"))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "INVOICE"
    assert "INVOICE |" in replies[0]["subject"]
    body = json.loads(replies[0]["text"])
    assert body["v"] == "0.1.0"
    assert body["type"] == "invoice"
    assert body["wallet"] == wh.WALLET
    assert "amount" in body
    assert body["chain"] == "solana"
    assert body["token"] == "SOL"


def test_order_with_json_includes_order_ref(patch_agentmail):
    order = json.dumps({"v": "0.1.0", "type": "order", "id": "ord_123",
                        "task": {"description": "Review PR #417"}})
    wh.process_email(_payload("ORDER", text=order))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    body = json.loads(replies[0]["text"])
    assert body["type"] == "invoice"
    assert body["order_ref"] == "ord_123"


# --- Self-skip ---

def test_skips_own_messages(patch_agentmail):
    wh.process_email(_payload("WHICH", from_addr=wh.INBOX))
    assert len(patch_agentmail._replies) == 0


# --- Lambda handler ---

def test_lambda_handler_returns_200(patch_agentmail):
    event = {"body": json.dumps(_payload("WHICH"))}
    result = wh.lambda_handler(event, None)
    assert result["statusCode"] == 200


def test_lambda_handler_ignores_non_message_events(patch_agentmail):
    event = {"body": json.dumps({"event_type": "inbox.created"})}
    result = wh.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert len(patch_agentmail._replies) == 0


# --- OOPS helper ---

def test_oops_helper_format(patch_agentmail):
    wh._oops(patch_agentmail, wh.INBOX, "thread-1", "Something broke", {"code": "test"})
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["subject"] == "OOPS | Something broke"
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    body = json.loads(replies[0]["text"])
    assert body == {"v": "0.1.0", "type": "oops", "note": "Something broke", "error": {"code": "test"}}


def test_oops_without_error_object(patch_agentmail):
    wh._oops(patch_agentmail, wh.INBOX, "thread-1", "Generic failure")
    body = json.loads(patch_agentmail._replies[0]["text"])
    assert "error" not in body
    assert body["note"] == "Generic failure"


# --- Protocol mismatch ---

def test_unknown_type_returns_oops(patch_agentmail):
    wh.process_email(_payload("HELLO"))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    body = json.loads(replies[0]["text"])
    assert body["error"]["code"] == "unknown_type"
    assert body["error"]["sent"] == "HELLO"
    assert "WHICH" in body["error"]["supported"]
    assert body["error"]["spec"] == "https://june.kim/certified-mail"


def test_unknown_type_with_pipe_returns_oops(patch_agentmail):
    wh.process_email(_payload("REVIEW | PR #417"))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "OOPS"
    body = json.loads(replies[0]["text"])
    assert body["error"]["sent"] == "REVIEW"


def test_known_types_not_caught_by_mismatch(patch_agentmail):
    """WHICH should route normally, not trigger the mismatch catch."""
    wh.process_email(_payload("WHICH"))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] == "METHODS"


def test_offer_not_caught_by_mismatch(patch_agentmail):
    """OFFER is a known type — should not trigger unknown_type OOPS."""
    wh.process_email(_payload("OFFER | 1 SOL for 30 USDC"))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    # Falls through to invoice handler, not OOPS
    assert replies[0]["headers"]["X-Envelopay-Type"] != "OOPS"


def test_accept_not_caught_by_mismatch(patch_agentmail):
    """ACCEPT is a known type — should not trigger unknown_type OOPS."""
    wh.process_email(_payload("ACCEPT | 30 USDC sent"))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    assert replies[0]["headers"]["X-Envelopay-Type"] != "OOPS"


def test_lowercase_subject_not_caught_by_mismatch(patch_agentmail):
    """Lowercase subjects aren't protocol attempts — fall through to invoice."""
    wh.process_email(_payload("hello there"))
    replies = patch_agentmail._replies
    assert len(replies) == 1
    # Should hit the invoice fallback, not OOPS
    assert replies[0]["headers"]["X-Envelopay-Type"] == "INVOICE"


# --- v and note on all responses ---

def test_all_responses_have_version_and_note(patch_agentmail):
    """Every reply body should contain v and note fields."""
    # WHICH → METHODS
    wh.process_email(_payload("WHICH"))
    body = json.loads(patch_agentmail._replies[-1]["text"])
    assert "v" in body and "note" in body

    # INVOICE with bad wallet → OOPS
    wh.process_email(_payload("INVOICE", text="garbage"))
    body = json.loads(patch_agentmail._replies[-1]["text"])
    assert "v" in body and "note" in body
