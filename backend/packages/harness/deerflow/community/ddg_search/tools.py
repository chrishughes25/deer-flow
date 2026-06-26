"""
Web Search Tool - Search the web using DuckDuckGo (no API key required).
"""

import json
import logging
import os

from langchain.tools import tool

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

# AlphaFRS tuning — web search must be fast and skip flaky engines.
#
#   * timeout: ddgs' default 30s lets one stalled engine block the whole
#     research step. A short cap means a slow / captcha-walled engine fails
#     fast instead of hanging.
#   * region: the default "wt-wt" makes ddgs' Wikipedia engine build a
#     non-existent host (wt.wikipedia.org) out of the region's language code.
#     "us-en" resolves it to the real en.wikipedia.org.
#   * backends: restrict to fast, dependable engines. Wikipedia (bad host) and
#     Mojeek (captcha walls / timeouts) were the repeat offenders in prod, so
#     they are excluded. Override the allow-list via DEERFLOW_SEARCH_BACKENDS
#     (comma-separated) to blacklist a newly-failing engine without a redeploy.
_SEARCH_TIMEOUT = float(os.getenv("DEERFLOW_SEARCH_TIMEOUT", "5"))
_SEARCH_REGION = os.getenv("DEERFLOW_SEARCH_REGION", "us-en")
_SEARCH_BACKENDS = os.getenv("DEERFLOW_SEARCH_BACKENDS", "duckduckgo, google, bing, brave")


def _search_text(
    query: str,
    max_results: int = 5,
    region: str = _SEARCH_REGION,
    safesearch: str = "moderate",
) -> list[dict]:
    """
    Execute text search using DuckDuckGo.

    Args:
        query: Search keywords
        max_results: Maximum number of results
        region: Search region
        safesearch: Safe search level

    Returns:
        List of search results
    """
    try:
        from ddgs import DDGS
    except ImportError:
        logger.error("ddgs library not installed. Run: pip install ddgs")
        return []

    ddgs = DDGS(timeout=_SEARCH_TIMEOUT)

    def _run(backend: str | None) -> list[dict]:
        kwargs = {"region": region, "safesearch": safesearch, "max_results": max_results}
        if backend:
            kwargs["backend"] = backend
        results = ddgs.text(query, **kwargs)
        return list(results) if results else []

    try:
        return _run(_SEARCH_BACKENDS)
    except Exception as e:
        # An unsupported engine name in the allow-list would otherwise kill every
        # search — fall back to ddgs' default engines (still fast: short timeout).
        logger.warning("web_search backend allow-list failed (%s); retrying with default engines", e)
        try:
            return _run(None)
        except Exception as e2:
            logger.error(f"Failed to search web: {e2}")
            return []


@tool("web_search", parse_docstring=True)
def web_search_tool(
    query: str,
    max_results: int = 5,
) -> str:
    """Search the web for information. Use this tool to find current information, news, articles, and facts from the internet.

    Args:
        query: Search keywords describing what you want to find. Be specific for better results.
        max_results: Maximum number of results to return. Default is 5.
    """
    config = get_app_config().get_tool_config("web_search")

    # Override max_results from config if set
    if config is not None and "max_results" in config.model_extra:
        max_results = config.model_extra.get("max_results", max_results)

    results = _search_text(
        query=query,
        max_results=max_results,
    )

    if not results:
        return json.dumps({"error": "No results found", "query": query}, ensure_ascii=False)

    normalized_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("href", r.get("link", "")),
            "content": r.get("body", r.get("snippet", "")),
        }
        for r in results
    ]

    output = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }

    return json.dumps(output, indent=2, ensure_ascii=False)
