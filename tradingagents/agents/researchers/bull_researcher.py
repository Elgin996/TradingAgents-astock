from tradingagents.agents.utils.agent_utils import (
    build_analysis_report_context,
    build_debate_framework,
    build_evidence_lexicon,
    build_instrument_context,
)

def create_bull_researcher(llm):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

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
            state.get("analysis_mode", "stock"), "bull"
        )
        report_context = build_analysis_report_context(state)
        etf_reports = (
            f"ETF liquidity report: {state.get('etf_liquidity_report', '')}\n"
            f"ETF structure report: {state.get('etf_profile_report', '')}\n"
            f"Index news/policy report: {state.get('etf_index_news_report', '')}"
        )

        prompt = f"""You are a Bull Analyst building a strong, evidence-based investment case. Use only evidence appropriate for the identified instrument and address bearish arguments directly.

Instrument context: {instrument_context}
Evidence rules: {evidence_lexicon}

Debate framework: {debate_framework}

General bull points:
- Growth Potential: Market opportunities, revenue projections, and scalability
- Competitive Advantages: Unique products, dominant market positioning, or moat in the domestic market
- Positive Indicators: Financial health, industry trends, and recent positive news
- Bear Counterpoints: Critically analyze the bear argument with specific data and sound reasoning
- Engagement: Present your argument conversationally, engaging directly with the bear analyst's points

Resources available:
{report_context}
Data quality assessment: {data_quality_summary}
ETF reports (when applicable):
{etf_reports}
Conversation history of the debate: {history}
Last bear argument: {current_response}

⚠️ If the data quality assessment flags any report as low-confidence (grade C/D/F), reduce your reliance on that report and note the data limitation in your argument.

Deliver a compelling bull argument that integrates A-share market dynamics. Refute the bear's concerns and demonstrate why the bull position holds stronger merit in the Chinese market context.
"""

        response = llm.invoke(prompt)

        argument = f"Bull Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
