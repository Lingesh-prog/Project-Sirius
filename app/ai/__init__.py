"""Provider-independent AI foundation for SIRIUS (Module 2.1).

Everything outside this package imports the abstraction from here; provider
SDKs are imported only inside app.ai.client.
"""

from app.ai.client import (
    AIClient,
    AIConfigurationError,
    AIError,
    AIProviderError,
    create_ai_client,
)

__all__ = [
    "AIClient",
    "AIError",
    "AIConfigurationError",
    "AIProviderError",
    "create_ai_client",
]