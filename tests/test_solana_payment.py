"""Test real Solana payment signing and verification."""

from solders.keypair import Keypair

from mailpay.payment import sign_payment, verify_signature, verify_on_chain
from mailpay.models import Payment


def test_sign_payment_returns_valid_payment():
    kp = Keypair()
    payment = sign_payment(
        amount=50000,
        token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC on Solana
        network="solana",
        private_key=str(kp),
        recipient="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
    )
    assert payment.signature
    assert payment.amount == 50000
    assert payment.token == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    assert payment.network == "solana"
    assert payment.nonce
    assert payment.sender == str(kp.pubkey())


def test_verify_signature_valid():
    kp = Keypair()
    payment = sign_payment(
        amount=50000,
        token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        network="solana",
        private_key=str(kp),
        recipient="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
    )
    assert verify_signature(payment)


def test_verify_signature_tampered_amount():
    kp = Keypair()
    payment = sign_payment(
        amount=50000,
        token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        network="solana",
        private_key=str(kp),
        recipient="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
    )
    payment.amount = 99999  # tamper
    assert not verify_signature(payment)


def test_verify_signature_tampered_recipient():
    kp = Keypair()
    payment = sign_payment(
        amount=50000,
        token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        network="solana",
        private_key=str(kp),
        recipient="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
    )
    payment.recipient = "AttackerPubkeyHere1111111111111111111111111"
    assert not verify_signature(payment)


def test_sign_payment_different_keys_different_sigs():
    kp1 = Keypair()
    kp2 = Keypair()
    p1 = sign_payment(
        amount=50000,
        token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        network="solana",
        private_key=str(kp1),
        recipient="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
    )
    p2 = sign_payment(
        amount=50000,
        token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        network="solana",
        private_key=str(kp2),
        recipient="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
    )
    assert p1.signature != p2.signature
    assert p1.sender != p2.sender


def test_payment_header_roundtrip_with_sender():
    kp = Keypair()
    payment = sign_payment(
        amount=100000,
        token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        network="solana",
        private_key=str(kp),
        recipient="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
    )
    header = payment.to_header()
    parsed = Payment.from_header(header)
    assert parsed.amount == 100000
    assert parsed.sender == str(kp.pubkey())
    assert parsed.recipient == "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV"
    assert verify_signature(parsed)
