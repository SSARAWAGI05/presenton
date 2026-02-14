import asyncio
import aiohttp
from typing import List, Dict


class AgenticResearchService:
    """
    Multi-source async research service.

    Sources:
    - Tavily (web search)
    - Wikipedia
    - Archive.org (research papers metadata)

    Returns:
    {
        "summary": "<LLM injectable research context>",
        "sources": [
            {"title": "...", "url": "..."},
            ...
        ]
    }
    """

    # 🔐 PUT YOUR REAL TAVILY KEY HERE
    TAVILY_API_KEY = "YOUR_TAVILY_API_KEY_HERE"

    # -------------------------------------------------------
    # PUBLIC ENTRYPOINT
    # -------------------------------------------------------
    async def run(self, query: str) -> Dict:
        """
        Run parallel research safely.
        """

        results = await asyncio.gather(
            self.search_tavily(query),
            self.search_wikipedia(query),
            self.search_archive(query),
            return_exceptions=True,
        )

        collected_results: List[Dict] = []

        for result in results:
            if isinstance(result, list):
                collected_results.extend(result)

        # Remove duplicates by URL
        unique_results = {}
        for item in collected_results:
            url = item.get("url", "")
            if url and url not in unique_results:
                unique_results[url] = item

        final_results = list(unique_results.values())

        if not final_results:
            return {
                "summary": "",
                "sources": []
            }

        # Build LLM summary context
        research_blocks = []

        for item in final_results:
            title = item.get("title", "")
            content = item.get("content", "")
            url = item.get("url", "")

            block = (
                f"Title: {title}\n"
                f"Content: {content}\n"
                f"Source: {url}\n"
            )
            research_blocks.append(block)

        summary_text = "\n\n".join(research_blocks)

        # Build structured source list
        sources = [
            {
                "title": item.get("title", "Unknown Source"),
                "url": item.get("url", "")
            }
            for item in final_results
        ]

        return {
            "summary": summary_text,
            "sources": sources
        }

    # -------------------------------------------------------
    # TAVILY SEARCH
    # -------------------------------------------------------
    async def search_tavily(self, query: str) -> List[Dict]:
        if not self.TAVILY_API_KEY:
            return []

        url = "https://api.tavily.com/search"

        payload = {
            "api_key": self.TAVILY_API_KEY,
            "query": query,
            "search_depth": "advanced",
            "include_answer": False,
            "max_results": 5,
        }

        try:
            timeout = aiohttp.ClientTimeout(total=20)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as response:
                    if response.status != 200:
                        return []

                    data = await response.json()

            results = []

            for item in data.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "content": item.get("content", ""),
                    "url": item.get("url", "")
                })

            return results

        except Exception as e:
            print(f"[Tavily Error] {str(e)}")
            return []

    # -------------------------------------------------------
    # WIKIPEDIA SEARCH
    # -------------------------------------------------------
    async def search_wikipedia(self, query: str) -> List[Dict]:
        try:
            search_url = (
                "https://en.wikipedia.org/w/api.php"
                "?action=query"
                "&list=search"
                "&srsearch=" + query.replace(" ", "%20") +
                "&format=json"
            )

            timeout = aiohttp.ClientTimeout(total=15)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(search_url) as response:
                    if response.status != 200:
                        return []

                    data = await response.json()

            search_results = data.get("query", {}).get("search", [])

            results = []

            for item in search_results[:3]:
                title = item.get("title", "")

                snippet = (
                    item.get("snippet", "")
                    .replace('<span class="searchmatch">', "")
                    .replace("</span>", "")
                )

                page_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"

                results.append({
                    "title": title,
                    "content": snippet,
                    "url": page_url
                })

            return results

        except Exception as e:
            print(f"[Wikipedia Error] {str(e)}")
            return []

    # -------------------------------------------------------
    # ARCHIVE.ORG SEARCH (Research Papers Metadata)
    # -------------------------------------------------------
    async def search_archive(self, query: str) -> List[Dict]:
        try:
            archive_url = (
                "https://archive.org/advancedsearch.php"
                f"?q={query.replace(' ', '%20')}"
                "&fl[]=identifier,title,description"
                "&rows=3"
                "&page=1"
                "&output=json"
            )

            timeout = aiohttp.ClientTimeout(total=15)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(archive_url) as response:
                    if response.status != 200:
                        return []

                    data = await response.json()

            docs = data.get("response", {}).get("docs", [])

            results = []

            for item in docs:
                identifier = item.get("identifier", "")
                title = item.get("title", "Archive Document")
                description = item.get("description", "")

                page_url = f"https://archive.org/details/{identifier}"

                results.append({
                    "title": title,
                    "content": str(description)[:500],
                    "url": page_url
                })

            return results

        except Exception as e:
            print(f"[Archive Error] {str(e)}")
            return []
