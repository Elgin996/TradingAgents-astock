"""Portfolio Manager: synthesises the risk-analyst debate into the final decision.

Uses LangChain's ``with_structured_output`` so the LLM produces a typed
``PortfolioDecision`` directly, in a single call.  The result is rendered
back to markdown for storage in ``final_trade_decision`` so memory log,
CLI display, and saved reports continue to consume the same shape they do
today.  When a provider does not expose structured output, the agent falls
back gracefully to free-text generation.
"""

from __future__ import annotations

from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
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
from tradingagents.agents.utils.etf_synthesis_grounding import (
    grounded_portfolio_decision,
    has_unsupported_etf_synthesis,
)
from tradingagents.agents.utils.rating import parse_rating


# Mirrors the Trader: the schema alone cannot stop the model from putting
# price levels into the prose fields, so the prompt says it explicitly too.
_NO_LEVELS_RULE = (
    "\n- Do NOT state entry prices, stop-loss levels, target prices or "
    "position sizes for this security; give the rating and the reasoning."
)


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        analysis_mode = state.get("analysis_mode", "stock")
        analysis_product = state.get("analysis_product")
        instrument_profile = state.get("instrument_profile")
        instrument_context = build_instrument_context(
            state["company_of_interest"], instrument_profile
        )
        evidence_lexicon = build_evidence_lexicon(
            analysis_mode,
            state.get("analysis_capabilities"),
            state.get("analysis_product"),
        )
        trading_constraints = build_trading_constraints(
            analysis_mode, instrument_profile, state.get("analysis_product")
        )
        mode_rules = (
            (
                "Passive ETF decision: use verified tracking-index context, ETF market-price "
                "signals, liquidity, disclosed fund structure and policy/news. Preserve a "
                "conflicted or standalone state; do not cite company financials, management, "
                "lockups, or insider activity."
                if state.get("analysis_product") == "passive_equity_etf"
                else "Active ETF decision: rely first on the ETF's own market-price, liquidity, "
                "fund structure and policy/news evidence. An optional benchmark is context only; "
                "do not cite mechanical tracking conclusions or company financials, management, "
                "lockups, or insider activity."
                if state.get("analysis_product") == "active_equity_etf"
                else "ETF decision: rely on index trend, liquidity, disclosed fund structure "
                "and policy/news. Do not cite company financials, management, lockups, "
                "or insider activity."
            )
            if analysis_mode == "etf"
            else "Stock decision: consider the applicable A-share stock constraints."
        )

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        # A blocked subject series is not a neutral investment opinion.  Keep
        # the final output explicitly unavailable instead of allowing the
        # generic five-level rating schema to turn missing evidence into
        # Hold.  Standalone/conflicted ETF states still reach the normal
        # synthesis path because their vehicle data remains usable.
        technical_assessment = state.get("technical_assessment") or {}
        if (
            analysis_product
            and isinstance(technical_assessment, dict)
            and technical_assessment.get("product_state") == "unavailable"
        ):
            unavailable_decision = (
                "**Rating**: Unavailable\n\n"
                "**Executive Summary**: The subject technical series is unavailable or "
                "blocked, so no directional portfolio rating is issued.\n\n"
                "**Investment Thesis**: Preserve the data-quality block and rerun only "
                "after an auditable subject snapshot is available."
            )
            new_risk_debate_state = {
                "judge_decision": unavailable_decision,
                "history": risk_debate_state.get("history", ""),
                "aggressive_history": risk_debate_state.get("aggressive_history", ""),
                "conservative_history": risk_debate_state.get("conservative_history", ""),
                "neutral_history": risk_debate_state.get("neutral_history", ""),
                "latest_speaker": "Judge",
                "current_aggressive_response": risk_debate_state.get(
                    "current_aggressive_response", ""
                ),
                "current_conservative_response": risk_debate_state.get(
                    "current_conservative_response", ""
                ),
                "current_neutral_response": risk_debate_state.get(
                    "current_neutral_response", ""
                ),
                "count": risk_debate_state.get("count", 0),
            }
            return {
                "risk_debate_state": new_risk_debate_state,
                "final_trade_decision": unavailable_decision,
            }

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions and outcomes:\n{past_context}\n"
            if past_context
            else ""
        )

        prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

{instrument_context}

{mode_rules}
Evidence constraints: {evidence_lexicon}

---

{trading_constraints}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction to enter or add to position
- **Overweight**: Favorable outlook, gradually increase exposure
- **Hold**: Maintain current position, no action needed
- **Underweight**: Reduce exposure, take partial profits
- **Sell**: Exit position or avoid entry

**Context:**
- Research Manager's investment plan: **{research_plan}**
- Trader's transaction proposal: **{trader_plan}**
{lessons_line}
**Risk Analysts Debate History:**
{history}

---

Be decisive and ground every conclusion in specific evidence from the analysts.{_NO_LEVELS_RULE}{get_language_instruction()}"""

        final_trade_decision = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_pm_decision,
            "Portfolio Manager",
        )
        if analysis_mode == "etf" or has_unsupported_etf_synthesis(
            final_trade_decision, state
        ):
            final_trade_decision = grounded_portfolio_decision(
                state, parse_rating(final_trade_decision)
            )

        etf_mode = analysis_mode == "etf"
        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": "" if etf_mode else risk_debate_state["history"],
            "aggressive_history": "" if etf_mode else risk_debate_state["aggressive_history"],
            "conservative_history": "" if etf_mode else risk_debate_state["conservative_history"],
            "neutral_history": "" if etf_mode else risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": "" if etf_mode else risk_debate_state["current_aggressive_response"],
            "current_conservative_response": "" if etf_mode else risk_debate_state["current_conservative_response"],
            "current_neutral_response": "" if etf_mode else risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
        }

    return portfolio_manager_node
