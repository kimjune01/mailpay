# checkout/ — QR and Checkout Links

## What it does
Generate mailto: URLs for QR codes and one-click checkout. The link pre-composes a paid email; the sender's agent signs the payment on dispatch.

## API
- `mailto_url(to_addr, task, subject, payment_amount, ...) → str` — RFC 6068 mailto URL
- `checkout_link(to_addr, items, payment_amount, order_id, ...) → str` — purchase-specific mailto
- `qr_data(to_addr, task, payment_amount, ...) → str` — string for QR encoding

## Contracts
- Output is valid RFC 6068 mailto URL
- Task serialized as JSON in body
- Payment amount displayed as human-readable USDC in body
- All defaults are Solana/USDC
- QR data is just the mailto URL (feed to any QR library)

## Missing (to implement)
- Actual QR image generation (currently returns string for external library)
- Deep link for mobile wallet apps
- Expiration field in checkout links
