# Cambio — $1–$5 SOL dispensary

Fiat in, SOL out. For developers who need real mainnet SOL to test with.

## What it does

Accept $1–$5 USD via CashApp or Venmo. Dispense SOL at live market rate minus 30% spread. Accept chargeback risk wholly — amounts too small to dispute.

## Flow

1. User emails `WHICH` → exchange replies `METHODS` with CashApp/Venmo handles and current SOL rate
2. User sends $1–$5 via CashApp or Venmo
3. User emails `OFFER` with their Solana wallet address → exchange logs pending transaction
4. Gmail forwards CashApp/Venmo "paid you" notification to the AgentMail inbox
5. Handler auto-matches notification to pending OFFER by amount (FIFO)
6. Exchange sends SOL to user's wallet, replies `ACCEPT` with tx hash

Reversal notifications ("reversed", "dispute", "chargeback", "declined") are detected and ignored.

## Scope

- One direction: USD → SOL
- Two rails: CashApp (`$kimjune01`) and Venmo (`@June-Kim-04933`)
- $1–$5 per transaction
- 30% spread on live SOL/USD rate
- Auto-matching via forwarded payment notifications
- Manual operator CLI fallback for edge cases
- All transactions logged (SQLite) for analytics
- Hot wallet payout via Solana RPC

## Not in scope

- SOL → USD (reverse direction)
- Multiple pairs
- Partial fills
- User accounts

## Email setup

**Inbox:** `axiomatic@agentmail.to` (AgentMail, polled every 1 min via Lambda + EventBridge)

**Gmail forwarding:** Payment notifications from CashApp/Venmo forward to the AgentMail inbox automatically.

Gmail filter:
- **From:** `venmo@venmo.com OR cash@square.com`
- **Has the words:** `"paid you" OR "sent you"`
- **Does NOT have:** `reversed OR dispute OR chargeback OR "payment canceled" OR "payment returned" OR declined`
- **Forward to:** `axiomatic@agentmail.to`

## Operator CLI

```bash
cd /Users/junekim/Documents/envelopay
source .env && export $(cut -d= -f1 .env)
python -m exchange.cli pending         # what's waiting
python -m exchange.cli approve <id>    # manual approve + send SOL
python -m exchange.cli reject <id> "reason"  # manual reject
python -m exchange.cli stats           # volume, count, average
```

## Config

Environment variables (see `config.py` and `.env`):

| Var | Purpose |
|-----|---------|
| `AGENTMAIL_API_KEY` | AgentMail API key |
| `SOLANA_PRIVATE_KEY` | Hot wallet private key (base58) |
| `EXCHANGE_INBOX` | AgentMail inbox (default: `axiomatic@agentmail.to`) |
| `SOL_WALLET` | Hot wallet public address |
| `CASHAPP_HANDLE` | CashApp cashtag (default: `$kimjune01`) |
| `VENMO_HANDLE` | Venmo handle (default: `@June-Kim-04933`) |
| `WEBHOOK_SECRET` | Webhook verification (optional) |
