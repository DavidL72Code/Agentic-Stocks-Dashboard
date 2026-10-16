"""Importing this package registers every tool via the @tool decorator."""
from . import events, fundamentals, history, macro, market, portfolio, relations, screener, street  # noqa: F401
from .registry import DOMAIN_DESC, TOOLS, Tool, catalog, domain_tools  # noqa: F401
