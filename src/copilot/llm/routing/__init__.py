"""Adaptive multi-provider model routing (Groq and Gemini key pools, per-task policies)."""

from copilot.llm.routing.config import RouterConfig, load_router_config
from copilot.llm.routing.router import LLMRouter, LLMUnavailable, RouteResult

__all__ = ["LLMRouter", "LLMUnavailable", "RouteResult", "RouterConfig", "load_router_config"]
