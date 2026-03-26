"""Trust exchange: in-memory implementation (toy). Swap for HTTP client in production."""

from __future__ import annotations

from dataclasses import dataclass, field

from envelopay.trust.models import Attestation, Confirmation, Revocation, Edge

# Unilateral types create edges immediately without subject confirmation
_UNILATERAL_TYPES = {"platform_rating", "license"}


@dataclass
class Exchange:
    """An append-only attestation ledger.

    Nodes are canonical email addresses. Bilateral attestations create
    two directed edges. The exchange does not compute weights or trust
    scores — that's the curator's job.
    """
    _pending: dict[str, Attestation] = field(default_factory=dict)
    _edges: list[Edge] = field(default_factory=list)
    _attestation_ids: set[str] = field(default_factory=set)
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
            return self._create_edges(attestation, kind="unilateral")

        return []

    def submit_confirmation(self, confirmation: Confirmation) -> list[Edge]:
        """Submit a bilateral confirmation. Returns two directed edges on success."""
        att_id = confirmation.attestation_id
        if att_id not in self._pending:
            return []

        attestation = self._pending[att_id]

        # Confirmer must not be the attestor
        if confirmation.confirmer == attestation.attestor:
            return []

        attestation.confirmed = True
        self._log.append({"action": "confirm", "id": att_id, "confirmer": confirmation.confirmer})
        return self._create_edges(attestation, kind="bilateral")

    def submit_revocation(self, revocation: Revocation) -> bool:
        """Revoke an attestation. Either party can unlink."""
        att_id = revocation.attestation_id

        if att_id in self._pending:
            att = self._pending[att_id]
            if revocation.revoker not in (att.attestor, att.subject):
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

        edges = []
        if kind == "bilateral":
            for from_a, to_a in [(attestation.attestor, attestation.subject),
                                  (attestation.subject, attestation.attestor)]:
                edge = Edge(
                    from_addr=from_a, to_addr=to_a,
                    attestation_id=attestation.attestation_id,
                    attestation_type=attestation.attestation_type,
                    kind="bilateral", timestamp=attestation.timestamp,
                    fields=fields,
                )
                self._edges.append(edge)
                edges.append(edge)
        else:
            edge = Edge(
                from_addr=attestation.attestor, to_addr=attestation.subject,
                attestation_id=attestation.attestation_id,
                attestation_type=attestation.attestation_type,
                kind="unilateral", timestamp=attestation.timestamp,
                fields=fields,
            )
            self._edges.append(edge)
            edges.append(edge)

        return edges

    def get_edges(self, addr: str) -> list[Edge]:
        """Get all edges involving an email address."""
        return [e for e in self._edges if e.from_addr == addr or e.to_addr == addr]

    def get_graph(self) -> list[Edge]:
        """Get the full edge set."""
        return list(self._edges)

    def get_attestation(self, att_id: str) -> Attestation | None:
        return self._pending.get(att_id)

    def get_log(self, limit: int = 100, since: int = 0) -> list[dict]:
        return self._log[since:][:limit]

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    @property
    def pending_count(self) -> int:
        return len([a for a in self._pending.values() if not a.confirmed])
