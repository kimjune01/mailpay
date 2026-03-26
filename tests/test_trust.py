"""Test trust layer: attestations, exchange, curator."""

from envelopay.trust.models import Attestation, Confirmation, Revocation, canonicalize_email
from envelopay.trust.exchange import Exchange
from envelopay.trust.curator import (
    Curator, has_payment_history, has_min_endorsements,
    has_platform_rating, has_bilateral_edges,
)


# --- Canonicalization tests ---

def test_canonicalize_lowercase():
    assert canonicalize_email("Alice@Gmail.com") == "alice@gmail.com"

def test_canonicalize_gmail_dots():
    assert canonicalize_email("a.l.i.c.e@gmail.com") == "alice@gmail.com"

def test_canonicalize_gmail_dots_and_case():
    assert canonicalize_email("A.Li.Ce@GMAIL.COM") == "alice@gmail.com"

def test_canonicalize_strips_plus_suffix():
    assert canonicalize_email("alice+promo@gmail.com") == "alice@gmail.com"

def test_canonicalize_preserves_plus_agent():
    assert canonicalize_email("alice+agent@gmail.com") == "alice+agent@gmail.com"

def test_canonicalize_non_gmail_keeps_dots():
    assert canonicalize_email("first.last@company.com") == "first.last@company.com"

def test_canonicalize_non_gmail_strips_plus():
    assert canonicalize_email("bob+tag@company.com") == "bob@company.com"

def test_canonicalize_non_gmail_preserves_plus_agent():
    assert canonicalize_email("bob+agent@company.com") == "bob+agent@company.com"

def test_canonicalize_googlemail():
    assert canonicalize_email("a.lice+spam@googlemail.com") == "alice@googlemail.com"


def test_exchange_canonicalizes_on_ingestion():
    """Attestation from A.lice@Gmail.com and alice@gmail.com should be the same node."""
    ex = Exchange()
    att = Attestation(
        attestation_id="canon_test_2026",
        attestation_type="payment_processor",
        subject="A.Li.Ce@Gmail.com",
        attestor="attestations@stripe.com",
        timestamp="2026-03-25",
        standard_fields={"duration_years": 1},
    )
    ex.submit_attestation(att)
    conf = Confirmation(attestation_id="canon_test_2026", confirmer="alice@gmail.com")
    edges = ex.submit_confirmation(conf)
    assert len(edges) == 2

    # Query with any variant should find the edges
    assert len(ex.get_edges("a.l.i.c.e@gmail.com")) == 2
    assert len(ex.get_edges("ALICE@GMAIL.COM")) == 2


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


# --- Model tests ---

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
    edges = ex.submit_attestation(att)
    assert len(edges) == 1
    assert edges[0].kind == "unilateral"
    assert edges[0].to_addr == "restaurant@example.com"
    assert edges[0].from_addr == "attestations@google.com"
    assert ex.edge_count == 1


def test_bilateral_requires_confirmation():
    ex = Exchange()
    att = _stripe_attestation()
    edges = ex.submit_attestation(att)
    assert len(edges) == 0  # bilateral, needs confirmation
    assert ex.edge_count == 0

    conf = Confirmation(
        attestation_id="stripe_merchant123_2026",
        confirmer="merchant@example.com",
    )
    edges = ex.submit_confirmation(conf)
    assert len(edges) == 2  # two directed edges
    assert ex.edge_count == 2
    addrs = {(e.from_addr, e.to_addr) for e in edges}
    assert ("attestations@stripe.com", "merchant@example.com") in addrs
    assert ("merchant@example.com", "attestations@stripe.com") in addrs


def test_self_confirmation_rejected():
    ex = Exchange()
    att = _stripe_attestation()
    ex.submit_attestation(att)

    # Attestor confirming themselves
    conf = Confirmation(
        attestation_id="stripe_merchant123_2026",
        confirmer="attestations@stripe.com",
    )
    edges = ex.submit_confirmation(conf)
    assert len(edges) == 0
    assert ex.edge_count == 0


def test_duplicate_attestation_id_rejected():
    ex = Exchange()
    att = _stripe_attestation()
    ex.submit_attestation(att)
    edges = ex.submit_attestation(att)  # duplicate
    assert len(edges) == 0


def test_revocation_removes_edges():
    ex = Exchange()
    att = _stripe_attestation()
    ex.submit_attestation(att)
    conf = Confirmation(attestation_id="stripe_merchant123_2026", confirmer="merchant@example.com")
    ex.submit_confirmation(conf)
    assert ex.edge_count == 2

    rev = Revocation(
        attestation_id="stripe_merchant123_2026",
        revoker="attestations@stripe.com",
        reason="account_closed",
    )
    assert ex.submit_revocation(rev)
    assert ex.edge_count == 0


def test_get_edges_for_domain():
    ex = Exchange()
    att = _stripe_attestation()
    ex.submit_attestation(att)
    conf = Confirmation(attestation_id="stripe_merchant123_2026", confirmer="merchant@example.com")
    ex.submit_confirmation(conf)

    rating = _google_rating()
    rating.subject = "merchant@example.com"
    rating.attestation_id = "google_merchant_2026"
    ex.submit_attestation(rating)

    edges = ex.get_edges("merchant@example.com")
    assert len(edges) == 3  # 2 bilateral + 1 unilateral


def test_get_log():
    ex = Exchange()
    ex.submit_attestation(_stripe_attestation())
    conf = Confirmation(attestation_id="stripe_merchant123_2026", confirmer="merchant@example.com")
    ex.submit_confirmation(conf)

    log = ex.get_log()
    assert len(log) == 2
    assert log[0]["action"] == "attestation"
    assert log[1]["action"] == "confirm"


def test_get_attestation():
    ex = Exchange()
    ex.submit_attestation(_stripe_attestation())
    att = ex.get_attestation("stripe_merchant123_2026")
    assert att is not None
    assert att.attestor == "attestations@stripe.com"


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


def test_license_is_unilateral():
    ex = Exchange()
    att = Attestation(
        attestation_id="license_plumber_2026",
        attestation_type="license",
        subject="plumber@example.com",
        attestor="registry@state.gov",
        timestamp="2026-01-01",
        standard_fields={"license_type": "plumbing", "jurisdiction": "OR"},
    )
    edges = ex.submit_attestation(att)
    assert len(edges) == 1
    assert edges[0].kind == "unilateral"
