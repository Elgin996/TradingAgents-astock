from tradingagents.agents.utils.agent_utils import (
    build_evidence_lexicon,
    build_analysis_report_context,
    build_instrument_context,
    build_risk_framework,
)

def create_aggressive_debator(llm):
    def aggressive_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        aggressive_history = risk_debate_state.get("aggressive_history", "")

        current_conservative_response = risk_debate_state.get("current_conservative_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        trader_decision = state["trader_investment_plan"]
        instrument_context = build_instrument_context(state["company_of_interest"], state.get("instrument_profile"))
        evidence_lexicon = build_evidence_lexicon(state.get("analysis_mode", "stock"), state.get("analysis_capabilities"))
        risk_framework = build_risk_framework(state.get("analysis_mode", "stock"), "aggressive")
        report_context = build_analysis_report_context(state)

        prompt = f"""As the Aggressive Risk Analyst, champion high-reward opportunities with instrument-appropriate evidence. Counter the conservative and neutral analysts with data-driven rebuttals.

Instrument context: {instrument_context}
Evidence constraints: {evidence_lexicon}

Risk framework: {risk_framework}

Here is the trader's decision:

{trader_decision}

Challenge the conservative and neutral stances. Demonstrate why their caution risks missing the opportunity. Use these data sources:

{report_context}
Conversation history: {history} Last conservative argument: {current_conservative_response} Last neutral argument: {current_neutral_response}. If no responses yet, present your own argument.

Engage actively, debate persuasively, and assert why aggressive positioning is optimal for this opportunity. Output conversationally without special formatting."""

        response = llm.invoke(prompt)

        argument = f"Aggressive Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": aggressive_history + "\n" + argument,
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return aggressive_node
