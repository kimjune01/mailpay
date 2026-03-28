# core/ — Email Payment Protocol

## What it does
Compose, send, receive, and verify paid emails over SMTP with envelopay payment proofs on Solana.

## API

### Models
- `Payment(signature, amount, token, network, nonce, tx_hash, sender, recipient)` — serializes to/from X-Payment header JSON
- `PaymentRequired(scheme, network, max_amount, token, resource, description)` — 402 equivalent
- `PaymentEmail(from_addr, to_addr, task, payment, wallet_key, payer_wallet, payee_wallet, ...)` — the full email envelope

### Functions
- `sign_payment(amount, token, network, private_key, recipient) → Payment` — ed25519 sign canonical message
- `verify_signature(payment) → bool` — verify ed25519 sig against sender pubkey
- `verify_on_chain(payment, network, rpc_url) → bool` — requires tx_hash, checks Solana RPC for matching transfer (mint, sender, recipient, amount)
- `compose(email) → MIMEMultipart` — build MIME with X-Payment, X-Payment-Required headers
- `send(email, smtp_host, ...) → message_id` — SMTP send
- `parse_email(raw_bytes) → PaymentEmail` — parse MIME, extract envelopay headers, verify DKIM
- `receive(imap_host, ...) → Iterator[PaymentEmail]` — poll IMAP for unread

## Contracts
- `sign_payment` + `verify_signature` roundtrips: sign then verify always True
- Tampered fields (amount, recipient, token) fail verification
- `verify_on_chain` rejects empty tx_hash
- `compose` + `parse_email` roundtrips: all fields survive MIME serialization
- X-Payment-Required emitted when payment_required is set
- Payment proof in both header (X-Payment) and body (JSON) — belt and suspenders
