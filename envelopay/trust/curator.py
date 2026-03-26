"""Trust curator: pull exchange graph, apply criteria, publish allowlists."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from envelopay.trust.exchange import Exchange
from envelopay.trust.models import Edge


# A criterion is a function that takes a list of edges for a node and returns True/False
Criterion = Callable[[list[Edge]], bool]


@dataclass
class Curator:
    """A trust curator that filters the exchange graph into an allowlist.

    Curators compete on criteria quality. Publishers subscribe to curators
    whose standards match their audience. The exchange serves edges;
    curators interpret them.
    """
    name: str
    _criteria: list[Criterion] = field(default_factory=list)

    def require(self, criterion: Criterion) -> None:
        """Add a requirement. All criteria must pass for a node to be allowed."""
        self._criteria.append(criterion)

    def evaluate(self, exchange: Exchange) -> set[str]:
        """Pull the exchange graph and return the set of allowed domains."""
        nodes: set[str] = set()
        for edge in exchange.get_graph():
            nodes.add(edge.from_addr)
            nodes.add(edge.to_addr)

        allowed: set[str] = set()
        for node in nodes:
            edges = exchange.get_edges(node)
            if all(c(edges) for c in self._criteria):
                allowed.add(node)

        return allowed


# --- Built-in criteria ---

def has_payment_history(min_years: int = 1) -> Criterion:
    """Require at least one bilateral payment_processor edge with sufficient duration."""
    def check(edges: list[Edge]) -> bool:
        for e in edges:
            if e.attestation_type == "payment_processor" and e.kind == "bilateral":
                duration = e.fields.get("duration_years", 0)
                if duration >= min_years:
                    return True
        return False
    return check


def has_min_endorsements(count: int = 3) -> Criterion:
    """Require at least N bilateral customer endorsement edges."""
    def check(edges: list[Edge]) -> bool:
        endorsements = [
            e for e in edges
            if e.attestation_type == "customer_endorsement" and e.kind == "bilateral"
        ]
        return len(endorsements) >= count
    return check


def has_platform_rating(min_rating: float = 4.0) -> Criterion:
    """Require at least one platform rating above threshold."""
    def check(edges: list[Edge]) -> bool:
        for e in edges:
            if e.attestation_type == "platform_rating":
                rating = e.fields.get("rating", 0)
                if rating >= min_rating:
                    return True
        return False
    return check


def edges_within_age(max_age_days: int = 365) -> Criterion:
    """Require at least one edge newer than max_age_days."""
    def check(edges: list[Edge]) -> bool:
        now = datetime.now(timezone.utc)
        for e in edges:
            if not e.timestamp:
                continue
            try:
                ts = datetime.fromisoformat(e.timestamp.replace("Z", "+00:00"))
                age = (now - ts).days
                if age <= max_age_days:
                    return True
            except (ValueError, TypeError):
                continue
        return False
    return check


def has_bilateral_edges(min_count: int = 1) -> Criterion:
    """Require at least N bilateral (mutually confirmed) directed edges."""
    def check(edges: list[Edge]) -> bool:
        bilateral = [e for e in edges if e.kind == "bilateral"]
        return len(bilateral) >= min_count
    return check
