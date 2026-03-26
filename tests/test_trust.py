"""Test trust layer: attestations, exchange, curator."""

from mailpay.trust.models import Attestation, Confirmation, Revocation
from mailpay.trust.exchange import Exchange
from mailpay.trust.curator import (
    Curator, has_payment_history, has_min_endorsements,
    has_platform_rating, has_bilateral_edges,
)


def _stripe_attestation() -> Attestation:
    return Attestation(
        attestation_id="stripe_merchant123_2026",
        attestation_type="payment_processor",
        subject="merchant@example.com",
        attestor="attestations@stripe.com",
        timestamp="2026-03-18T15:00:00Z",
        standard_fields={"duration_years": 3, "status": "good_standing"},
        optional_fields={"dispute_rate": 0.002, "transaction_count": 14250},
        published_fields=["dispute_rate"],
    )


def _google_rating() -> Attestation:
    return Attestation(
        attestation_id="google_restaurant456_2026",
        attestation_type="platform_rating",
        subject="restaurant@example.com",
        attestor="attestations@google.com",
        timestamp="2026-03-18",
        standard_fields={"rating": 4.5, "review_count": 247, "platform": "Google Reviews"},
    )


# --- Attestation model tests ---

def test_attestation_serialization():
    att = _stripe_attestation()
    body = att.to_email_body()
    parsed = Attestation.from_email_body(body, attestor="attestations@stripe.com")
    assert parsed.attestation_id == "stripe_merchant123_2026"
    assert parsed.attestation_type == "payment_processor"
    assert parsed.subject == "merchant@example.com"
    assert parsed.standard_fields["duration_years"] == 3


def test_attestation_publishes_opted_fields_only():
    att = _stripe_attestation()
    body = att.to_email_body()
    import json
    data = json.loads(body)
    assert "dispute_rate" in data  # opted in
    assert "transaction_count" not in data  # not opted in


def test_confirmation_roundtrip():
    conf = Confirmation(
        attestation_id="stripe_merchant123_2026",
        confirmer="merchant@example.com",
    )
    body = conf.to_email_body()
    parsed = Confirmation.from_email_body(body, confirmer="merchant@example.com")
    assert parsed.attestation_id == "stripe_merchant123_2026"


def test_revocation_roundtrip():
    rev = Revocation(
        attestation_id="stripe_merchant123_2026",
        revoker="attestations@stripe.com",
        reason="account_closed",
        timestamp="2026-03-18T16:00:00Z",
    )
    body = rev.to_email_body()
    parsed = Revocation.from_email_body(body, revoker="attestations@stripe.com")
    assert parsed.reason == "account_closed"


# --- Exchange tests ---

def test_unilateral_creates_edge_immediately():
    ex = Exchange()
    att = _google_rating()
    edge = ex.submit_attestation(att)
    assert edge is not None
    assert not edge.bilateral
    assert edge.target == "restaurant@example.com"
    assert ex.edge_count == 1


def test_bilateral_requires_confirmation():
    ex = Exchange()
    att = _stripe_attestation()
    edge = ex.submit_attestation(att)
    assert edge is None  # bilateral type, needs confirmation
    assert ex.pending_count == 1
    assert ex.edge_count == 0

    conf = Confirmation(
        attestation_id="stripe_merchant123_2026",
        confirmer="merchant@example.com",
    )
    edge = ex.submit_confirmation(conf)
    assert edge is not None
    assert edge.bilateral
    assert ex.edge_count == 1


def test_self_confirmation_rejected():
    ex = Exchange()
    att = _stripe_attestation()
    ex.submit_attestation(att)

    conf = Confirmation(
        attestation_id="stripe_merchant123_2026",
        confirmer="attestations@stripe.com",  # attestor confirming themselves
    )
    edge = ex.submit_confirmation(conf)
    assert edge is None
    assert ex.edge_count == 0


def test_revocation_removes_edge():
    ex = Exchange()
    att = _stripe_attestation()
    ex.submit_attestation(att)
    conf = Confirmation(attestation_id="stripe_merchant123_2026", confirmer="merchant@example.com")
    ex.submit_confirmation(conf)
    assert ex.edge_count == 1

    rev = Revocation(
        attestation_id="stripe_merchant123_2026",
        revoker="attestations@stripe.com",
        reason="account_closed",
    )
    assert ex.submit_revocation(rev)
    assert ex.edge_count == 0


def test_revoked_attestation_cannot_be_resubmitted():
    ex = Exchange()
    att = _stripe_attestation()
    ex.submit_attestation(att)
    rev = Revocation(attestation_id="stripe_merchant123_2026", revoker="merchant@example.com")
    ex.submit_revocation(rev)

    edge = ex.submit_attestation(att)
    assert edge is None
    assert ex.edge_count == 0


def test_get_edges_for_node():
    ex = Exchange()
    att = _stripe_attestation()
    ex.submit_attestation(att)
    conf = Confirmation(attestation_id="stripe_merchant123_2026", confirmer="merchant@example.com")
    ex.submit_confirmation(conf)

    rating = _google_rating()
    # Make subject the same merchant for this test
    rating.subject = "merchant@example.com"
    rating.attestation_id = "google_merchant_2026"
    ex.submit_attestation(rating)

    edges = ex.get_edges("merchant@example.com")
    assert len(edges) == 2


# --- Curator tests ---

def test_curator_payment_history():
    ex = Exchange()
    att = _stripe_attestation()
    ex.submit_attestation(att)
    conf = Confirmation(attestation_id="stripe_merchant123_2026", confirmer="merchant@example.com")
    ex.submit_confirmation(conf)

    curator = Curator(name="commerce-verified")
    curator.require(has_payment_history(min_years=2))
    allowed = curator.evaluate(ex)
    assert "merchant@example.com" in allowed


def test_curator_rejects_insufficient_history():
    ex = Exchange()
    att = _stripe_attestation()
    att.standard_fields["duration_years"] = 0
    ex.submit_attestation(att)
    conf = Confirmation(attestation_id="stripe_merchant123_2026", confirmer="merchant@example.com")
    ex.submit_confirmation(conf)

    curator = Curator(name="strict")
    curator.require(has_payment_history(min_years=2))
    allowed = curator.evaluate(ex)
    assert "merchant@example.com" not in allowed


def test_curator_platform_rating():
    ex = Exchange()
    ex.submit_attestation(_google_rating())

    curator = Curator(name="quality")
    curator.require(has_platform_rating(min_rating=4.0))
    allowed = curator.evaluate(ex)
    assert "restaurant@example.com" in allowed


def test_curator_multiple_criteria():
    ex = Exchange()
    # Merchant has payment history
    att = _stripe_attestation()
    ex.submit_attestation(att)
    conf = Confirmation(attestation_id="stripe_merchant123_2026", confirmer="merchant@example.com")
    ex.submit_confirmation(conf)

    curator = Curator(name="strict")
    curator.require(has_payment_history(min_years=1))
    curator.require(has_bilateral_edges(min_count=1))
    allowed = curator.evaluate(ex)
    assert "merchant@example.com" in allowed

    # Add a criterion that fails
    curator.require(has_min_endorsements(count=5))
    allowed = curator.evaluate(ex)
    assert "merchant@example.com" not in allowed
