"""Trust exchange: in-memory implementation (toy). Swap for HTTP client in production."""

from __future__ import annotations

from dataclasses import dataclass, field

from mailpay.trust.models import (
    Attestation, Confirmation, Revocation, Edge, domain_from_email,
)

# Unilateral types create edges immediately without subject confirmation
_UNILATERAL_TYPES = {"platform_rating", "license"}


@dataclass
class Exchange:
    """An append-only attestation ledger.

    Nodes are domains, not email addresses. Bilateral attestations create
    two directed edges. The exchange does not compute weights or trust
    scores — that's the curator's job.
    """
    _pending: dict[str, Attestation] = field(default_factory=dict)
    _edges: list[Edge] = field(default_factory=list)
    _attestation_ids: set[str] = field(default_factory=set)  # all seen IDs (PK constraint)
    _log: list[dict] = field(default_factory=list)

    def submit_attestation(self, attestation: Attestation) -> list[Edge]:
        """Submit an attestation. Returns created edges (empty for bilateral pending)."""
        att_id = attestation.attestation_id
        if att_id in self._attestation_ids:
            return []

        self._attestation_ids.add(att_id)
        self._pending[att_id] = attestation
        self._log.append({"action": "attestation", "id": att_id, "attestor": attestation.attestor})

        if attestation.attestation_type in _UNILATERAL_TYPES:
            edges = self._create_edges(attestation, kind="unilateral")
            return edges

        return []

    def submit_confirmation(self, confirmation: Confirmation) -> list[Edge]:
        """Submit a bilateral confirmation. Returns two directed edges on success."""
        att_id = confirmation.attestation_id
        if att_id not in self._pending:
            return []

        attestation = self._pending[att_id]

        # Reject self-confirmation: confirmer domain must differ from attestor domain
        attestor_domain = domain_from_email(attestation.attestor)
        confirmer_domain = domain_from_email(confirmation.confirmer)
        if confirmer_domain == attestor_domain:
            return []

        attestation.confirmed = True
        self._log.append({"action": "confirm", "id": att_id, "confirmer": confirmation.confirmer})
        return self._create_edges(attestation, kind="bilateral")

    def submit_revocation(self, revocation: Revocation) -> bool:
        """Revoke an attestation. Either party can unlink."""
        att_id = revocation.attestation_id

        if att_id in self._pending:
            att = self._pending[att_id]
            revoker_domain = domain_from_email(revocation.revoker)
            attestor_domain = domain_from_email(att.attestor)
            subject_domain = domain_from_email(att.subject)
            if revoker_domain not in (attestor_domain, subject_domain):
                return False

        self._pending.pop(att_id, None)
        self._edges = [e for e in self._edges if e.attestation_id != att_id]
        self._log.append({"action": "revoke", "id": att_id, "revoker": revocation.revoker})
        return True

    def _create_edges(self, attestation: Attestation, kind: str) -> list[Edge]:
        """Create directed edges from an attestation."""
        fields = dict(attestation.standard_fields)
        for key in attestation.published_fields:
            if key in attestation.optional_fields:
                fields[key] = attestation.optional_fields[key]

        attestor_domain = domain_from_email(attestation.attestor)
        subject_domain = domain_from_email(attestation.subject)

        edges = []
        if kind == "bilateral":
            # Two directed edges
            for from_d, to_d in [(attestor_domain, subject_domain), (subject_domain, attestor_domain)]:
                edge = Edge(
                    from_domain=from_d,
                    to_domain=to_d,
                    attestation_id=attestation.attestation_id,
                    attestation_type=attestation.attestation_type,
                    kind="bilateral",
                    timestamp=attestation.timestamp,
                    fields=fields,
                )
                self._edges.append(edge)
                edges.append(edge)
        else:
            # One directed edge
            edge = Edge(
                from_domain=attestor_domain,
                to_domain=subject_domain,
                attestation_id=attestation.attestation_id,
                attestation_type=attestation.attestation_type,
                kind="unilateral",
                timestamp=attestation.timestamp,
                fields=fields,
            )
            self._edges.append(edge)
            edges.append(edge)

        return edges

    def get_edges(self, domain: str) -> list[Edge]:
        """Get all edges involving a domain (as source or target)."""
        return [
            e for e in self._edges
            if e.from_domain == domain or e.to_domain == domain
        ]

    def get_graph(self) -> list[Edge]:
        """Get the full edge set."""
        return list(self._edges)

    def get_attestation(self, att_id: str) -> Attestation | None:
        """Get a single attestation by ID."""
        return self._pending.get(att_id)

    def get_log(self, limit: int = 100, since: int = 0) -> list[dict]:
        """Get append-only log entries for curator sync."""
        return self._log[since:][:limit]

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    @property
    def pending_count(self) -> int:
        return len([a for a in self._pending.values() if not a.confirmed])
