"""Test agent task dispatch without network."""

from solders.keypair import Keypair

from mailpay.agent import Agent
from mailpay.models import PaymentEmail, Payment
from mailpay.payment import sign_payment, USDC_MINT


def _make_agent() -> Agent:
    agent = Agent(
        email_addr="bot@test.com",
        imap_host="localhost",
        smtp_host="localhost",
        price=50000,
        token=USDC_MINT,
        network="solana",
    )

    @agent.handle("ping")
    def ping(task):
        return {"pong": True}

    @agent.handle("echo")
    def echo(task):
        return {"echo": task.get("text", "")}

    return agent


def test_process_with_payment():
    agent = _make_agent()
    kp = Keypair()
    payment = sign_payment(
        amount=50000,
        token=USDC_MINT,
        network="solana",
        private_key=str(kp),
        recipient="bot@test.com",
    )
    email = PaymentEmail(
        from_addr="alice@alice.dev",
        to_addr="bot@test.com",
        task={"task": "ping"},
        subject="Ping",
        message_id="<123@alice.dev>",
        payment=payment,
    )

    reply = agent.process(email)
    assert reply is not None
    assert reply.task == {"pong": True}
    assert reply.to_addr == "alice@alice.dev"
    assert reply.in_reply_to == "<123@alice.dev>"
    assert reply.payment_response["status"] == "verified"


def test_process_rejects_nonce_replay():
    agent = _make_agent()
    kp = Keypair()
    payment = sign_payment(
        amount=50000,
        token=USDC_MINT,
        network="solana",
        private_key=str(kp),
        recipient="bot@test.com",
    )
    email1 = PaymentEmail(
        from_addr="alice@alice.dev",
        to_addr="bot@test.com",
        task={"task": "ping"},
        subject="Ping",
        message_id="<1@alice.dev>",
        payment=payment,
    )
    email2 = PaymentEmail(
        from_addr="alice@alice.dev",
        to_addr="bot@test.com",
        task={"task": "ping"},
        subject="Ping",
        message_id="<2@alice.dev>",
        payment=payment,  # same payment = same nonce
    )

    reply1 = agent.process(email1)
    assert reply1 is not None
    assert reply1.task == {"pong": True}

    reply2 = agent.process(email2)
    assert reply2 is not None
    assert reply2.task == {"error": "nonce already used"}


def test_process_without_payment_returns_402():
    agent = _make_agent()
    email = PaymentEmail(
        from_addr="alice@alice.dev",
        to_addr="bot@test.com",
        task={"task": "ping"},
        subject="Ping",
    )

    reply = agent.process(email)
    assert reply is not None
    assert reply.payment_required is not None
    assert reply.payment_required.max_amount == 50000


def test_process_unknown_task():
    agent = _make_agent()
    email = PaymentEmail(
        from_addr="alice@alice.dev",
        to_addr="bot@test.com",
        task={"task": "unknown"},
    )

    reply = agent.process(email)
    assert reply is None


def test_process_free_agent():
    agent = Agent(
        email_addr="free@test.com",
        imap_host="localhost",
        smtp_host="localhost",
        price=0,
    )

    @agent.handle("ping")
    def ping(task):
        return {"pong": True}

    email = PaymentEmail(
        from_addr="alice@alice.dev",
        to_addr="free@test.com",
        task={"task": "ping"},
    )

    reply = agent.process(email)
    assert reply is not None
    assert reply.task == {"pong": True}
    assert reply.payment_response == {}
