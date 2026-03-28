# Roadmap

Items for consideration. Not committed — just captured so we don't forget.

## Protocol (v0.2.0 candidates)

### Split payments
Half up front, half on completion. Deferred from v0.1.0 because it needs a real state machine: `upfront` proof in ORDER, `upon_completion` promise, PAY after FULFILL. The trust model is different — the worker trusts the payer to follow through.

### WAIT
Signal a pending state without using OOPS. "I got your message, I'm working on it." Not an error, not a result. Current workaround: silence until ACCEPT/FULFILL. WAIT would be a courtesy signal that something is in progress.

### WHATSUP
Query the status of a pending transaction. "I sent an OFFER an hour ago, where's my SOL?" The receiver replies with current state: pending, claimed, approved, rejected. Avoids the user resending because they think it was lost.

### ORDER schema
Optional structured fields so implementations don't invent their own:

```json
{"v":"0.1.0",
 "type":"order",
 "id":"ord_1",
 "task":{
   "description":"Review PR #417",
   "repo":"github.com/alice/widget",
   "ref":"pull/417",
   "scope":"security",
   "prompt":"Focus on auth boundaries",
   "resources":["https://github.com/alice/widget/pull/417"],
   "deadline":"2026-04-01"
 }}
```

All fields inside `task` are optional. The spec defines the vocabulary so people don't invent `order_id` vs `request_id` vs `job_id`, or `prompt` vs `instructions` vs `description`. One schema, optional fields, no enforcement.

## Exchange (axiomatic)

- Reverse direction: SOL → USD (payout via CashApp/Venmo)
- More rails: Interac, Zelle, PayPal
- Dynamic spread based on inventory level
- Multiple pairs: SOL/USDC, ETH/USDC
- Rate quotes with expiry (firm quotes, not just indicative)
- Automatic inventory rebalancing
