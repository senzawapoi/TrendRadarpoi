"""Lark international aliases for the compatibility-preserving transport."""

from trendradar.integrations.feishu import (
    FeishuInbound as LarkInbound,
)
from trendradar.integrations.feishu import (
    FeishuMediaPart as LarkMediaPart,
)
from trendradar.integrations.feishu import (
    FeishuReply as LarkReply,
)
from trendradar.integrations.feishu import (
    LarkConfig,
    SessionBinding,
    SessionMapper,
)

__all__ = [
    "LarkConfig",
    "LarkInbound",
    "LarkMediaPart",
    "LarkReply",
    "SessionBinding",
    "SessionMapper",
]
