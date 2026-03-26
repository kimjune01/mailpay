# Trust Exchange Interface

The trust exchange is a mail server with a ledger. It receives DKIM-signed attestation emails, verifies signatures, and indexes them into a public graph. The theory is in [Proof of Trust](https://june.kim/proof-of-trust). The production implementation is in [vectorspace-adserver/trust/](https://github.com/kimjune01/vectorspace-adserver/tree/master/trust).

This file defines the interface. `Exchange` in `exchange.py` implements it in-memory for tests. In production, swap it for an HTTP client that talks to a running vectorspace-exchange instance.

## The contract

An exchange does five things:

1. **Accept attestations.** An attestor sends a DKIM-signed email claiming a relationship with a subject. Bilateral types (payment_processor, customer_endorsement, vendor_relationship) pend until the subject confirms. Unilateral types (platform_rating, license) create edges immediately.

2. **Accept confirmations.** The subject sends a separate DKIM-signed email referencing the attestation ID. The exchange matches the pair and creates a bilateral edge. Self-confirmation is rejected.

3. **Accept revocations.** Either party sends a revocation email. The edge is removed. The attestation ID is blocked from resubmission.

4. **Serve edges.** Curators pull the graph and build allowlists. The exchange serves edges by node or as a full graph. The HTTP API in vectorspace-exchange exposes `GET /trust/graph`, `GET /trust/node/{domain}`, `GET /trust/allowlist`.

5. **Answer trust checks.** The agent asks "does this sender have enough bilateral edges?" before accepting paid work. This is the bridge between `trust/` and `agent/`.

## Python interface

```python
class TrustExchange:
    def submit_attestation(self, attestation, dkim_verified=False) -> Edge | None
    def submit_confirmation(self, confirmation, dkim_verified=False) -> Edge | None
    def submit_revocation(self, revocation) -> bool
    def get_edges(self, node: str) -> list[Edge]
    def get_graph(self) -> list[Edge]
    def trust_check(self, sender: str, min_bilateral: int = 1) -> bool
```

## Implementations

| Implementation | Backing store | Use case |
|---------------|--------------|----------|
| `Exchange` (exchange.py) | In-memory dict | Tests, single-agent dev |
| `HTTPExchange` (future) | HTTP calls to vectorspace-exchange | Production, multi-agent |

The HTTP implementation maps directly to the vectorspace-exchange API:

| Method | HTTP equivalent |
|--------|----------------|
| `submit_attestation` | `POST /trust/attest` |
| `submit_confirmation` | `POST /trust/attest` (action: confirm) |
| `submit_revocation` | `POST /trust/attest` (action: revoke) |
| `get_edges` | `GET /trust/node/{domain}` |
| `get_graph` | `GET /trust/graph` |
| `trust_check` | `GET /trust/allowlist?min_bilateral=N` then check membership |

## Schema

The vectorspace-exchange uses SQLite with four tables:

- `attestations` — claims received, with DKIM verification status
- `trust_edges` — verified relationships (bilateral creates two edges, unilateral creates one)
- `ledger_log` — append-only audit trail of every action
- `publish_preferences` — field-level disclosure opt-in per subject

The full schema is in [TRUST_EXCHANGE.md](https://github.com/kimjune01/vectorspace-adserver/blob/master/TRUST_EXCHANGE.md).

## Edge weights

Weights are derived from attestation payload, not computed by the exchange. The exchange passes through what attestors claim. Curators interpret what it means.

- `duration_years`: weight = years (3 years → 3.0)
- `review_count`: weight = count / 100 (247 reviews → 2.47)
- Default: 1.0

## Why not reimplement in Python

The Go implementation in vectorspace-adserver is ~500 lines, has SQLite persistence, SMTP receiving with DKIM verification, and an HTTP API. Reimplementing it in Python would duplicate all of that for no gain. The right architecture: mailpay agents talk to the exchange over HTTP. The exchange is infrastructure, like a mail server. You run one, not one per agent.

The in-memory `Exchange` in `exchange.py` exists so tests don't need a running server. The interface is the same. The backing store is the only difference.
