from tradingagents.agents.utils.agent_utils import (
    build_analysis_report_context,
    build_debate_framework,
    build_evidence_lexicon,
    build_instrument_context,
)

def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        policy_report = state.get("policy_report", "")
        hot_money_report = state.get("hot_money_report", "")
        lockup_report = state.get("lockup_report", "")
        data_quality_summary = state.get("data_quality_summary", "")
        instrument_context = build_instrument_context(
            state["company_of_interest"], state.get("instrument_profile")
        )
        evidence_lexicon = build_evidence_lexicon(
            state.get("analysis_mode", "stock"), state.get("analysis_capabilities")
        )
        debate_framework = build_debate_framework(
            state.get("analysis_mode", "stock"), "bear"
        )
        report_context = build_analysis_report_context(state)
        etf_reports = (
            f"ETF liquidity report: {state.get('etf_liquidity_report', '')}\n"
            f"ETF structure report: {state.get('etf_profile_report', '')}\n"
            f"Index news/policy report: {state.get('etf_index_news_report', '')}"
        )

        prompt = f"""You are a Bear Analyst making a well-reasoned case against investing in the identified instrument. Use only instrument-appropriate evidence and counter bullish arguments directly.

Instrument context: {instrument_context}
Evidence rules: {evidence_lexicon}

Debate framework: {debate_framework}

General bear points:
- Risks and Challenges: Market saturation, financial instability, or macroeconomic threats
- Competitive Weaknesses: Weaker market positioning, declining innovation, or competitor threats
- Negative Indicators: Evidence from financial data, market trends, or adverse news
- Bull Counterpoints: Expose over-optimistic assumptions with specific data
- Engagement: Present your argument conversationally, directly engaging with the bull analyst's points

Resources available:
{report_context}
Data quality assessment: {data_quality_summary}
ETF reports (when applicable):
{etf_reports}
Conversation history of the debate: {history}
Last bull argument: {current_response}

⚠️ If the data quality assessment flags any report as low-confidence (grade C/D/F), reduce your reliance on that report and note the data limitation in your argument.

Deliver a compelling bear argument grounded in A-share market realities. Refute the bull's claims and demonstrate the risks of investing in this stock within the Chinese regulatory and market structure.
"""

        response = llm.invoke(prompt)

        argument = f"Bear Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
