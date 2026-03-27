# Envelopay Protocol v0.1.0

Agent-to-agent payments over email. The thread is the ledger.

## Transport

Every envelopay message is a valid RFC 5322 email with:

- `X-Envelopay-Type` header (the message type, case-insensitive on receipt)
- `Subject: TYPE | note` (type echoed in subject for human readability)
- JSON body with `v` (version string) and `type` (lowercase type name)
- `In-Reply-To` and `References` for all replies (standard email threading)
- DKIM signature (sender domain proves provenance)

## Message Types

Seven types. Two negotiate. Four transact. One handles errors.

| Type | Direction | Purpose |
|------|-----------|---------|
| `WHICH` | A → B | "What do you accept?" |
| `METHODS` | B → A | Accepted rails, wallets, pricing |
| `PAY` | A → B | Payment proof, no task attached |
| `ORDER` | A → B | Task + payment proof |
| `FULFILL` | B → A | Work product + settlement proof |
| `INVOICE` | B → A | "You owe me this, here's my wallet" |
| `OOPS` | either | Something went wrong |

## Negotiation

### WHICH

Asks what the receiver accepts. May include a task description for pricing.

```json
{"v":"0.1.0",
 "type":"which",
 "note":"Looking for a security-focused code review",
 "task":{"description":"Review PR #417"}}
```

### METHODS

Replies with accepted rails, wallets, and optionally a price.

```json
{"v":"0.1.0",
 "type":"methods",
 "note":"$0.50 USDC, Solana preferred",
 "price":{"amount":"500000","currency":"USDC"},
 "rails":[
   {"chain":"solana",
    "token":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "wallet":"6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif"},
   {"chain":"base",
    "token":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "wallet":"0x1a2B..."}
 ],
 "fallback":"https://pay.stripe.com/c/cs_live_abc123"}
```

When both parties already know each other's rails, skip WHICH/METHODS.

## Transactions

### PAY

Money with no task. A tip, a split bill, a donation. Fire-and-forget.

```json
{"v":"0.1.0",
 "type":"pay",
 "note":"Dinner — my half",
 "amount":"30000000",
 "token":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
 "chain":"base",
 "proof":{"tx":"0x7a3f..."}}
```

The money moves on-chain before the email is composed. The `proof` field carries rail-specific evidence (tx hash, signed intent, escrow receipt). The protocol transports proofs; it does not standardize the rail.

### ORDER

Task + payment. Expects a FULFILL.

```json
{"v":"0.1.0",
 "type":"order",
 "note":"Review PR #417, focus on auth boundaries",
 "task":{"description":"Review PR #417",
         "repo":"github.com/alice/widget",
         "scope":"security"},
 "amount":"500000",
 "token":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
 "chain":"solana",
 "proof":{"tx":"4vJ9..."}}
```

### FULFILL

Work product + settlement proof. Replies to an ORDER via `In-Reply-To`.

```json
{"v":"0.1.0",
 "type":"fulfill",
 "note":"Approved with 2 comments, one medium severity",
 "result":{"summary":"Approved with 2 comments",
           "findings":[{"file":"handler.go","line":47,
                        "severity":"medium",
                        "finding":"Session token not validated before use"}]},
 "settlement":{"tx":"4vJ9...","verified":true,"block":285714200}}
```

### INVOICE

"You owe me this." The recipient decides whether to pay. If they do, they send a PAY.

```json
{"v":"0.1.0",
 "type":"invoice",
 "note":"Auth hardening beyond original scope",
 "amount":"1000000",
 "token":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
 "chain":"solana",
 "wallet":"6dL6n77jJFWq4bu3cQp57H8rMUPEXu7uYN1XApPxpUif"}
```

## Errors

### OOPS

Any message can get an OOPS back. The `note` tells a human; the `error` object tells an agent.

```json
{"v":"0.1.0",
 "type":"oops",
 "note":"Payment not found on-chain",
 "error":{"code":"tx_not_found","tx":"0x3a7f..."}}
```

Common error codes:

| Code | Meaning |
|------|---------|
| `tx_not_found` | Transaction doesn't exist on-chain |
| `amount_mismatch` | On-chain amount doesn't match claimed amount |
| `dkim_failed` | Sender can't be authenticated |
| `unknown_type` | Subject looks like a protocol message but the type isn't recognized |
| `insufficient_funds` | Can't fulfill a refund or payment |
| `missing_wallet` | Invoice or refund request missing wallet address |

### Protocol mismatch

If the subject matches `^[A-Z]+(\s*\|.*)?$` but the keyword isn't one of the seven types, reply OOPS with `unknown_type`, the list of supported types, and a link to the spec.

No message in the protocol requires a response. Silence is always valid. OOPS is a courtesy, not an obligation.

## Flows

**Pay:** `PAY` → done.

**Order work:** `ORDER` → `FULFILL`. Two emails.

**Invoice:** `INVOICE` → `PAY`. Two emails.

**First contact:** `WHICH` → `METHODS` → `ORDER` → `FULFILL`. Four emails.

**Repeat customer:** `ORDER` → `FULFILL`. Skip negotiation.

## Verification

Receivers must verify before doing work:

1. Check DKIM signature on the incoming email
2. Verify the proof on-chain (tx exists, amount matches, recipient matches)
3. Check for replay (track processed Message-IDs)

An ORDER without a matching FULFILL is a DKIM-signed, timestamped record of non-delivery. The protocol doesn't prevent fraud — it makes fraud auditable.

## What the protocol doesn't do

| Protocol | Application |
|----------|-------------|
| Message types and headers | Discovery and ranking |
| Proof payload | Pricing and negotiation |
| Email threading | Retries and timeouts |
| DKIM verification | Reputation and trust |

Discovery, trust, escrow, disputes, refunds — application concerns. The protocol carries proofs. Applications decide policy.

## Spec

- [Certified Mail](https://june.kim/certified-mail) — the semantics
- [Sent](https://june.kim/sent) — the user story
