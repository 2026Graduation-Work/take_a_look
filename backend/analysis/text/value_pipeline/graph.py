"""LangGraph 오케스트레이터.

validation_agent를 병렬 구간이 아니라 fan-in 뒤 선형 구간에 두는 이유:
PipelineState의 각 키에 reducer가 없어 last-write-wins이므로, 병렬 노드가 같은
키를 쓰면 LangGraph가 InvalidUpdateError를 낸다.
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from . import collectors
from .agents import financial_agent, news_agent, synthesis_agent, validation_agent
from .config import SETTINGS


class PipelineState(TypedDict, total=False):
    ticker: str
    date: str
    company_name: str
    raw_news: list
    prior_news: list
    news_source: str
    raw_financials: dict
    financial_source: str
    news_result: dict
    financial_result: dict
    validation: dict
    final: dict


def ingest(state: PipelineState) -> dict:
    ticker = state["ticker"]
    date = state["date"]
    name = state.get("company_name") or ticker

    news, news_src = collectors.collect_news(ticker, name, date)
    prior = collectors.collect_prior_news(
        ticker, name, date, SETTINGS.staleness_lookback_articles
    )
    fin, fin_src = collectors.collect_financials(ticker, date)

    return {
        "company_name": state.get("company_name") or fin.get("company_name") or ticker,
        "raw_news": news,
        "prior_news": prior,
        "news_source": news_src,
        "raw_financials": fin,
        "financial_source": fin_src,
    }


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("ingest", ingest)
    g.add_node("news_agent", news_agent)
    g.add_node("financial_agent", financial_agent)
    g.add_node("validation_agent", validation_agent)
    g.add_node("synthesis_agent", synthesis_agent)

    g.add_edge(START, "ingest")
    for node in ("news_agent", "financial_agent"):
        g.add_edge("ingest", node)
        g.add_edge(node, "validation_agent")    # fan-in (둘 다 끝난 뒤 1회 실행)
    g.add_edge("validation_agent", "synthesis_agent")
    g.add_edge("synthesis_agent", END)
    return g.compile()


APP = build_graph()


def run_pipeline(ticker: str, date: str, company_name: str = "") -> dict:
    state: PipelineState = {"ticker": ticker, "date": date, "company_name": company_name}
    result = APP.invoke(state)
    return result["final"]
