# envelopay

Agent-to-agent payments over email. Two emails, any rail.

**The idea:** email already has identity (DKIM), payloads (MIME), threading (`In-Reply-To`), and federation (SMTP). The only missing dimension is value. Envelopay adds a payment proof to the envelope.

## Quick start

### 1. Get email accounts

Sign up at [AgentMail](https://www.agentmail.to) (free tier: 3 inboxes, 100 emails/day). Create your agent inboxes:

```bash
export AGENTMAIL_API_KEY="am_..."

# Create inboxes
curl -X POST https://api.agentmail.to/v0/inboxes \
  -H "Authorization: Bearer $AGENTMAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"username": "axiomatic"}'

curl -X POST https://api.agentmail.to/v0/inboxes \
  -H "Authorization: Bearer $AGENTMAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"username": "blader"}'
```

### 2. Install

```bash
uv sync
```

### 3. Run the demo

```bash
uv run python demo/four_rails.py
```

Shows all four payment paths:

| Path | Payer rail | Receiver rail | Bridge |
|------|-----------|--------------|--------|
| Crypto → crypto | On-chain | On-chain | None |
| Card → crypto | Stripe | On-chain | Bridge.xyz on-ramp |
| Crypto → card | On-chain | Bank/card | Bridge.xyz off-ramp |
| Card → card | Stripe | Stripe | None |

Plus a bounced payment (invalid proof → no DELIVER).

## Protocol

Two states. That's the whole protocol.

| State | Direction | Semantics |
|-------|-----------|-----------|
| `REQUEST` | Payer → Worker | Task + payment proof |
| `DELIVER` | Worker → Payer | Work product + settlement proof |

The `X-Envelopay-State` header carries the state. The JSON MIME part carries the payload. DKIM proves provenance. `In-Reply-To` links the thread. The thread is the transaction log.

See [SPEC.md](SPEC.md) for the full protocol specification.

## What the emails look like

### REQUEST

```
From: axiomatic@agentmail.to
To: blader@agentmail.to
Subject: Review PR #417
Message-ID: <req-8f3a@agentmail.to>
X-Envelopay-State: REQUEST
DKIM-Signature: v=1; a=rsa-sha256; d=agentmail.to; ...
Content-Type: multipart/mixed; boundary="mp"

--mp
Content-Type: text/plain; charset=utf-8

Review PR #417 in github.com/axiomatic/widget

--mp
Content-Type: application/json; charset=utf-8

{
  "task": {"description": "Review PR #417", "repo": "github.com/axiomatic/widget"},
  "amount": "500000",
  "token": "USDC",
  "chain": "solana",
  "proof": {"tx": "4vJ9..."},
  "fallback": "https://cash.app/$axiomatic"
}
--mp--
```

### DELIVER

```
From: blader@agentmail.to
To: axiomatic@agentmail.to
Subject: Re: Review PR #417
In-Reply-To: <req-8f3a@agentmail.to>
X-Envelopay-State: DELIVER
DKIM-Signature: v=1; a=rsa-sha256; d=agentmail.to; ...

{
  "result": {"summary": "Approved with 2 comments"},
  "settlement": {"tx": "4vJ9...", "status": "confirmed"}
}
```

Two emails. Both DKIM-signed. Both parties hold the full record.

## Fallback

The `fallback` field carries a payment URL for counterparties without a wallet: Stripe checkout, PayPal, Cash App, Venmo — any URL that accepts money. The protocol mandates a proof, not a rail.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AGENTMAIL_API_KEY` | Yes | AgentMail API key for sending/receiving |
| `SOLANA_PRIVATE_KEY` | For crypto paths | Solana wallet private key (base58) |
| `BRIDGE_API_KEY` | For cross-rail | Bridge.xyz API key for fiat ↔ crypto |
| `STRIPE_SECRET_KEY` | For card paths | Stripe API key for card payments |

## License

AGPL-3.0. If you serve this over a network, share your source.

## See also

- [Sent](https://june.kim/sent) — the user story
- [Certified Mail](https://june.kim/certified-mail) — the semantics
- [You Have Mail](https://june.kim/you-have-mail) — the protocol argument
- [No Postage](https://june.kim/no-postage) — the economics
- [Illegal Tender](https://june.kim/illegal-tender) — the stack
- [Proof of Trust](https://june.kim/proof-of-trust) — trust topology
- [SPEC.md](SPEC.md) — protocol specification
- [STACK.md](STACK.md) — component map
