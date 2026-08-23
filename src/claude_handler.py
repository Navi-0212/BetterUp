from src.gemini_handler import SYSTEM_PROMPT, GeminiHandler

# Alias ClaudeHandler to GeminiHandler so all existing code and imports work seamlessly
ClaudeHandler = GeminiHandler

__all__ = ["ClaudeHandler", "GeminiHandler", "SYSTEM_PROMPT"]
