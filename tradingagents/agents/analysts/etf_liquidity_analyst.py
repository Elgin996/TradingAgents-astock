from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_etf_quote,
    get_language_instruction,
    get_stock_data,
)
from tradingagents.dataflows.config import get_config


def create_etf_liquidity_analyst(llm):
    """Analyze secondary-market liquidity without calling stock-flow tools."""
    def node(state):
        ticker, trade_date = state["company_of_interest"], state["trade_date"]
        lookback = get_config().get("market_lookback_days") or 30
        tools = [get_stock_data, get_etf_quote]
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an ETF liquidity and trading analyst. Use only the
provided ETF OHLCV and quote tools. Distinguish secondary-market turnover from
primary-market subscriptions. Do not infer fund flows when shares are unavailable.
Report latest volume/amount when published, 5/20-day liquidity context over about
{lookback} calendar days of market data, zero or unusually low trading days,
turnover status, and execution risks. Include source dates and a Markdown summary
table. Mark unavailable fields as [数据缺失: field].
{instrument_context}\nCurrent date: {trade_date}.\n{language}"""),
            MessagesPlaceholder(variable_name="messages"),
        ]).partial(
            instrument_context=build_instrument_context(ticker, state.get("instrument_profile")),
            trade_date=trade_date,
            lookback=lookback,
            language=get_language_instruction(),
        )
        result = (prompt | llm.bind_tools(tools)).invoke(state["messages"])
        return {"messages": [result], "etf_liquidity_report": "" if result.tool_calls else result.content}
    return node
