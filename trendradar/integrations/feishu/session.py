"""Identity authorization and stable Assistant session mapping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trendradar.ai.session import SessionStore

from .config import FeishuConfig
from .models import FeishuInbound, stable_digest


@dataclass(frozen=True, slots=True)
class SessionBinding:
    principal_id: str
    session_id: str
    identity_field: str


class SessionMapper:
    """Match configured identity fields before any content or provider work."""

    def __init__(self, config: FeishuConfig) -> None:
        self.config = config

    def authorize(self, event: FeishuInbound) -> SessionBinding | None:
        if event.chat_type not in self.config.allowed_chat_types:
            return None
        for field, accepted in self.config.identity_fields:
            value = event.identity.get(field)
            if value and value in accepted:
                principal = f"feishu:{stable_digest(field, value)}"
                session = f"feishu:{stable_digest(principal, event.chat_type, event.chat_id)}"
                return SessionBinding(principal, session, field)
        return None

    @staticmethod
    def ensure_session(store: SessionStore, binding: SessionBinding, now: datetime) -> None:
        store.open_session(binding.principal_id, binding.session_id, now=now)


__all__ = ["SessionBinding", "SessionMapper"]
