"""Minimal agent loop: poll IMAP, dispatch tasks, reply with results."""

from __future__ import annotations

import json
import time
from typing import Callable

from mailpay.models import PaymentEmail, PaymentRequired
from mailpay.receive import receive, verify_payment
from mailpay.send import compose

import smtplib


# Type for task handler: takes a task dict, returns a result dict
TaskHandler = Callable[[dict], dict]


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
        token: str = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        network: str = "base",
        poll_interval: int = 10,
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
        self._handlers: dict[str, TaskHandler] = {}

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

    def process(self, email: PaymentEmail) -> PaymentEmail | None:
        """Process a single incoming email. Returns a reply email or None."""
        task_type = email.task.get("task", "")

        # Unknown task type
        if task_type not in self._handlers:
            return None

        # No payment and we require one
        if self.price > 0 and not email.has_payment:
            return _payment_required_reply(
                email, self.email_addr, self.price, self.token, self.network
            )

        # Verify payment
        if email.has_payment and not verify_payment(email.payment, self.network):
            return _error_reply(
                email, self.email_addr, "payment verification failed"
            )

        # Do the work
        handler = self._handlers[task_type]
        result = handler(email.task)

        # Build reply
        reply = PaymentEmail(
            from_addr=self.email_addr,
            to_addr=email.from_addr,
            task=result,
            subject=f"Re: {email.subject}",
            in_reply_to=email.message_id,
        )
        if email.has_payment:
            reply.payment_response = {
                "status": "settled",
                "tx": email.payment.tx_hash if email.payment else "",
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
