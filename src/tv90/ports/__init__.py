"""Ports that domain and application depend on. Adapters implement these."""

from tv90.ports.clock import Clock
from tv90.ports.library import LibrarySource

__all__ = ["Clock", "LibrarySource"]
