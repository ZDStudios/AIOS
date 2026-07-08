"""
Claude Code API Gateway

A FastAPI-based service that provides OpenAI-compatible endpoints
while leveraging Claude Code's powerful workflow capabilities.
"""

__version__ = "1.0.0"
__author__ = "Claude Code API Team"
__description__ = "OpenAI-compatible API gateway for Claude Code with streaming support"

from .main import app

__all__ = ["app"]
