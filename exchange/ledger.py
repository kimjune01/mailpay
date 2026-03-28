"""GitHub-backed JSONL ledger transport layer."""

from __future__ import annotations

import base64
import json
import time
import urllib.request
import urllib.error
from typing import Optional

from exchange.config import LEDGER_GITHUB_TOKEN, LEDGER_REPO, LEDGER_PREFIX

# --- Cache ---
_cache_lines: Optional[list[dict]] = None
_cache_ts: float = 0.0
_cache_sha: Optional[str] = None
_CACHE_TTL = 5.0  # seconds

# --- Test override ---
# Tests can populate this list to bypass GitHub API entirely.
_test_ledger_lines: Optional[list[dict]] = None
_test_append_sink: Optional[list[dict]] = None


def _github_headers() -> dict:
    return {
        "Authorization": f"Bearer {LEDGER_GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _ledger_url() -> str:
    return f"https://api.github.com/repos/{LEDGER_REPO}/contents/{LEDGER_PREFIX}/ledger.jsonl"


def _read_ledger() -> tuple[list[dict], Optional[str]]:
    """Fetch JSONL from GitHub. Returns (lines, sha).

    Uses a module-level cache (refreshed every 5s).
    If _test_ledger_lines is set, returns that instead (for testing).
    """
    global _cache_lines, _cache_ts, _cache_sha

    if _test_ledger_lines is not None:
        return list(_test_ledger_lines), "test-sha"

    now = time.time()
    if _cache_lines is not None and (now - _cache_ts) < _CACHE_TTL:
        return list(_cache_lines), _cache_sha

    req = urllib.request.Request(_ledger_url(), headers=_github_headers())
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        content = base64.b64decode(data["content"]).decode("utf-8")
        sha = data["sha"]
        lines = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if line:
                lines.append(json.loads(line))
        _cache_lines = lines
        _cache_sha = sha
        _cache_ts = now
        return list(lines), sha
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # File doesn't exist yet
            _cache_lines = []
            _cache_sha = None
            _cache_ts = now
            return [], None
        raise


def _append_event(event: dict) -> bool:
    """Append a JSON event line to the ledger via GitHub Contents API.

    Returns True on success, False on 409 conflict (SHA mismatch).
    If _test_append_sink is set, appends there instead (for testing).
    """
    global _cache_lines, _cache_ts, _cache_sha

    if _test_append_sink is not None:
        _test_append_sink.append(event)
        # Also update the test ledger if it exists
        if _test_ledger_lines is not None:
            _test_ledger_lines.append(event)
        return True

    lines, sha = _read_ledger()
    new_line = json.dumps(event, separators=(",", ":"))

    if lines:
        # Reconstruct existing content and append
        existing_lines = [json.dumps(l, separators=(",", ":")) for l in lines]
        new_content = "\n".join(existing_lines) + "\n" + new_line + "\n"
    else:
        new_content = new_line + "\n"

    encoded = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
    body = {
        "message": f"ledger: {event.get('event', 'unknown')}",
        "content": encoded,
    }
    if sha:
        body["sha"] = sha

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        _ledger_url(),
        data=data,
        headers={**_github_headers(), "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            resp_data = json.loads(resp.read())
        # Update cache
        _cache_sha = resp_data["content"]["sha"]
        lines.append(event)
        _cache_lines = lines
        _cache_ts = time.time()
        return True
    except urllib.error.HTTPError as e:
        if e.code == 409:
            # SHA conflict — retry up to 3 times with fresh SHA
            _invalidate_cache()
            for _retry in range(3):
                time.sleep(0.5)
                lines, sha = _read_ledger()
                new_content = "\n".join(json.dumps(l) for l in lines + [event]) + "\n"
                encoded = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
                body = {"message": f"ledger: {event.get('event', 'unknown')}", "content": encoded}
                if sha:
                    body["sha"] = sha
                data = json.dumps(body).encode("utf-8")
                retry_req = urllib.request.Request(
                    _ledger_url(), data=data,
                    headers={**_github_headers(), "Content-Type": "application/json"},
                    method="PUT",
                )
                try:
                    with urllib.request.urlopen(retry_req) as resp:
                        resp_data = json.loads(resp.read())
                    _cache_sha = resp_data["content"]["sha"]
                    lines.append(event)
                    _cache_lines = lines
                    _cache_ts = time.time()
                    return True
                except urllib.error.HTTPError as retry_e:
                    if retry_e.code == 409:
                        _invalidate_cache()
                        continue
                    raise
            return False  # exhausted retries
        raise


def _invalidate_cache() -> None:
    global _cache_lines, _cache_ts, _cache_sha
    _cache_lines = None
    _cache_ts = 0.0
    _cache_sha = None
