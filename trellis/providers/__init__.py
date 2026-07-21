"""The model seat. Core imports no vendor SDK; adapters import theirs lazily.

Exporting the adapter CLASSES here is safe: `openai_compat` is pure stdlib and
`claude_sdk` defers its SDK import to `__init__` (so importing the class pulls in
nothing). `provider_from_env` is the config-driven selector — see factory.py.
"""

from .base import Provider, ProviderResponse, ToolCall, ProviderUnavailable
from .mock import MockProvider
from .openai_compat import OpenAICompatProvider
from .claude_sdk import ClaudeSDKProvider
from .factory import provider_from_env, VALID as PROVIDER_KINDS

__all__ = ["Provider", "ProviderResponse", "ToolCall", "ProviderUnavailable",
           "MockProvider", "OpenAICompatProvider", "ClaudeSDKProvider",
           "provider_from_env", "PROVIDER_KINDS"]
