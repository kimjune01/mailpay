# envelopay

Agent-to-agent payments over email. Envelopay headers on SMTP.

## Stack

- Python 3.11+
- `uv` for package management
- No web framework — this is a library + CLI

## Structure

- `envelopay/` — library package
  - `send.py` — compose and send paid emails via SMTP
  - `receive.py` — poll IMAP, parse envelopay headers, verify DKIM
  - `payment.py` — envelopay header construction, on-chain verification
  - `models.py` — dataclasses for PaymentEmail, Payment, Task
- `cli.py` — CLI entrypoint (`envelopay send`, `envelopay listen`)
- `tests/` — pytest

## Dev

```bash
uv sync
uv run pytest
```
