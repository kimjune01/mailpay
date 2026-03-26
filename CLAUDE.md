# envelopay

Agent-to-agent payments over email. x402 headers on SMTP.

## Stack

- Python 3.11+
- `uv` for package management
- No web framework — this is a library + CLI

## Structure

- `envelopay/` — library package
  - `send.py` — compose and send paid emails via SMTP
  - `receive.py` — poll IMAP, parse x402 headers, verify DKIM
  - `payment.py` — x402 header construction, on-chain verification
  - `models.py` — dataclasses for PaymentEmail, Payment, Task
- `cli.py` — CLI entrypoint (`envelopay send`, `envelopay listen`)
- `tests/` — pytest

## Dev

```bash
uv sync
uv run pytest
```
