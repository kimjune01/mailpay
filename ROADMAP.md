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

## Consolidate (the sixth cell)

The exchange currently has 5 of 6 Natural Framework roles. Consolidate is missing — no cron job reads the ledger and updates how the system processes next time. Adding it:

- **Dynamic spread**: read settlement history, adjust spread based on volume and chargeback rate. High volume + zero chargebacks → lower spread. Chargebacks → wider spread. The 30% is a starting point, not an endpoint.
- **Reputation scoring**: read the trust topology, weight matching by sender history. Repeat customers with clean settlements get priority. New senders get slower matching.
- **Rate prediction**: read trade history, predict demand windows. Pre-fund the hot wallet before peak hours. Adjust indicative pricing in METHODS based on inventory pressure.
- **Ban decay**: read ban history, soften bans over time. A chargeback from a year ago isn't the same as one from yesterday. The forgiveness curve is a learned parameter.
- **Risk-adjusted limits**: read settlement history per sender, adjust max transfer. New sender: $5 cap. After 5 clean settlements: $10. After 20: $50. The cap is a learned parameter per identity, not a global constant. One chargeback resets it to zero.
- **Global floor adjustment**: read aggregate chargeback rate across all senders. If chargebacks spike globally (fraud wave, platform policy change), lower the floor for everyone — even trusted senders. The per-sender limit is the ceiling; the global floor pulls it down when the environment is hostile.
- **DKIM-adjusted limits**: DKIM-verified sender gets the full limit. DKIM absent or failed gets a lower multiplier. Effective cap is `min(sender_cap, global_floor) * dkim_factor`. Three learned inputs: individual trust, collective risk, provenance confidence.
- **Anomaly detection**: read recent events, flag patterns. Same amount from different emails in quick succession. Sudden volume spikes. The system learns what normal looks like and alerts on deviation.
