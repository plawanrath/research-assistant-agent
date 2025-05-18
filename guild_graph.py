"""Research Guild Orchestrator – LangGraph implementation

* `FetcherAgent` returns a list of new paper dicts in `state["outputs"]`.
* `SummariserAgent` downloads each PDF, creates a concise summary with GPT, and
  replaces `state["outputs"]` with the enriched list (now including
  `summary`).

### Quick test
```
python guild_graph.py                # prints count + first titles
```
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, TypedDict
from langgraph.graph import StateGraph, START, END
from agents.fetcher import FetcherAgent
from agents.summariser import SummariserAgent
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
# logging.basicConfig(
#     level=logging.DEBUG,                     # DEBUG, INFO, WARNING…
#     format="%(levelname)s | %(name)s | %(message)s",
# )
# load_dotenv()


class GuildState(TypedDict):
    """Minimal state schema for initial build.

    We keep one key – `outputs` – which accumulates the list of new paper
    dictionaries returned by the Fetcher.  Later agents (summaries, scores,
    etc.) will extend this schema.
    """

    outputs: List[Dict[str, Any]]


class ResearchGuildGraph:
    """Encapsulates the LangGraph powering the Personal Research Guild."""

    # ------------------------------------------------------------------ #
    def __init__(self, topic: str, *, since_days: int = 2, max_results: int = 25):
        self.topic = topic
        self.since_days = since_days
        self.max_results = max_results

        self._compiled = self._build_and_compile()

    # ------------------------------------------------------------------ #
    def run(self) -> List[Dict[str, Any]]:
        """Execute the graph; return list of new papers from Fetcher."""
        state_in: GuildState = {"outputs": []}
        state_out: GuildState = self._compiled.invoke(state_in)
        return state_out["outputs"]

    # ------------------------------------------------------------------ #
    def _build_and_compile(self):
        """Create StateGraph → compile → return runnable."""
        builder = StateGraph(GuildState)

        # ---------- Fetcher node ---------- #
        fetch_agent = FetcherAgent(
            topic=self.topic, since_days=self.since_days, max_results=self.max_results
        )

        def fetch_node(state: GuildState) -> GuildState:
            papers, _ = fetch_agent.run(None, {})
            return {"outputs": papers}

        builder.add_node("fetch", fetch_node)

        # ---------- Summariser node ---------- #
        summariser_agent = SummariserAgent()

        def summarise_node(state: GuildState) -> GuildState:
            summarised, _ = summariser_agent.run(state["outputs"], {})
            return {"outputs": summarised}

        builder.add_node("summarise", summarise_node)

        # ---------- Edges ---------- #
        builder.add_edge(START, "fetch")
        builder.add_edge("fetch", "summarise")
        builder.add_edge("summarise", END)

        # 3️⃣ Compile
        return builder.compile()


# ---------------------------------------------------------------------- #
# CLI helper
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    rg = ResearchGuildGraph(topic="ai safety", since_days=1, max_results=15)
    papers = rg.run()

    logging.info("✅ Finished – %d new papers", len(papers))
    for p in papers[:5]:
        logging.info(" • %s", p.get("title", "<no title>"))
