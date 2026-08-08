from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)
from tradingagents.agents.utils.signal_data_tools import (
    get_profit_forecast,
    get_hot_stocks,
    get_northbound_flow,
    get_concept_blocks,
    get_fund_flow,
    get_dragon_tiger_board,
    get_lockup_expiry,
    get_industry_comparison,
)
from tradingagents.agents.utils.etf_data_tools import (
    get_etf_announcements,
    get_etf_profile,
    get_etf_quote,
    get_etf_shares_aum,
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(
    ticker: str, instrument_profile: dict | None = None
) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    if instrument_profile and instrument_profile.get("security_type") == "etf":
        limit = instrument_profile.get("price_limit_pct")
        limit_value = limit.get("value") if isinstance(limit, dict) else limit
        tracking_code = instrument_profile.get("tracking_index_code")
        if isinstance(tracking_code, dict):
            tracking_code = tracking_code.get("value", {}).get("code")
        return (
            f"The instrument is the domestic equity ETF `{ticker}` "
            f"({instrument_profile.get('fund_name', ticker)}) on "
            f"{instrument_profile.get('exchange')}. It tracks "
            f"{instrument_profile.get('tracking_index_name')}. "
            f"Tracking index code: {tracking_code or 'unavailable'}. "
            f"Trading rules: T+1, minimum lot 100 shares, price limit "
            f"{limit_value or '10'}%. Use ETF/index evidence only; never use "
            "company revenue, management, lockups, or insider transactions. "
            "Use the exact ETF code in every tool call."
        )
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`). "
        "When a tool argument is named `ticker`, pass only this ticker value; "
        "do not pass company names, sectors, concepts, or search keywords."
    )


def build_evidence_lexicon(analysis_mode: str, capabilities: list[str] | None) -> str:
    """Supply mode-specific allowed and prohibited evidence without duplicating prompts."""
    if analysis_mode != "etf":
        return ""
    return (
        "Allowed evidence: ETF price/technical data, liquidity, disclosed shares/AUM, "
        "fund profile and announcements, tracking-index news and policy. "
        "Prohibited evidence: company financials, earnings forecasts, management, "
        "insider transactions, lockups, Dragon Tiger Board, or claims about real-time holdings. "
        f"Active capabilities: {', '.join(capabilities or [])}."
    )


def build_risk_framework(analysis_mode: str, posture: str) -> str:
    """Return the small mode-dependent risk block injected into one shared prompt."""
    if analysis_mode != "etf":
        return {
            "aggressive": "Consider A-share policy support, momentum, Northbound flow, and valuation upside.",
            "conservative": "Consider T+1, price-limit traps, policy reversals, lockups, hot-money exits, and valuation risk.",
            "neutral": "Balance T+1, policy sensitivity, sector rotation, valuation, and position sizing.",
        }[posture]
    return {
        "aggressive": (
            "Consider tracking-index momentum, policy support for the index theme, "
            "adequate liquidity, and clearly disclosed fund structure."
        ),
        "conservative": (
            "Consider T+1 and the ETF's stated price limit, low liquidity, stale "
            "shares/AUM disclosures, index concentration, tracking uncertainty, "
            "and policy reversal. Do not cite lockups or company valuation."
        ),
        "neutral": (
            "Balance tracking-index trend, ETF liquidity, disclosure freshness, "
            "policy sensitivity, T+1 constraints, and trading-cost risk. Do not "
            "use company earnings, management, or lockup evidence."
        ),
    }[posture]


def build_analysis_report_context(state: dict) -> str:
    """Render only the report fields that are semantically valid for this mode."""
    if state.get("analysis_mode") == "etf":
        return (
            f"ETF technical report:\n{state.get('market_report', '')}\n\n"
            f"ETF liquidity report:\n{state.get('etf_liquidity_report', '')}\n\n"
            f"ETF structure report:\n{state.get('etf_profile_report', '')}\n\n"
            f"Index news and policy report:\n{state.get('etf_index_news_report', '')}"
        )
    return (
        f"Market research report:\n{state.get('market_report', '')}\n\n"
        f"Social media sentiment report:\n{state.get('sentiment_report', '')}\n\n"
        f"Latest news report:\n{state.get('news_report', '')}\n\n"
        f"Company fundamentals report:\n{state.get('fundamentals_report', '')}\n\n"
        f"Policy analysis report:\n{state.get('policy_report', '')}\n\n"
        f"Hot money / capital flow report:\n{state.get('hot_money_report', '')}\n\n"
        f"Lockup expiry / insider reduction report:\n{state.get('lockup_report', '')}"
    )


def build_debate_framework(analysis_mode: str, side: str) -> str:
    """Provide a compact, mode-correct thesis framework for bull/bear debate."""
    if analysis_mode == "etf":
        return {
            "bull": (
                "Bull thesis: tracking-index trend, supportive policy, adequate ETF "
                "liquidity, improving disclosed shares/AUM, and low data uncertainty."
            ),
            "bear": (
                "Bear thesis: weakening index trend, low ETF liquidity, stale "
                "disclosures, policy reversal, concentration/tracking uncertainty, "
                "and T+1 or limit constraints."
            ),
        }[side]
    return {
        "bull": "Bull thesis: policy tailwinds, momentum, fundamentals, and positive market signals.",
        "bear": "Bear thesis: policy headwinds, valuation risk, momentum reversal, and company-specific downside.",
    }[side]

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
