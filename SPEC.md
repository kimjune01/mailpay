# Mailpay Protocol Specification

Version: 0.1.0-draft

## 1. Scope

Mailpay is an SMTP-native protocol for agent-to-agent paid requests over email.

This specification defines:

- A message state machine carried in email headers
- A payment-proof JSON MIME part
- A settlement-proof JSON MIME part
- DKIM-based provenance requirements
- Threading requirements using `Message-ID`, `In-Reply-To`, and `References`
- Optional extension states for low-trust interactions
- A rail-agnostic proof model with fallback payment links

Mailpay does not define a specific blockchain, payment rail, wallet system, escrow contract, or proof format. It defines how proofs are transported and linked in an email transaction log.

## 2. Terminology

The key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are interpreted as described in RFC 2119.

- **Proof**: machine-verifiable evidence that value has been authorized, reserved, or transferred
- **Settlement proof**: machine-verifiable evidence that the transaction was settled or finalized
- **Transaction thread**: the ordered email conversation representing one mailpay transaction
- **Fallback**: a payment URL for counterparties without wallet infrastructure

## 3. Design Principles

- SMTP-native. MIME-native. DKIM-anchored.
- The email thread is the transaction log.
- The protocol mandates a proof, not a rail.
- Two core states. Everything else is optional.

## 4. Message Model

Each mailpay message:

- MUST be a valid RFC 5322 email
- MUST include `Message-ID`
- MUST include `X-Mailpay-State`
- MUST carry the mailpay payload as a `Content-Type: application/json` MIME part
- SHOULD be DKIM-signed by the sender domain
- MUST use `In-Reply-To` and `References` for all messages after the first

## 5. States

### 5.1 Core States

Conforming implementations MUST support:

| State | Direction | Semantics |
|-------|-----------|-----------|
| `REQUEST` | Payer → Worker | Initiates a paid task with payment proof |
| `DELIVER` | Worker → Payer | Completes the task with settlement proof |

These two states are sufficient for the base protocol.

### 5.2 Extension States

Implementations MAY support these for low-trust or high-value transactions:

| State | Direction | Semantics |
|-------|-----------|-----------|
| `ACCEPT` | Worker → Payer | Confirms commitment before starting work |
| `CONFIRM` | Payer → Worker | Confirms receipt and releases escrow |
| `DISPUTE` | Payer → Worker | Contests delivery within a dispute window |
| `RESOLVE` | Arbitrator → Both | Issues a ruling with settlement instruction |

Implementations that do not support extension states MUST still interoperate on `REQUEST` and `DELIVER`.

### 5.3 Trust Compression

Agents SHOULD select the minimum states needed:

| Trust level | States | Example |
|------------|--------|---------|
| High | REQUEST → DELIVER | Repeat counterparty, small task |
| Medium | REQUEST → ACCEPT → DELIVER → CONFIRM | First interaction, moderate value |
| Low | Full lifecycle + DISPUTE → RESOLVE | Unknown agent, high-value task |

Trust assessment is an application concern, not a protocol concern.

### 5.4 Header

```
X-Mailpay-State: REQUEST
```

Values MUST be one of: `REQUEST`, `DELIVER`, `ACCEPT`, `CONFIRM`, `DISPUTE`, `RESOLVE`. Values SHOULD be uppercase on send, MUST be case-insensitive on receipt.

## 6. REQUEST

### 6.1 Header Requirements

- MUST include `X-Mailpay-State: REQUEST`
- MUST include `Message-ID`
- SHOULD be DKIM-signed
- MUST NOT include `In-Reply-To` unless continuing an existing negotiation

### 6.2 Payment-Proof JSON

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `amount` | string | Yes | Payment amount in smallest unit (e.g., `"500000"` = $0.50 USDC) |
| `token` | string | Yes | Asset identifier (contract address or symbol) |
| `chain` | string | Yes | Settlement chain identifier |
| `proof` | any | Yes | Rail-specific proof material. Opaque to the protocol. |
| `fallback` | string (URL) | No | Payment link for off-spec on-ramp (Stripe, PayPal, Cash App, etc.) |

The `proof` field MAY be a signed intent, transfer authorization, escrow receipt, Lightning invoice, card gateway reference, or any other rail-specific artifact. The protocol transports proofs; it does not standardize the underlying rail.

### 6.3 Task

The JSON part SHOULD include a `task` field with a freeform object describing the work. No schema is mandated. Application-specific fields (invoice IDs, order references, metadata) go here.

### 6.4 Example

```
From: alice-agent@alice.dev
To: review-agent@codereviews.cc
Subject: Review PR #417
Message-ID: <req-1234@alice.dev>
X-Mailpay-State: REQUEST
DKIM-Signature: v=1; a=rsa-sha256; d=alice.dev; ...
Content-Type: multipart/mixed; boundary="mp"

--mp
Content-Type: text/plain; charset=utf-8

Review PR #417 in github.com/alice/widget

--mp
Content-Type: application/json; charset=utf-8

{
  "task": {"description": "Review PR #417", "repo": "github.com/alice/widget"},
  "amount": "500000",
  "token": "USDC",
  "chain": "base",
  "proof": {"type": "signed-intent", "payload": "0xabc...", "signature": "0xdef..."},
  "fallback": "https://pay.stripe.com/c/cs_live_abc123"
}
--mp--
```

## 7. DELIVER

### 7.1 Header Requirements

- MUST include `X-Mailpay-State: DELIVER`
- MUST include `Message-ID`
- MUST include `In-Reply-To` referencing the REQUEST's `Message-ID`
- MUST include `References` containing the transaction thread chain
- SHOULD be DKIM-signed

### 7.2 Settlement-Proof JSON

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `settlement` | object | Yes | Rail-specific settlement proof. Opaque to the protocol. |
| `result` | object | No | Freeform work product. |

### 7.3 Example

```
From: review-agent@codereviews.cc
To: alice-agent@alice.dev
Subject: Re: Review PR #417
Message-ID: <deliver-5678@codereviews.cc>
In-Reply-To: <req-1234@alice.dev>
References: <req-1234@alice.dev>
X-Mailpay-State: DELIVER
DKIM-Signature: v=1; a=rsa-sha256; d=codereviews.cc; ...
Content-Type: multipart/mixed; boundary="mp"

--mp
Content-Type: text/plain; charset=utf-8

Approved with 2 comments.

--mp
Content-Type: application/json; charset=utf-8

{
  "result": {"summary": "Approved with 2 comments"},
  "settlement": {"type": "transfer", "tx": "0xSETTLE..."}
}
--mp--
```

## 8. Payment Required (402)

When a receiver gets a task without payment, it MAY reply with payment terms:

```
X-Mailpay-State: PAYMENT-REQUIRED
```

```json
{
  "amount": "500000",
  "token": "USDC",
  "chain": "base",
  "fallback": "https://pay.stripe.com/c/cs_live_abc123"
}
```

The sender resubmits with payment attached. This mirrors HTTP 402.

## 9. DKIM Provenance

### 9.1 Requirements

- Senders SHOULD DKIM-sign all mailpay messages.
- Receivers SHOULD verify DKIM on every mailpay message.
- Receivers MUST record DKIM verification outcome alongside the transaction.
- Receivers MAY reject or downgrade trust for messages without valid DKIM.

### 9.2 Semantics

DKIM proves that a domain-authenticated sender originated the message and that the body has not been altered in transit. Mailpay uses DKIM as provenance — a tamper-evident signed transcript — not as consensus.

DKIM does not bind to a wallet. Higher-layer identity binding (ZK Email, EAS) is out of scope.

## 10. Threading

The email thread is the transaction log.

- The first message in a transaction (REQUEST) establishes the thread via `Message-ID`.
- Every subsequent message MUST reference the thread via `In-Reply-To` and `References`.
- Both parties hold the full log. No external state is required.
- Implementations SHOULD persist raw headers and message linkage, not only parsed payloads.

## 11. Security Considerations

### 11.1 Replay Protection

Receivers MUST track processed `Message-ID` values and reject duplicates. Proof payloads SHOULD include replay-resistant semantics (nonces, expirations, recipient binding).

### 11.2 Proof Validation

Receivers MUST validate `proof` and `settlement` according to the chosen rail before taking irreversible action. The protocol transports opaque proofs — validation is the application's responsibility.

### 11.3 Amount Verification

Receivers MUST verify the on-chain transfer amount matches the claimed amount.

### 11.4 Thread Integrity

The transaction thread is the source of truth. Implementations SHOULD detect and reject messages with broken thread linkage.

## 12. Interoperability

### 12.1 Minimum Conforming Implementation

A conforming mailpay implementation MUST:

- Send and receive RFC 5322 email
- Parse MIME messages
- Support `REQUEST` and `DELIVER`
- Require `X-Mailpay-State` header
- Parse REQUEST JSON with `amount`, `token`, `chain`, `proof`
- Parse DELIVER JSON with `settlement`
- Maintain thread linkage with `Message-ID`, `In-Reply-To`, `References`
- Verify or record DKIM provenance status
- Treat `proof` and `settlement` as opaque

### 12.2 x402 Compatibility

Mailpay is compatible with the [x402 specification](https://www.x402.org/). The `X-Payment` and `X-Payment-Response` headers from the existing mailpay implementation are accepted as aliases for `X-Mailpay-State: REQUEST` and `X-Mailpay-State: DELIVER` respectively.

## 13. Application Concerns

The following are explicitly out of scope for the protocol and left to application implementations:

- Refund policies
- Invoice IDs and order references
- Milestone tracking and partial completion
- Dispute resolution procedures
- Escrow contract logic
- Trust scoring and reputation
- Wallet-email identity binding
- Tax and compliance reporting

The protocol carries proofs. Applications decide policy.
