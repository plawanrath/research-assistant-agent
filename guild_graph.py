"""
guild_graph.py
==============

•  ResearchGuildGraph(topic)  – same class as before (no hard-coded topic)
•  run_pipeline(topic, log_queue=None) – helper that executes the graph
   and, if a `queue.Queue` is provided, streams every root-logger INFO line
   into it.  A "__DONE__" sentinel marks completion.

This file can still be executed directly:

    python guild_graph.py --topic "ai safety" --days 2 --max 25
"""

from __future__ import annotations
import argparse, logging, queue
from typing import Any, Dict, List, TypedDict

from langgraph.graph import StateGraph, START, END
from agents.fetcher import FetcherAgent
from agents.summariser import SummariserAgent
from agents.critic import CriticAgent
from agents.trend import TrendAnalyzerAgent
from agents.planner import PlannerAgent

# ------------------------------------------------------------------ #
# Logging config (root logger)                                       #
# ------------------------------------------------------------------ #
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")


# ------------------------------------------------------------------ #
# Typed state passed through LangGraph                               #
# ------------------------------------------------------------------ #
class GuildState(TypedDict):
    outputs: List[Dict[str, Any]]


# ------------------------------------------------------------------ #
# Core graph wrapper                                                 #
# ------------------------------------------------------------------ #
class ResearchGuildGraph:
    def __init__(self, topic: str, *, since_days: int = 2, max_results: int = 25):
        self.topic = topic
        self.since_days = since_days
        self.max_results = max_results
        self._compiled = self._build_and_compile()

    def run(self) -> List[Dict[str, Any]]:
        start_state: GuildState = {"outputs": []}
        end_state: GuildState = self._compiled.invoke(start_state)
        return end_state["outputs"]

    # -------------------- internal builders -------------------- #
    def _build_and_compile(self):
        builder = StateGraph(GuildState)

        # 1️⃣ Fetch
        fetcher = FetcherAgent(self.topic, since_days=self.since_days, max_results=self.max_results)
        builder.add_node(
            "fetch",
            lambda _state: {"outputs": fetcher.run(None, {})[0]},
        )

        # 2️⃣ Summarise
        summariser = SummariserAgent()
        builder.add_node(
            "summarise",
            lambda state: {"outputs": summariser.run(state["outputs"], {})[0]},
        )

        # 3️⃣ Critic
        critic = CriticAgent()
        builder.add_node(
            "critic",
            lambda state: {"outputs": critic.run(state["outputs"], {})[0]},
        )

        # 4️⃣ Trend (side-effect only)
        trend = TrendAnalyzerAgent()
        builder.add_node(
            "trend",
            lambda state: (trend.run(None, {}))[0] or state,  # pass-through
        )

        # 5️⃣ Planner (side-effect only)
        planner = PlannerAgent()
        builder.add_node(
            "planner",
            lambda state: (planner.run(None, {}))[0] or state,
        )

        # Edges
        builder.set_entry_point("fetch")
        # builder.add_edge(START, "fetch")
        builder.add_edge("fetch", "summarise")
        builder.add_edge("summarise", "critic")
        builder.add_edge("critic", "trend")
        builder.add_edge("trend", "planner")
        builder.set_finish_point("planner")
        # builder.add_edge("planner", END)

        # 3️⃣ Compile
        return builder.compile()


# ------------------------------------------------------------------ #
# Helper for Streamlit (or any UI)                                   #
# ------------------------------------------------------------------ #
def run_pipeline(topic: str, log_q=None, *, days=2, max_results=25):
    """Execute the pipeline.  Streams INFO lines to log_q and ALWAYS
    puts '__DONE__' when the PlannerAgent returns (even on crash)."""
    import logging

    qh = None
    try:
        if log_q is not None:
            class QHandler(logging.Handler):
                def emit(self, rec):
                    if rec.levelno >= logging.INFO:
                        log_q.put(self.format(rec))
            qh = QHandler()
            qh.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
            logging.getLogger().addHandler(qh)

        graph = ResearchGuildGraph(topic, since_days=days, max_results=max_results)
        graph.run()

    finally:
        if log_q is not None:          # <- ALWAYS queue the sentinel
            log_q.put("__DONE__")
        if qh:
            logging.getLogger().removeHandler(qh)


# ------------------------------------------------------------------ #
# CLI entry – still convenient for cron / debugging                  #
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run Personal Research Guild pipeline.")
    ap.add_argument("--topic", default="ai safety", help="research topic keyword(s)")
    ap.add_argument("--days", type=int, default=2, help="look back N days")
    ap.add_argument("--max",  type=int, default=25, help="max results per source")
    args = ap.parse_args()

    logging.info("▶ Running pipeline for topic: %s", args.topic)
    run_pipeline(args.topic, None, days=args.days, max_results=args.max)
    logging.info("✅ Pipeline finished.")
