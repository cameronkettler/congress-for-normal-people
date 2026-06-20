from dataclasses import dataclass

import httpx

from packages.shared.config import Settings, get_settings


@dataclass(frozen=True)
class SearchResult:
    title: str
    link: str
    snippet: str
    source: str = ""


class SerpApiClient:
    endpoint = "https://serpapi.com/search"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.serpapi_enabled and self.settings.serpapi_api_key)

    async def search(self, query: str, *, num: int | None = None) -> list[SearchResult]:
        if not self.enabled:
            return []

        limit = num or self.settings.rep_position_search_results
        try:
            async with httpx.AsyncClient(timeout=self.settings.serpapi_timeout_seconds) as client:
                response = await client.get(
                    self.endpoint,
                    params={
                        "engine": "google",
                        "q": query,
                        "api_key": self.settings.serpapi_api_key,
                        "num": limit,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return []

        return self._organic_results(response.json(), limit)

    def _organic_results(self, payload: dict[str, object], limit: int) -> list[SearchResult]:
        raw_results = payload.get("organic_results", [])
        if not isinstance(raw_results, list):
            return []

        results: list[SearchResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            link = str(item.get("link") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            if not title or not link:
                continue
            results.append(
                SearchResult(
                    title=title,
                    link=link,
                    snippet=snippet,
                    source=str(item.get("source") or item.get("displayed_link") or "").strip(),
                )
            )
            if len(results) >= limit:
                break
        return results
