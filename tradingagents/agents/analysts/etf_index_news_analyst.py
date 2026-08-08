from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_etf_announcements,
    get_global_news,
    get_language_instruction,
    get_news,
)


def create_etf_index_news_analyst(llm):
    """Review index/policy context and dated fund announcements."""
    def node(state):
        ticker, trade_date = state["company_of_interest"], state["trade_date"]
        tools = [get_news, get_global_news, get_etf_announcements]
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an ETF index news and policy analyst. Assess only
tracking-index, sector/theme, policy, and fund-announcement developments. Treat
single-constituent news as material only when it plausibly affects the index.
Every event must retain a publication date and source. Never use company financials,
lockups, insiders, or management logic. Include a Markdown event table and report
unavailable sources explicitly.
When the instrument context provides a tracking-index code, call `get_news`
with that index code for index-related coverage; use the ETF code only with
`get_etf_announcements`. Do not substitute ETF-code news for index evidence.
{instrument_context}\nCurrent date: {trade_date}.\n{language}"""),
            MessagesPlaceholder(variable_name="messages"),
        ]).partial(
            instrument_context=build_instrument_context(ticker, state.get("instrument_profile")),
            trade_date=trade_date,
            language=get_language_instruction(),
        )
        result = (prompt | llm.bind_tools(tools)).invoke(state["messages"])
        return {"messages": [result], "etf_index_news_report": "" if result.tool_calls else result.content}
    return node
