# Envelopay Shop

Sell digital goods over email. No framework, no dependencies, no platform fees.

## Setup

1. Get a free inbox at [agentmail.to](https://agentmail.to)
2. Get a Solana wallet address

```bash
export AGENTMAIL_API_KEY="your-key"
export SHOP_INBOX="yourshop@agentmail.to"
export SOL_WALLET="your-solana-wallet-address"
```

3. Edit the `CATALOG` dict in `shop.py` with your products
4. Run it:

```bash
python shop.py
```

That's it. Your inbox is now a store.

## How it works

The script polls your AgentMail inbox every 30 seconds. When someone emails:

- **WHICH** → replies with your catalog and wallet address
- **ORDER** → replies with a download link

No signup for the buyer. No checkout page. No fees. They send SOL, email the proof, get the file.

## Protocol

See the [Envelopay spec](https://june.kim/envelopay-spec) for the full protocol.
