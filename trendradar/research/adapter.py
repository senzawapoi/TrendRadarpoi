"""Provider boundary; concrete adapters must enforce the supplied I/O deadline."""

from abc import ABC, abstractmethod

from .models import ResearchRequest, ResearchResult


class ResearchAdapter(ABC):
    """Internal provider contract, never exposed directly to a model or transport."""

    @abstractmethod
    def research(
        self, request: ResearchRequest, *, timeout: float = 15, max_bytes: int = 262_144,
    ) -> ResearchResult:
        """Execute a fixed capability with bounded I/O and sanitized failures."""

    def search(self, query: str, *, source: str = "web", limit: int = 5,
               timeout: float = 15, max_bytes: int = 262_144) -> ResearchResult:
        return self.research(ResearchRequest(f"search_{source}", query=query, limit=limit),
                             timeout=timeout, max_bytes=max_bytes)

    def fetch(self, url: str, *, kind: str = "webpage", timeout: float = 15,
              max_bytes: int = 262_144) -> ResearchResult:
        capability = {"webpage": "read_webpage", "video": "get_video_transcript"}.get(kind, "")
        return self.research(ResearchRequest(capability, url=url),
                             timeout=timeout, max_bytes=max_bytes)
