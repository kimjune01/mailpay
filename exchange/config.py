"""Configuration from environment variables."""

from __future__ import annotations

import os

AGENTMAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
SOLANA_PRIVATE_KEY = os.environ.get("SOLANA_PRIVATE_KEY", "")
EXCHANGE_INBOX = os.environ.get("EXCHANGE_INBOX", "axiomatic@agentmail.to")
CASHAPP_HANDLE = os.environ.get("CASHAPP_HANDLE", "$kimjune01")
VENMO_HANDLE = os.environ.get("VENMO_HANDLE", "@June-Kim-04933")
SOL_WALLET = os.environ.get("SOL_WALLET", "9gYwhNNw8cWs8RKXHvsKk66wMbDbSMLdJCkGmUcmkpAM")

MIN_FIAT_CENTS = 100   # $1.00
MAX_FIAT_CENTS = 500   # $5.00
SPREAD = 0.30           # 30%

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

LEDGER_GITHUB_TOKEN = os.environ.get("LEDGER_GITHUB_TOKEN", "")
LEDGER_REPO = os.environ.get("LEDGER_REPO", "kimjune01/envelopay-ledger")
LEDGER_PREFIX = os.environ.get("LEDGER_PREFIX", "axiomatic")

LOW_BALANCE_LAMPORTS = int(os.environ.get("LOW_BALANCE_LAMPORTS", "240000000"))  # ~$20 of SOL
OPERATOR_EMAIL = os.environ.get("OPERATOR_EMAIL", "june@june.kim")

KNOWN_TYPES = {"WHICH", "METHODS", "PAY", "ORDER", "FULFILL", "INVOICE", "OFFER", "ACCEPT", "OOPS"}
