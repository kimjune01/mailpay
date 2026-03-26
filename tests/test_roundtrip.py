"""Test compose → parse roundtrip without network."""

from solders.keypair import Keypair

from mailpay.models import PaymentEmail
from mailpay.payment import USDC_MINT
from mailpay.send import compose
from mailpay.receive import parse_email


def test_compose_and_parse_with_payment():
    kp = Keypair()
    email = PaymentEmail(
        from_addr="alice@alice.dev",
        to_addr="bob@bob.cc",
        task={"task": "code_review", "repo": "https://github.com/alice/widget"},
        body_text="Review my code please.",
        payment_amount=50000,
        payment_token=USDC_MINT,
        payment_network="solana",
        wallet_key=str(kp),
    )

    msg = compose(email)
    raw = msg.as_bytes()

    parsed = parse_email(raw)
    assert parsed.from_addr == "alice@alice.dev"
    assert parsed.to_addr == "bob@bob.cc"
    assert parsed.task["task"] == "code_review"
    assert parsed.has_payment
    assert parsed.payment.amount == 50000
    assert parsed.payment.token == USDC_MINT
    assert len(parsed.payment.signature) > 0  # base58 Solana signature
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
        signature="abc123sig",
        amount=100000,
        token=USDC_MINT,
        network="solana",
        nonce="deadbeef",
        tx_hash="5wHGS...",
        sender="SenderPubkey111",
        recipient="RecipientPubkey222",
    )

    header = payment.to_header()
    parsed = Payment.from_header(header)

    assert parsed.signature == "abc123sig"
    assert parsed.amount == 100000
    assert parsed.token == USDC_MINT
    assert parsed.network == "solana"
    assert parsed.nonce == "deadbeef"
    assert parsed.tx_hash == "5wHGS..."
    assert parsed.sender == "SenderPubkey111"
    assert parsed.recipient == "RecipientPubkey222"


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
