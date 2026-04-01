"""ORDER handler — digital goods fulfillment for axiomatic."""

from __future__ import annotations

import json
import logging

from agentmail import AgentMail

from exchange.rate import get_sol_usd_rate, apply_spread
from exchange.config import SPREAD
from exchange.reply import _oops, _reply

logger = logging.getLogger(__name__)

# Catalog: item_key -> {name, price_usd, file_url}
# Prices in USD — converted to lamports at current SOL rate + spread.
CATALOG = {
    "cashie-ui-kit": {
        "name": "Cashie UI Kit",
        "price_usd": 10.00,
        "file_url": "https://public-files.gumroad.com/npkic7uy1wzxo3k8k5hodowf8na2",
        "filename": "cashie-ui-kit.zip",
    },
}


def price_lamports(price_usd: float) -> int:
    """Convert a USD price to lamports at the current spread rate."""
    rate = apply_spread(get_sol_usd_rate(), SPREAD)
    sol = price_usd / rate
    return int(sol * 1_000_000_000)


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    return {}


def _extract_item_name(subject: str, text: str) -> str:
    """Pull item name from subject or body."""
    # Try subject after "ORDER |"
    if "|" in subject:
        name = subject.split("|", 1)[1].strip()
        # Strip price suffix like ", 0.13 SOL"
        if "," in name:
            name = name.rsplit(",", 1)[0].strip()
        if name:
            return name
    body = _parse_json(text)
    task = body.get("task", {})
    if isinstance(task, dict) and task.get("description"):
        return task["description"]
    if body.get("note"):
        return body["note"]
    return "Digital Product"


def handle_order(client: AgentMail, inbox_id: str, reply_to_msg_id: str,
                 from_addr: str, text: str, subject: str) -> None:
    """Process an ORDER: fulfill with download link."""
    body = _parse_json(text)
    item_name = _extract_item_name(subject, text)
    slug = item_name.lower().replace(" ", "-")

    fulfill = {
        "v": "0.1.0",
        "type": "fulfill",
        "order_ref": body.get("id", ""),
        "result": {
            "summary": f"Delivered: {item_name}",
            "download": f"https://axiomatic.store/download/{slug}",
        },
        "note": f"Payment verified. Here's your {item_name}.",
    }

    _reply(client, inbox_id, reply_to_msg_id,
           subject=f"FULFILL | {item_name}",
           text=json.dumps(fulfill, indent=2),
           headers={"X-Envelopay-Type": "FULFILL"},
           to=from_addr)
    logger.info("FULFILLED %s to %s", item_name, from_addr)
