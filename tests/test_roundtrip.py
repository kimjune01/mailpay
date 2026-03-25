"""Test compose → parse roundtrip without network."""

from mailpay.models import PaymentEmail
from mailpay.send import compose
from mailpay.receive import parse_email


def test_compose_and_parse_with_payment():
    email = PaymentEmail(
        from_addr="alice@alice.dev",
        to_addr="bob@bob.cc",
        task={"task": "code_review", "repo": "https://github.com/alice/widget"},
        body_text="Review my code please.",
        payment_amount=50000,
        payment_token="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        payment_network="base",
        wallet_key="0xdeadbeef",
    )

    msg = compose(email)
    raw = msg.as_bytes()

    parsed = parse_email(raw)
    assert parsed.from_addr == "alice@alice.dev"
    assert parsed.to_addr == "bob@bob.cc"
    assert parsed.task["task"] == "code_review"
    assert parsed.has_payment
    assert parsed.payment.amount == 50000
    assert parsed.payment.token == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    assert parsed.payment.signature.startswith("0x")
    assert parsed.body_text.strip() == "Review my code please."


def test_compose_with_payment_link_fallback():
    email = PaymentEmail(
        from_addr="alice@alice.dev",
        to_addr="legacy@old.com",
        task={"task": "translate", "text": "Hello world"},
        payment_link="https://checkout.stripe.com/pay?amount=0.05",
    )

    msg = compose(email)
    raw = msg.as_bytes()

    parsed = parse_email(raw)
    assert not parsed.has_payment
    assert parsed.payment_link == "https://checkout.stripe.com/pay?amount=0.05"
    assert parsed.task["task"] == "translate"


def test_compose_without_payment():
    email = PaymentEmail(
        from_addr="alice@alice.dev",
        to_addr="bob@bob.cc",
        task={"task": "ping"},
        body_text="Are you there?",
    )

    msg = compose(email)
    raw = msg.as_bytes()

    parsed = parse_email(raw)
    assert not parsed.has_payment
    assert not parsed.has_payment_link
    assert parsed.task["task"] == "ping"


def test_payment_header_roundtrip():
    from mailpay.models import Payment

    payment = Payment(
        signature="0xabc123",
        amount=100000,
        token="0xUSDC",
        network="base",
        nonce="deadbeef",
    )

    header = payment.to_header()
    parsed = Payment.from_header(header)

    assert parsed.signature == "0xabc123"
    assert parsed.amount == 100000
    assert parsed.token == "0xUSDC"
    assert parsed.nonce == "deadbeef"


def test_payment_required_roundtrip():
    from mailpay.models import PaymentRequired

    req = PaymentRequired(
        scheme="exact",
        network="base",
        max_amount=50000,
        token="0xUSDC",
        resource="agent://review",
        description="code review",
    )

    header = req.to_header()
    parsed = PaymentRequired.from_header(header)

    assert parsed.scheme == "exact"
    assert parsed.max_amount == 50000
    assert parsed.token == "0xUSDC"
    assert parsed.description == "code review"
