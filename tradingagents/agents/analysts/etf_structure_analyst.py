from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_etf_profile,
    get_etf_shares_aum,
    get_language_instruction,
)


def create_etf_structure_analyst(llm):
    """Analyze ETF identity and disclosed structure, never company fundamentals."""
    def node(state):
        ticker, trade_date = state["company_of_interest"], state["trade_date"]
        tools = [get_etf_profile, get_etf_shares_aum]
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an ETF structure analyst. Retrieve and report fund
identity, manager, tracking index, fees, and the latest disclosed shares/AUM.
Clearly label shares/AUM disclosure periods and never call them realtime or net
subscriptions. Do not discuss company earnings, management, or holdings. Include
source/as-of dates, missing-data notices, and a Markdown summary table.
{instrument_context}\nCurrent date: {trade_date}.\n{language}"""),
            MessagesPlaceholder(variable_name="messages"),
        ]).partial(
            instrument_context=build_instrument_context(ticker, state.get("instrument_profile")),
            trade_date=trade_date,
            language=get_language_instruction(),
        )
        result = (prompt | llm.bind_tools(tools)).invoke(state["messages"])
        return {"messages": [result], "etf_profile_report": "" if result.tool_calls else result.content}
    return node
