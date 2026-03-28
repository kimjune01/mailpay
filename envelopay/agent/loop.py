"""Minimal agent loop: poll IMAP, dispatch tasks, reply with results."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable

from envelopay.core.models import PaymentEmail, PaymentRequired
from envelopay.core.payment import verify_signature
from envelopay.core.receive import receive
from envelopay.core.send import compose

import smtplib


# Type for task handler: takes a task dict, returns a result dict
TaskHandler = Callable[[dict], dict]


class _NonceStore:
    """Persistent nonce store backed by a JSON file."""

    def __init__(self, path: str):
        self._path = path
        self._nonces: set[str] = set()
        self._load()

    def _load(self) -> None:
        if os.path.exists(self._path):
            with open(self._path) as f:
                self._nonces = set(json.load(f))

    def _save(self) -> None:
        if not self._path:
            return
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        temp = f"{self._path}.tmp"
        with open(temp, "w") as f:
            json.dump(sorted(self._nonces), f)
        os.replace(temp, self._path)

    def seen(self, key: str) -> bool:
        return key in self._nonces

    def add(self, key: str) -> None:
        self._nonces.add(key)
        self._save()


class _BudgetTracker:
    """Track spending per hour. Reject when exceeded."""

    def __init__(self, max_per_hour: int):
        self.max_per_hour = max_per_hour  # in token units (e.g. USDC micros)
        self._ledger: list[tuple[float, int]] = []  # (timestamp, amount)

    def _prune(self) -> None:
        cutoff = time.time() - 3600
        self._ledger = [(t, a) for t, a in self._ledger if t > cutoff]

    def spent_this_hour(self) -> int:
        self._prune()
        return sum(a for _, a in self._ledger)

    def can_spend(self, amount: int) -> bool:
        if self.max_per_hour <= 0:
            return True
        return self.spent_this_hour() + amount <= self.max_per_hour

    def record(self, amount: int) -> None:
        self._ledger.append((time.time(), amount))


class Agent:
    """A paid email agent that polls for tasks and replies with results.

    Usage:
        agent = Agent(
            email_addr="review-agent@codereviews.cc",
            imap_host="imap.codereviews.cc",
            smtp_host="smtp.codereviews.cc",
            price=50000,  # 0.05 USDC
        )

        @agent.handle("code_review")
        def review(task):
            return {"result": "pass", "findings": []}

        agent.run()
    """

    def __init__(
        self,
        email_addr: str,
        imap_host: str,
        smtp_host: str,
        imap_port: int = 993,
        smtp_port: int = 587,
        imap_user: str = "",
        imap_pass: str = "",
        smtp_user: str = "",
        smtp_pass: str = "",
        price: int = 0,
        token: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        network: str = "solana",
        poll_interval: int = 10,
        nonce_file: str = "",
        handler_timeout: float = 30.0,
        max_spend_per_hour: int = 0,
    ):
        self.email_addr = email_addr
        self.imap_host = imap_host
        self.smtp_host = smtp_host
        self.imap_port = imap_port
        self.smtp_port = smtp_port
        self.imap_user = imap_user or email_addr
        self.imap_pass = imap_pass
        self.smtp_user = smtp_user or email_addr
        self.smtp_pass = smtp_pass
        self.price = price
        self.token = token
        self.network = network
        self.poll_interval = poll_interval
        self.handler_timeout = handler_timeout
        self._handlers: dict[str, TaskHandler] = {}
        self._default_handler: TaskHandler | None = None

        # Persistent nonce store
        if nonce_file:
            self._nonces = _NonceStore(nonce_file)
        else:
            self._nonces = _NonceStore("")  # in-memory only (empty path = no persistence)

        # Budget tracking
        self._budget = _BudgetTracker(max_spend_per_hour)

    def handle(self, task_type: str) -> Callable[[TaskHandler], TaskHandler]:
        """Register a handler for a task type.

        @agent.handle("code_review")
        def review(task):
            return {"result": "pass"}
        """
        def decorator(fn: TaskHandler) -> TaskHandler:
            self._handlers[task_type] = fn
            return fn
        return decorator

    def default(self, fn: TaskHandler) -> TaskHandler:
        """Register a default handler for any unregistered task type.

        @agent.default
        def fallback(task):
            return {"result": "done"}
        """
        self._default_handler = fn
        return fn

    def process(self, email: PaymentEmail) -> PaymentEmail | None:
        """Process a single incoming email. Returns a reply email or None."""
        task_type = email.task.get("task", "")

        # Resolve handler: named handler first, then default, then drop
        handler = self._handlers.get(task_type) or self._default_handler
        if handler is None:
            return None

        # No payment and we require one
        if self.price > 0 and not email.has_payment:
            return _payment_required_reply(
                email, self.email_addr, self.price, self.token, self.network
            )

        # Check nonce replay
        if email.has_payment and email.payment.nonce:
            nonce_key = f"{email.payment.sender}:{email.payment.nonce}"
            if self._nonces.seen(nonce_key):
                return _error_reply(
                    email, self.email_addr, "nonce already used"
                )
            self._nonces.add(nonce_key)

        # Verify payment signature (cryptographic proof)
        if email.has_payment and not verify_signature(email.payment):
            return _error_reply(
                email, self.email_addr, "payment verification failed"
            )

        # Check budget
        if email.has_payment and email.payment:
            if not self._budget.can_spend(email.payment.amount):
                return _error_reply(
                    email, self.email_addr, "budget exceeded"
                )

        # Do the work (with timeout)
        result = _run_with_timeout(handler, email.task, self.handler_timeout)

        if result is None:
            return _error_reply(
                email, self.email_addr, "handler timeout"
            )

        # Record spend
        if email.has_payment and email.payment:
            self._budget.record(email.payment.amount)

        # Build reply
        reply = PaymentEmail(
            from_addr=self.email_addr,
            to_addr=email.from_addr,
            task=result,
            subject=f"Re: {email.subject}",
            in_reply_to=email.message_id,
        )
        if email.has_payment and email.payment:
            has_tx = bool(email.payment.tx_hash)
            reply.payment_response = {
                "status": "settled" if has_tx else "verified",
                "tx": email.payment.tx_hash,
            }
        return reply

    def run(self) -> None:
        """Poll IMAP and dispatch tasks forever."""
        print(f"Agent {self.email_addr} listening...")
        while True:
            try:
                for email in receive(
                    imap_host=self.imap_host,
                    imap_port=self.imap_port,
                    imap_user=self.imap_user,
                    imap_pass=self.imap_pass,
                ):
                    reply = self.process(email)
                    if reply:
                        self._send_reply(reply)
            except Exception as e:
                print(f"Error: {e}")
            time.sleep(self.poll_interval)

    def _send_reply(self, reply: PaymentEmail) -> None:
        """Send a reply email via SMTP."""
        msg = compose(reply)

        # Add payment response header if present
        if reply.payment_response:
            msg["X-Payment-Response"] = json.dumps(
                reply.payment_response, separators=(",", ":")
            )

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            if self.smtp_user:
                server.login(self.smtp_user, self.smtp_pass)
            server.send_message(msg)


def _run_with_timeout(
    handler: TaskHandler, task: dict, timeout: float,
) -> dict | None:
    """Run a handler with a timeout. Returns None on timeout."""
    result: dict | None = None
    exception: Exception | None = None

    def target():
        nonlocal result, exception
        try:
            result = handler(task)
        except Exception as e:
            exception = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        return None
    if exception:
        raise exception
    return result


def _payment_required_reply(
    original: PaymentEmail,
    from_addr: str,
    price: int,
    token: str,
    network: str,
) -> PaymentEmail:
    """Build a 402-equivalent reply."""
    reply = PaymentEmail(
        from_addr=from_addr,
        to_addr=original.from_addr,
        subject=f"Re: {original.subject}",
        in_reply_to=original.message_id,
        body_text="Payment required to process this request.",
    )
    reply.payment_required = PaymentRequired(
        scheme="exact",
        network=network,
        max_amount=price,
        token=token,
        resource=f"agent://{from_addr}",
        description=original.task.get("task", "request"),
    )
    return reply


def _error_reply(
    original: PaymentEmail,
    from_addr: str,
    error: str,
) -> PaymentEmail:
    """Build an error reply."""
    return PaymentEmail(
        from_addr=from_addr,
        to_addr=original.from_addr,
        subject=f"Re: {original.subject}",
        in_reply_to=original.message_id,
        body_text=f"Error: {error}",
        task={"error": error},
    )
