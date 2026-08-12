from tradingagents.agents.utils.agent_utils import (
    build_analysis_report_context,
    build_debate_framework,
    build_evidence_lexicon,
    build_general_debate_points,
    build_instrument_context,
)

def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = investment_debate_state.get("current_response", "")
        data_quality_summary = state.get("data_quality_summary", "")
        analysis_mode = state.get("analysis_mode", "stock")
        instrument_context = build_instrument_context(
            state["company_of_interest"], state.get("instrument_profile")
        )
        evidence_lexicon = build_evidence_lexicon(
            analysis_mode,
            state.get("analysis_capabilities"),
            state.get("analysis_product"),
        )
        debate_framework = build_debate_framework(
            analysis_mode, "bear", state.get("analysis_product")
        )
        general_points = build_general_debate_points(
            analysis_mode, "bear", state.get("analysis_product")
        )
        report_context = build_analysis_report_context(state)
        closing = (
            "Deliver a compelling bear argument grounded in ETF/index evidence and "
            "Chinese market structure. Refute the bull without inventing company-level facts."
            if analysis_mode == "etf"
            else "Deliver a compelling bear argument grounded in A-share market realities. "
            "Refute the bull's claims and demonstrate the risks of investing in this stock "
            "within the Chinese regulatory and market structure."
        )

        prompt = f"""You are a Bear Analyst making a well-reasoned case against investing in the identified instrument. Use only instrument-appropriate evidence and counter bullish arguments directly.

Instrument context: {instrument_context}
Evidence rules: {evidence_lexicon}

Debate framework: {debate_framework}

{general_points}

Resources available:
{report_context}
Data quality assessment: {data_quality_summary}
Conversation history of the debate: {history}
Last bull argument: {current_response}

⚠️ If the data quality assessment flags any report as low-confidence (grade C/D/F), reduce your reliance on that report and note the data limitation in your argument.

{closing}
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
