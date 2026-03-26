"""Trust layer models from the Proof of Trust spec."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Attestation:
    """A signed trust claim sent via DKIM-signed email.

    Bilateral: both parties send to exchange, matched by attestation_id.
    Unilateral: platform attests about a subject without confirmation.
    """
    attestation_id: str
    attestation_type: str  # payment_processor, platform_rating, customer_endorsement, vendor_relationship, license
    subject: str  # email address of the entity being attested
    attestor: str  # email address of the attesting party
    timestamp: str  # ISO 8601

    # Standard fields (always public)
    standard_fields: dict[str, Any] = field(default_factory=dict)
    # Optional fields (merchant opts in to publish)
    optional_fields: dict[str, Any] = field(default_factory=dict)
    # Which optional fields the subject has opted to publish
    published_fields: list[str] = field(default_factory=list)

    # Confirmation state
    confirmed: bool = False  # True when bilateral confirmation received
    revoked: bool = False

    def to_email_body(self) -> str:
        """Serialize for inclusion in a DKIM-signed email body."""
        payload: dict[str, Any] = {
            "attestation_type": self.attestation_type,
            "attestation_id": self.attestation_id,
            "subject": self.subject,
            "timestamp": self.timestamp,
        }
        payload.update(self.standard_fields)
        # Only include opted-in optional fields
        for key in self.published_fields:
            if key in self.optional_fields:
                payload[key] = self.optional_fields[key]
        return json.dumps(payload, indent=2)

    @classmethod
    def from_email_body(cls, raw: str, attestor: str = "") -> Attestation:
        """Parse from an email body JSON payload."""
        data = json.loads(raw)
        return cls(
            attestation_id=data.get("attestation_id", ""),
            attestation_type=data.get("attestation_type", ""),
            subject=data.get("subject", ""),
            attestor=attestor,
            timestamp=data.get("timestamp", ""),
            standard_fields={
                k: v for k, v in data.items()
                if k not in ("attestation_type", "attestation_id", "subject", "timestamp")
            },
        )


@dataclass
class Confirmation:
    """A bilateral confirmation referencing an attestation_id."""
    attestation_id: str
    confirmer: str  # email address of the confirming party

    def to_email_body(self) -> str:
        return json.dumps({
            "action": "confirm",
            "attestation_id": self.attestation_id,
        }, indent=2)

    @classmethod
    def from_email_body(cls, raw: str, confirmer: str = "") -> Confirmation:
        data = json.loads(raw)
        return cls(
            attestation_id=data.get("attestation_id", ""),
            confirmer=confirmer,
        )


@dataclass
class Revocation:
    """Either party can unlink by sending a revocation."""
    attestation_id: str
    revoker: str  # email address of the revoking party
    reason: str = ""
    timestamp: str = ""

    def to_email_body(self) -> str:
        return json.dumps({
            "action": "revoke",
            "attestation_id": self.attestation_id,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }, indent=2)

    @classmethod
    def from_email_body(cls, raw: str, revoker: str = "") -> Revocation:
        data = json.loads(raw)
        return cls(
            attestation_id=data.get("attestation_id", ""),
            revoker=revoker,
            reason=data.get("reason", ""),
            timestamp=data.get("timestamp", ""),
        )


def domain_from_email(email: str) -> str:
    """Extract domain from email address. If no @, treat as domain."""
    at = email.rfind("@")
    return email[at + 1:] if at >= 0 else email


@dataclass
class Edge:
    """A directed edge in the trust graph between two domain nodes.

    Bilateral attestations create two edges (A→B and B→A).
    Unilateral attestations create one edge (attestor→subject).
    """
    from_domain: str
    to_domain: str
    attestation_id: str
    attestation_type: str
    kind: str = "bilateral"  # "bilateral" or "unilateral"
    timestamp: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
