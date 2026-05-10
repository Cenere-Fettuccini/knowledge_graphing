"""Web search tool — Google Custom Search wrapper.

Requires two env vars:
    GOOGLE_API_KEY   — your existing Google API key (already used for Gemini)
    GOOGLE_CSE_ID    — Custom Search Engine ID from https://cse.google.com

Usage (CLI):
    python -m src.tools.search "latest AI research papers"
"""

import json
import logging
import sys

import requests

from src.core.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.googleapis.com/customsearch/v1"


def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Search the web and return a list of results with title, link, and snippet.

    Uses Google Custom Search API. Returns an error dict if not configured.
    """
    if not settings.google_cse_id:
        logger.warning("GOOGLE_CSE_ID not set — web search is unavailable.")
        return [{"error": "Web search not configured. Set GOOGLE_CSE_ID in your .env file."}]

    api_key = settings.google_api_key
    if not api_key:
        return [{"error": "No Google API key configured."}]

    params = {
        "key": api_key,
        "cx": settings.google_cse_id,
        "q": query,
        "num": min(max(1, num_results), 10),
    }

    try:
        resp = requests.get(_BASE_URL, params=params, timeout=10)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [
            {
                "title": item.get("title"),
                "link": item.get("link"),
                "snippet": item.get("snippet"),
            }
            for item in items
        ]
    except requests.HTTPError as e:
        logger.error("Google Custom Search HTTP error: %s", e)
        return [{"error": f"Search API error: {e}"}]
    except requests.RequestException as e:
        logger.error("Web search request failed: %s", e)
        return [{"error": f"Network error: {e}"}]
    except Exception as e:
        logger.error("Unexpected search error: %s", e)
        return [{"error": str(e)}]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    results = web_search(" ".join(sys.argv[1:]))
    print(json.dumps(results, indent=2))
