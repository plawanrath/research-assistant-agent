"""Research Guild Orchestrator – LangGraph implementation

Refactored to use **StateGraph** (the canonical builder in the
`langgraph.graph` module) to avoid the `ImportError: cannot import name 'Graph'`
that occurs on current LangGraph versions ≥ 0.4.x.

### Quick test
```
python guild_graph.py                # prints count + first titles
```

### Next steps
* Add `SummariserAgent`, then wire:
    `builder.add_node("summarise", SummariserAgent(...).run)`
    `builder.add_edge("fetch", "summarise")`
* Keep the `GuildState` TypedDict up‑to‑date as more keys flow through.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, TypedDict

from langgraph.graph import StateGraph, START, END

from agents.fetcher import FetcherAgent

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")


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

        fetcher = FetcherAgent(
            topic=self.topic, since_days=self.since_days, max_results=self.max_results
        )

        # 1️⃣ Nodes
        builder.add_node("fetch", lambda state: {"outputs": fetcher.run(None, {})[0]})

        # 2️⃣ Edges: START → fetch → END
        builder.add_edge(START, "fetch")
        builder.add_edge("fetch", END)

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
