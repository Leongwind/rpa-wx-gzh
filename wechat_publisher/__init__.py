"""微信公众号文章发布器。

The public API intentionally stays small so it can later be wrapped by an MCP
server without duplicating browser or API logic.
"""

from .models import Article, Asset, PublishResult, PublishStatus
from .publisher import AutoPublisher, publish

__all__ = [
    "Article",
    "Asset",
    "AutoPublisher",
    "PublishResult",
    "PublishStatus",
    "publish",
]
