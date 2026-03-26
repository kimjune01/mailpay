# trust/ — Trust Graph (Proof of Trust)

## What it does
Attestation exchange and curation layer. Businesses attest to relationships via DKIM-signed emails. Curators filter the graph into allowlists. Agents query trust before accepting paid requests.

## API

### Models
- `Attestation(attestation_id, attestation_type, subject, attestor, timestamp, standard_fields, optional_fields, published_fields)` — serializes to email body JSON
- `Confirmation(attestation_id, confirmer)` — bilateral confirmation
- `Revocation(attestation_id, revoker, reason, timestamp)` — either party unlinks
- `Edge(source, target, attestation_id, attestation_type, bilateral, timestamp, fields)` — graph edge

### Exchange
- `submit_attestation(att) → Edge | None` — unilateral types create edge immediately; bilateral types pend
- `submit_confirmation(conf) → Edge | None` — completes bilateral attestation
- `submit_revocation(rev) → bool` — removes edge, blocks resubmission
- `get_edges(node) → list[Edge]` — all edges for a node
- `get_graph() → list[Edge]` — full graph

### Curator
- `require(criterion)` — add a filter criterion
- `evaluate(exchange) → set[str]` — allowed nodes
- Built-in criteria: `has_payment_history`, `has_min_endorsements`, `has_platform_rating`, `has_bilateral_edges`

## Contracts
- Bilateral attestations require both parties to send directly (no self-confirmation)
- Revoked attestations cannot be resubmitted
- Either party can revoke unilaterally
- Curators compose criteria with AND logic
- Unilateral types: platform_rating, license
- Bilateral types: payment_processor, customer_endorsement, vendor_relationship

## Missing (to implement)
- Persistent ledger (currently in-memory dict)
- HTTPS feed for curators to sync (append-only log)
- DKIM verification on attestation emails (currently trust parameter)
- Attestation type registry / URI-prefixed extensions
- Timestamp-based edge weighting in curators
- Integration with agent/ (query trust before accepting work)
