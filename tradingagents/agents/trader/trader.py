"""Trader: turns the Research Manager's investment plan into a concrete transaction proposal."""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import TraderProposal, render_trader_proposal
from tradingagents.agents.utils.agent_utils import (
    build_evidence_lexicon,
    build_instrument_context,
    build_trading_constraints,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)

# The schema alone cannot stop the model from putting price levels into the
# free-text reasoning field, so the prompt says it explicitly too.
_NO_LEVELS_INSTRUCTION = (
    "Explain the reasoning behind the direction. Do NOT state entry prices, "
    "stop-loss levels, target prices or position sizes for this security."
)


def create_trader(llm):
    structured_llm = bind_structured(llm, TraderProposal, "Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        analysis_mode = state.get("analysis_mode", "stock")
        instrument_profile = state.get("instrument_profile")
        instrument_context = build_instrument_context(
            company_name, instrument_profile
        )
        evidence_lexicon = build_evidence_lexicon(
            analysis_mode, state.get("analysis_capabilities")
        )
        investment_plan = state["investment_plan"]
        trading_constraints = build_trading_constraints(
            analysis_mode, instrument_profile
        )

        # Collect A-stock specific analyst reports only in stock mode.
        astock_context = ""
        if analysis_mode != "etf":
            astock_context_parts = []
            for key, label in (
                ("policy_report", "Policy Analysis Report"),
                ("hot_money_report", "Hot Money / Capital Flow Report"),
                ("lockup_report", "Lockup Expiry / Insider Reduction Report"),
            ):
                content = state.get(key, "")
                if content:
                    astock_context_parts.append(f"{label}:\n{content}")
            astock_context = "\n\n".join(astock_context_parts)

        analyst_description = (
            "ETF technical, liquidity, structure, and index-news specialists"
            if analysis_mode == "etf"
            else "market, sentiment, news, fundamentals, policy, capital flow, and lockup/reduction specialists"
        )
        role_line = (
            "You are a trading agent specialising in domestic equity ETFs listed in mainland China."
            if analysis_mode == "etf"
            else "You are a trading agent specialising in A-share (China mainland) stocks."
        )

        messages = [
            {
                "role": "system",
                "content": (
                    f"{role_line} "
                    "Translate the Research Manager's investment plan into a structured "
                    f"transaction view.\n{trading_constraints}\n"
                    f"Evidence constraints: {evidence_lexicon} "
                    f"{_NO_LEVELS_INSTRUCTION} "
                    "（以上参数仅供技术研究参考，不构成投资建议）"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Based on a comprehensive analysis by {analyst_description}, "
                    f"here is an investment plan for {company_name}.\n\n"
                    f"{instrument_context}\n\n"
                    f"Proposed Investment Plan:\n{investment_plan}\n\n"
                    + (f"Additional A-Stock Analyst Context:\n{astock_context}\n\n" if astock_context else "")
                    + "Leverage these insights to craft the transaction view."
                    + get_language_instruction()
                ),
            },
        ]

        trader_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            messages,
            render_trader_proposal,
            "Trader",
        )

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
