# Trust Exchange Interface

The trust exchange is a mail server with a ledger. It receives DKIM-signed attestation emails, verifies signatures, and indexes them into a public graph. The theory is in [Proof of Trust](https://june.kim/proof-of-trust). The production Go implementation is in [vectorspace-adserver/trust/](https://github.com/kimjune01/vectorspace-adserver/tree/master/trust) — it diverges from the theory in places noted below.

## The contract

An exchange does four things. Policy decisions (who to trust, what thresholds to apply) belong to curators, not the exchange.

1. **Accept attestations via DKIM-signed email.** The exchange is an SMTP server. Attestors send directly to `attestations@exchange.domain`. The exchange verifies DKIM, parses the JSON body, and writes to the ledger. DKIM verification is transport-derived — never a caller-supplied parameter. HTTP submission exists for dev/testing only.

2. **Match bilateral confirmations.** The subject sends a separate DKIM-signed email referencing the attestation ID. The exchange matches the pair and creates two directed edges (A→B and B→A). Self-confirmation is rejected: if the attestor and subject share a domain, the confirmation must come from a different domain. Unilateral types (platform_rating, license) create one directed edge immediately.

3. **Process revocations.** Either party sends a revocation email. Both directed edges are removed. Duplicate attestation IDs are rejected (primary key constraint), whether revoked or not.

4. **Serve the graph.** The exchange exposes the current edge set and the append-only log. Curators sync the log to build their own indexes. The exchange passes through what attestors claim. It does not compute weights or interpret trust — that's the curator's job.

## Read surfaces

```python
get_edges(domain: str) -> list[Edge]      # all edges involving a domain
get_graph() -> list[Edge]                  # full edge set
get_attestation(id: str) -> Attestation    # single attestation by ID
get_log(limit: int, since: int) -> list    # append-only log for curator sync
```

## Write surfaces

Production writes arrive as DKIM-signed SMTP. The Python interface abstracts this:

```python
submit_attestation(attestation) -> list[Edge]   # returns created edges (0 for bilateral pending, 1 for unilateral, 2 for pre-confirmed)
submit_confirmation(confirmation) -> list[Edge]  # returns 2 directed edges on success
submit_revocation(revocation) -> bool
```

## Node identity

Graph nodes are **domains**, not email addresses. `merchant@example.com` becomes node `example.com`. The exchange normalizes on ingestion. Edge queries, graph queries, and allowlists all operate on domains.

## Edge model

A bilateral attestation creates **two directed edges**: `stripe.com → example.com` and `example.com → stripe.com`. A unilateral attestation creates **one directed edge**: `google.com → example.com`. Edge counts reflect directed edges, not attestation counts.

Edges carry:
- `attestation_id`, `attestation_type`, `kind` (bilateral/unilateral)
- `from_domain`, `to_domain`
- `timestamp`
- `fields` (the published subset of the attestation payload)

Edges do **not** carry computed weights. The exchange stores what attestors claim. Curators compute weights from the fields using their own criteria.

## Attestation types

Canonical set: `payment_processor`, `platform_rating`, `customer_endorsement`, `vendor_relationship`, `license`.

Unknown types are accepted and passed through. Attestors extend with URI-prefixed types (e.g. `https://stripe.com/attestation/payment_processing`). Curators normalize across synonyms. No central registry governs the vocabulary.

| Type | Edge kind | Confirmation required |
|------|-----------|----------------------|
| `payment_processor` | bilateral | Yes — both parties send |
| `customer_endorsement` | bilateral | Yes |
| `vendor_relationship` | bilateral | Yes |
| `platform_rating` | unilateral | No — edge created immediately |
| `license` | unilateral | No — licensing authority attests directly |

## What the exchange does NOT do

- **Compute trust scores.** That's the curator's job.
- **Compute edge weights.** Curators derive weights from attestation fields.
- **Enforce publish preferences.** Theory describes opt-in field publication but it's not enforced in production yet. When implemented, the exchange filters fields on read based on the subject's preferences.
- **Make policy decisions.** "Is this sender trusted?" is a curator/publisher question, not an exchange question. The exchange serves edges. Curators build allowlists.

## Implementations

| Implementation | Backing store | Use case |
|---------------|--------------|----------|
| `Exchange` (exchange.py) | In-memory dict | Tests, single-agent dev |
| vectorspace-exchange (Go) | SQLite + SMTP + HTTP API | Production, multi-agent |

To plug in the production exchange, replace in-memory dict operations with HTTP calls:

| Read method | HTTP call |
|-------------|-----------|
| `get_edges(domain)` | `GET /trust/node/{domain}` |
| `get_graph()` | `GET /trust/graph` |
| `get_attestation(id)` | `GET /trust/attestation/{id}` |
| `get_log(limit, since)` | `GET /trust/log?limit=N` |

Write operations in production go through SMTP, not HTTP. The `POST /trust/attest` endpoint is dev-only.

## Known divergences in vectorspace-adserver

The Go implementation diverges from this spec in several places:

- **Weights computed by exchange.** `computeWeight()` derives weights from `duration_years` and `review_count`. Theory says the exchange passes through; curators interpret. The Go code should move weight computation to the curator/query layer.
- **`license` treated as bilateral.** Theory and this spec say license is unilateral. Go only special-cases `platform_rating`.
- **Self-confirmation not rejected.** Go checks that the confirmer's domain matches the subject's domain, but doesn't check that attestor ≠ subject. Same-domain self-attestations can create self-loop edges.
- **Publish preferences stored but not enforced.** `SetPublishPreference` writes to the database but reads don't filter by it.
- **No cursor-based sync.** `GET /trust/log` accepts `limit` but no `since` parameter. Curators can't efficiently sync incrementally.

These are bugs in the Go implementation, not in the spec.
