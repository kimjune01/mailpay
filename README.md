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

### Run a paid agent

```python
from mailpay import Agent

agent = Agent(
    email_addr="review-agent@codereviews.cc",
    imap_host="imap.codereviews.cc",
    smtp_host="smtp.codereviews.cc",
    price=50000,  # 0.05 USDC
)

@agent.handle("code_review")
def review(task):
    return {"result": "pass", "findings": []}

agent.run()  # polls IMAP, dispatches tasks, replies with results
```

The agent loop handles payment verification and 402 replies automatically. Register handlers, run, done.

### Scan to pay (QR / checkout link)

```python
from mailpay import mailto_url, checkout_link

# QR code for a farmers market stall
url = mailto_url(
    to_addr="shop@store.com",
    task={"task": "purchase", "item": "honey"},
    payment_amount=500000,  # $0.50
)
# → mailto:shop%40store.com?subject=Task%3A%20purchase&body=...

# One-click checkout link for e-commerce
link = checkout_link(
    to_addr="orders@widget.co",
    items=[{"name": "widget", "qty": 2}],
    payment_amount=1000000,  # $1.00
    order_id="#417",
)
```

Scan the QR or click the link. Your mail client opens with the order pre-composed. Your agent signs the x402 header and sends. No app. No card reader. No 2.9% + 30¢.

### Fallback to payment link

```python
email = PaymentEmail(
    from_addr="alice-agent@alice.dev",
    to_addr="old-agent@legacy.com",
    task={"task": "translate", "text": "Hello world"},
    payment_link="https://buy.stripe.com/abc123",  # fallback for agents without x402
)
```

## What the emails look like

### Request (with payment)

```
From: alice-agent@alice.dev
To: review-agent@codereviews.cc
DKIM-Signature: v=1; a=rsa-sha256; d=alice.dev; s=agent; ...
In-Reply-To: <quote-req-4821@codereviews.cc>
X-Payment: {"signature":"0x3a7f...","payload":{"amount":"50000",
  "token":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913","nonce":"a8c2..."}}
Content-Type: multipart/mixed; boundary="task-boundary"

--task-boundary
Content-Type: application/json

{
  "task": "code_review",
  "repo": "https://github.com/alice/widget",
  "commit": "a1b2c3d",
  "scope": "security"
}
--task-boundary
Content-Type: text/plain

Review the latest commit for security issues.
Focus on input validation and auth boundaries.
--task-boundary--
```

### Reply (with settlement proof)

```
From: review-agent@codereviews.cc
To: alice-agent@alice.dev
DKIM-Signature: v=1; a=rsa-sha256; d=codereviews.cc; s=agent; ...
In-Reply-To: <task-7392@alice.dev>
X-Payment-Response: {"status":"settled","tx":"0xf4e1..."}
Content-Type: application/json

{
  "result": "pass",
  "findings": [],
  "confidence": 0.94,
  "model": "claude-sonnet-4-6",
  "elapsed_ms": 12400
}
```

Two emails. One transaction. DKIM proves identity on both sides. The `X-Payment` header carries the signed stablecoin proof. The `X-Payment-Response` confirms settlement. Threading headers link them.

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

- [You Have Mail](https://june.kim/you-have-mail) — the protocol argument
- [No Postage](https://june.kim/no-postage) — the economic consequence
- [Proof of Trust](https://june.kim/proof-of-trust) — trust graph over email
- [x402 spec](https://www.x402.org/) — the payment header format
- [Hashcash](http://www.hashcash.org/) — where email payment headers started (1997)
