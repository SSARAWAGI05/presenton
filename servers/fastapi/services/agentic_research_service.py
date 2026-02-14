import asyncio
import aiohttp
import wikipedia
import arxiv
from typing import TypedDict, Optional
from langgraph.graph import StateGraph

# ============================================================
# 🔐 HARD-CODED CONFIGURATION (PUT YOUR KEYS HERE)
# ============================================================

TAVILY_API_KEY = "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"

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b-instruct-q4_0"

# ============================================================
# LIMITS (token protection)
# ============================================================

MAX_WEB_RESULTS = 5
MAX_WIKI_CHARS = 3000
MAX_ARXIV_RESULTS = 3
MAX_COMBINED_CHARS = 15000
MAX_FINAL_CONTEXT_CHARS = 8000


# ============================================================
# STATE DEFINITION
# ============================================================

class ResearchState(TypedDict):
    query: str
    web_results: Optional[str]
    wiki_results: Optional[str]
    arxiv_results: Optional[str]
    final_context: Optional[str]


# ============================================================
# TOOL 1 — WEB SEARCH (Tavily)
# ============================================================

async def web_search(query: str) -> str:
    url = "https://api.tavily.com/search"

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": MAX_WEB_RESULTS,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json()
    except Exception:
        return ""

    results = []
    for r in data.get("results", []):
        results.append(
            f"Title: {r.get('title')}\n"
            f"Content: {r.get('content')}\n"
        )

    return "\n\n".join(results)


# ============================================================
# TOOL 2 — WIKIPEDIA
# ============================================================

async def wiki_search(query: str) -> str:
    try:
        page = wikipedia.page(query, auto_suggest=True)
        content = page.content[:MAX_WIKI_CHARS]
        return f"Wikipedia Summary:\n{content}"
    except Exception:
        return ""


# ============================================================
# TOOL 3 — ARXIV PAPERS
# ============================================================

async def arxiv_search(query: str) -> str:
    try:
        search = arxiv.Search(
            query=query,
            max_results=MAX_ARXIV_RESULTS,
            sort_by=arxiv.SortCriterion.Relevance
        )

        papers = []
        for result in search.results():
            papers.append(
                f"Title: {result.title}\n"
                f"Summary: {result.summary}\n"
                f"Published: {result.published.date()}\n"
            )

        return "\n\n".join(papers)

    except Exception:
        return ""


# ============================================================
# OLLAMA SUMMARIZER
# ============================================================

async def summarize_with_ollama(text: str) -> str:
    if not text.strip():
        return ""

    prompt = f"""
You are a professional research analyst.

Summarize the following research into structured knowledge
that can be used to create a high-quality presentation.

Focus on:
- Key themes
- Important insights
- Data points
- Academic findings
- Trends
- Structured bullet knowledge

Research:
{text}
"""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json=payload) as resp:
                if resp.status != 200:
                    return text[:MAX_FINAL_CONTEXT_CHARS]
                data = await resp.json()

        return data.get("response", "")[:MAX_FINAL_CONTEXT_CHARS]

    except Exception:
        return text[:MAX_FINAL_CONTEXT_CHARS]


# ============================================================
# GRAPH NODE 1 — PARALLEL RESEARCH
# ============================================================

async def research_parallel_node(state: ResearchState):
    query = state["query"]

    web_task = web_search(query)
    wiki_task = wiki_search(query)
    arxiv_task = arxiv_search(query)

    web_results, wiki_results, arxiv_results = await asyncio.gather(
        web_task,
        wiki_task,
        arxiv_task
    )

    return {
        "web_results": web_results,
        "wiki_results": wiki_results,
        "arxiv_results": arxiv_results
    }


# ============================================================
# GRAPH NODE 2 — MERGE + SUMMARIZE
# ============================================================

async def merge_and_summarize_node(state: ResearchState):
    combined = "\n\n".join(filter(None, [
        state.get("web_results", ""),
        state.get("wiki_results", ""),
        state.get("arxiv_results", "")
    ]))

    if not combined.strip():
        return {"final_context": ""}

    combined = combined[:MAX_COMBINED_CHARS]

    summary = await summarize_with_ollama(combined)

    return {"final_context": summary}


# ============================================================
# BUILD LANGGRAPH
# ============================================================

def build_graph():
    builder = StateGraph(ResearchState)

    builder.add_node("research_parallel", research_parallel_node)
    builder.add_node("merge", merge_and_summarize_node)

    builder.set_entry_point("research_parallel")
    builder.add_edge("research_parallel", "merge")
    builder.set_finish_point("merge")

    return builder.compile()


# ============================================================
# PUBLIC SERVICE
# ============================================================

class AgenticResearchService:

    def __init__(self):
        self.graph = build_graph()

    async def run(self, query: str) -> str:
        try:
            result = await self.graph.ainvoke({
                "query": query,
                "web_results": "",
                "wiki_results": "",
                "arxiv_results": "",
                "final_context": ""
            })

            return result.get("final_context", "")

        except Exception as e:
            print("Agentic research error:", e)
            return ""
