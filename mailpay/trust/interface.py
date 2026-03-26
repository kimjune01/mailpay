"""Trust exchange interface. Implementations: MemoryExchange (toy), HTTPExchange (vectorspace)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from mailpay.trust.models import Attestation, Confirmation, Revocation, Edge


class TrustExchange(ABC):
    """Abstract trust exchange. Two implementations:

    - MemoryExchange: in-memory dict, good for tests and single-agent dev
    - HTTPExchange: calls a vectorspace-exchange over HTTP (GET /trust/*)

    The agent doesn't care which one backs it.
    """

    @abstractmethod
    def submit_attestation(self, attestation: Attestation, dkim_verified: bool = False) -> Edge | None: ...

    @abstractmethod
    def submit_confirmation(self, confirmation: Confirmation, dkim_verified: bool = False) -> Edge | None: ...

    @abstractmethod
    def submit_revocation(self, revocation: Revocation) -> bool: ...

    @abstractmethod
    def get_edges(self, node: str) -> list[Edge]: ...

    @abstractmethod
    def get_graph(self) -> list[Edge]: ...

    @abstractmethod
    def trust_check(self, sender: str, min_bilateral: int = 1) -> bool: ...

    @property
    @abstractmethod
    def edge_count(self) -> int: ...
