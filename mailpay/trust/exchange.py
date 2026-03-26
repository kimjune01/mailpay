"""Trust exchange: receive attestation emails, verify DKIM, build graph."""

from __future__ import annotations

from dataclasses import dataclass, field

from mailpay.trust.models import Attestation, Confirmation, Revocation, Edge


@dataclass
class Exchange:
    """An append-only attestation ledger.

    Receives attestation emails, matches bilateral confirmations,
    processes revocations, and exposes the trust graph.
    """
    # Pending attestations awaiting bilateral confirmation
    _pending: dict[str, Attestation] = field(default_factory=dict)
    # Live edges in the graph
    _edges: dict[str, Edge] = field(default_factory=dict)
    # Revoked attestation IDs
    _revoked: set[str] = field(default_factory=set)

    def submit_attestation(self, attestation: Attestation, dkim_verified: bool = False) -> Edge | None:
        """Submit an attestation. Returns an Edge if unilateral or already confirmed."""
        if attestation.attestation_id in self._revoked:
            return None

        # Store as pending for bilateral confirmation
        self._pending[attestation.attestation_id] = attestation

        # Unilateral attestations create edges immediately
        # (platform_rating, license — subject doesn't confirm)
        if attestation.attestation_type in ("platform_rating", "license"):
            return self._create_edge(attestation, bilateral=False)

        return None

    def submit_confirmation(self, confirmation: Confirmation, dkim_verified: bool = False) -> Edge | None:
        """Submit a bilateral confirmation. Returns an Edge if the attestation exists."""
        att_id = confirmation.attestation_id
        if att_id in self._revoked:
            return None
        if att_id not in self._pending:
            return None

        attestation = self._pending[att_id]

        # Confirmer must be the subject (not the attestor confirming themselves)
        if confirmation.confirmer == attestation.attestor:
            return None

        attestation.confirmed = True
        return self._create_edge(attestation, bilateral=True)

    def submit_revocation(self, revocation: Revocation) -> bool:
        """Revoke an attestation. Either party can unlink."""
        att_id = revocation.attestation_id

        # Must be from attestor or subject
        if att_id in self._pending:
            att = self._pending[att_id]
            if revocation.revoker not in (att.attestor, att.subject):
                return False

        self._revoked.add(att_id)
        self._pending.pop(att_id, None)
        self._edges.pop(att_id, None)
        return True

    def _create_edge(self, attestation: Attestation, bilateral: bool) -> Edge:
        """Create and store a graph edge from an attestation."""
        # Build published fields
        fields = dict(attestation.standard_fields)
        for key in attestation.published_fields:
            if key in attestation.optional_fields:
                fields[key] = attestation.optional_fields[key]

        edge = Edge(
            source=attestation.attestor,
            target=attestation.subject,
            attestation_id=attestation.attestation_id,
            attestation_type=attestation.attestation_type,
            bilateral=bilateral,
            timestamp=attestation.timestamp,
            fields=fields,
        )
        self._edges[attestation.attestation_id] = edge
        return edge

    def get_edges(self, node: str) -> list[Edge]:
        """Get all edges involving a node (as source or target)."""
        return [
            e for e in self._edges.values()
            if e.source == node or e.target == node
        ]

    def get_graph(self) -> list[Edge]:
        """Get the full trust graph."""
        return list(self._edges.values())

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def trust_check(self, sender: str, min_bilateral: int = 1) -> bool:
        """Check if a sender has enough bilateral edges to be trusted.

        Used by agent/ before accepting paid work from an unknown sender.
        """
        edges = self.get_edges(sender)
        bilateral = [e for e in edges if e.bilateral]
        return len(bilateral) >= min_bilateral
