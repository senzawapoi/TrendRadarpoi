"""Optional on-demand research; importing this package performs no I/O."""

from .adapter import ResearchAdapter
from .gateway import ResearchGateway
from .models import (
    CAPABILITIES,
    ResearchDocument,
    ResearchPolicy,
    ResearchRequest,
    ResearchResult,
)

__all__ = [
    "CAPABILITIES", "ResearchAdapter", "ResearchDocument", "ResearchGateway",
    "ResearchPolicy", "ResearchRequest", "ResearchResult",
]
