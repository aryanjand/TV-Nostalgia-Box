"""Port for listing local channel bumpers. Adapters implement this."""

from typing import Protocol


class InterstitialCatalog(Protocol):
    def filenames_for(self, channel_number: int) -> tuple[str, ...]:
        """Return media names for one channel. Unknown channel is empty."""
        ...
