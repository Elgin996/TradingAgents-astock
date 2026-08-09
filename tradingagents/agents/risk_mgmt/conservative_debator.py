from tradingagents.agents.utils.agent_utils import (
    build_evidence_lexicon,
    build_analysis_report_context,
    build_instrument_context,
    build_risk_framework,
)

def create_conservative_debator(llm):
    def conservative_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        conservative_history = risk_debate_state.get("conservative_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        trader_decision = state["trader_investment_plan"]
        instrument_context = build_instrument_context(state["company_of_interest"], state.get("instrument_profile"))
        evidence_lexicon = build_evidence_lexicon(state.get("analysis_mode", "stock"), state.get("analysis_capabilities"))
        risk_framework = build_risk_framework(state.get("analysis_mode", "stock"), "conservative")
        report_context = build_analysis_report_context(state)

        prompt = f"""As the Conservative Risk Analyst, protect assets and minimize risk using instrument-appropriate evidence.

Instrument context: {instrument_context}
Evidence constraints: {evidence_lexicon}

Risk framework: {risk_framework}

Here is the trader's decision:

{trader_decision}

Counter the aggressive and neutral analysts. Highlight where their optimism overlooks A-share structural risks. Use these data sources:

{report_context}
Conversation history: {history} Last aggressive argument: {current_aggressive_response} Last neutral argument: {current_neutral_response}. If no responses yet, present your own argument.

Demonstrate why a conservative stance is the safest path under the stated instrument constraints. Output conversationally without special formatting."""

        response = llm.invoke(prompt)

        argument = f"Conservative Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": conservative_history + "\n" + argument,
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Conservative",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": argument,
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return conservative_node
