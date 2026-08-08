from tradingagents.agents.utils.agent_utils import (
    build_evidence_lexicon,
    build_analysis_report_context,
    build_instrument_context,
    build_risk_framework,
)

def create_neutral_debator(llm):
    def neutral_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_conservative_response = risk_debate_state.get("current_conservative_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        policy_report = state.get("policy_report", "")
        hot_money_report = state.get("hot_money_report", "")
        lockup_report = state.get("lockup_report", "")

        trader_decision = state["trader_investment_plan"]
        instrument_context = build_instrument_context(state["company_of_interest"], state.get("instrument_profile"))
        evidence_lexicon = build_evidence_lexicon(state.get("analysis_mode", "stock"), state.get("analysis_capabilities"))
        risk_framework = build_risk_framework(state.get("analysis_mode", "stock"), "neutral")
        report_context = build_analysis_report_context(state)

        prompt = f"""As the Neutral Risk Analyst, provide a balanced instrument-appropriate perspective.

Instrument context: {instrument_context}
Evidence constraints: {evidence_lexicon}

Risk framework: {risk_framework}

Here is the trader's decision:

{trader_decision}

Challenge both the aggressive and conservative analysts. Point out where each perspective is overly optimistic or overly cautious in the A-share context. Use these data sources:

{report_context}
Conversation history: {history} Last aggressive argument: {current_aggressive_response} Last conservative argument: {current_conservative_response}. If no responses yet, present your own argument.

Advocate for a balanced, position-sized approach that captures upside while respecting the stated trading constraints. Output conversationally without special formatting."""

        response = llm.invoke(prompt)

        argument = f"Neutral Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": neutral_history + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": argument,
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return neutral_node
