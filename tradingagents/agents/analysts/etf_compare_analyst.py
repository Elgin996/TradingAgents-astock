from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_etf_peer_comparison,
    get_etf_structure_alerts,
    get_language_instruction,
)


def create_etf_compare_analyst(llm):
    """Compare same-index ETFs and emit Stage-3 rule alerts without closed metrics."""

    def node(state):
        ticker, trade_date = state["company_of_interest"], state["trade_date"]
        tools = [get_etf_peer_comparison, get_etf_structure_alerts]
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are an ETF peer-comparison analyst for domestic equity ETFs.
Call the tools and report:
1) Same-index peer comparison on fees, disclosed shares/AUM, and secondary-market
   liquidity (turnover / float market cap). Rank peers on those fields only.
2) Deterministic structure alerts from the alerts tool (share spikes, AUM shrink,
   thin turnover). Quote each alert's rule, severity, as_of, and notes.

Hard prohibitions:
- Do not invent or request premium/discount, IOPV, tracking error, index weights,
  PCF baskets, or real-time holdings.
- Do not treat disclosed share changes as realtime net subscriptions.
- Do not use company earnings, management, lockups, or Dragon Tiger Board logic.

Include source/as-of dates, list unavailable comparison dimensions explicitly,
and finish with Markdown summary tables.
{instrument_context}
Current date: {trade_date}.
{language}""",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        ).partial(
            instrument_context=build_instrument_context(
                ticker, state.get("instrument_profile")
            ),
            trade_date=trade_date,
            language=get_language_instruction(),
        )
        result = (prompt | llm.bind_tools(tools)).invoke(state["messages"])
        return {
            "messages": [result],
            "etf_compare_report": "" if result.tool_calls else result.content,
        }

    return node
