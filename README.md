# mailpay

Agent-to-agent payments over email. x402 headers on SMTP.

**The idea:** email already has identity (DKIM), payloads (MIME), threading (`In-Reply-To`), and federation (SMTP). The only missing dimension is value. [x402](https://www.x402.org/) defined the payment header format for HTTP. This library ports it to email.

## What it does

1. **Send a paid task** — compose an email with an x402 `X-Payment` header and a MIME payload
2. **Receive and verify** — check DKIM signature, verify on-chain payment, process the task
3. **Reply with results** — include `X-Payment-Response` with settlement proof

## Quick start

```bash
pip install mailpay
```

### Send a paid request

```python
from mailpay import PaymentEmail, send

email = PaymentEmail(
    from_addr="alice-agent@alice.dev",
    to_addr="review-agent@codereviews.cc",
    task={"task": "code_review", "repo": "https://github.com/alice/widget", "commit": "a1b2c3d"},
    payment_amount=50000,  # 0.05 USDC (6 decimals)
    payment_token="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
    payment_network="base",
    wallet_key="0xYOUR_PRIVATE_KEY",
)
send(email, smtp_host="smtp.alice.dev", smtp_port=587)
```

### Receive and process

```python
from mailpay import receive, verify_payment

for email in receive(imap_host="imap.codereviews.cc", folder="INBOX"):
    if not email.has_payment:
        email.reply_payment_required(amount=50000, token=USDC, network="base")
        continue

    if not verify_payment(email.payment, network="base"):
        email.reply_error("payment verification failed")
        continue

    # Do the work
    result = run_code_review(email.task)
    email.reply(result=result, payment_response={"status": "settled", "tx": email.payment.tx_hash})
```

### Fallback to payment link

```python
email = PaymentEmail(
    from_addr="alice-agent@alice.dev",
    to_addr="old-agent@legacy.com",
    task={"task": "translate", "text": "Hello world"},
    payment_link="https://buy.stripe.com/abc123",  # fallback for agents without x402
)
```

## How it works

```
alice-agent@alice.dev                    review-agent@codereviews.cc
        |                                          |
        |  -------- SMTP + DKIM + X-Payment -----> |
        |           (task in MIME body)             |
        |                                          |
        |                    Base L2: verify USDC   |
        |                                          |
        | <--- SMTP + DKIM + X-Payment-Response --- |
        |           (result in MIME body)           |
```

## Headers

Follows the [x402 specification](https://github.com/coinbase/x402/blob/main/specs/x402-specification.md), adapted for SMTP:

| Header | Direction | Purpose |
|--------|-----------|---------|
| `X-Payment-Required` | Reply (402 equivalent) | Payment terms: amount, token, network |
| `X-Payment` | Request | Signed payment proof |
| `X-Payment-Response` | Reply | Settlement confirmation |

## License

AGPL-3.0. If you serve this over a network, share your source.

## See also

- [You Have Mail](https://june.kim/you-have-mail) — the argument
- [Proof of Trust](https://june.kim/proof-of-trust) — trust graph over email
- [x402 spec](https://www.x402.org/) — the payment header format
- [Hashcash](http://www.hashcash.org/) — where email payment headers started (1997)
