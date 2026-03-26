# agent/ — Paid Email Agent Loop

## What it does
Poll IMAP for paid task requests, verify payment, dispatch to handlers, reply with results.

## API

### Agent
```python
agent = Agent(email_addr, imap_host, smtp_host, price, token, network, ...)

@agent.handle("code_review")
def review(task: dict) -> dict:
    return {"result": "pass"}

agent.run()  # polls forever
agent.process(email) -> PaymentEmail | None  # single dispatch
```

## Contracts
- Unknown task type → return None (ignore)
- Missing payment when price > 0 → reply X-Payment-Required (402)
- Invalid signature → reply error
- Replayed nonce → reply "nonce already used"
- Valid payment with tx_hash → reply status "settled"
- Valid payment without tx_hash → reply status "verified"
- Handler exception → reply error, don't crash loop
- Seen nonces tracked in memory (set of sender:nonce pairs)

## Missing (to implement)
- Persistent nonce store (currently in-memory, lost on restart)
- Handler timeout / cancellation
- Concurrent task processing (currently sequential poll)
- Budget tracking (spending limits per period)
