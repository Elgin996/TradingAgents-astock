from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data,
    get_index_data,
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
    get_etf_peer_comparison,
    get_etf_profile,
    get_etf_quote,
    get_etf_shares_aum,
    get_etf_structure_alerts,
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
        limit_status = (
            limit.get("status") if isinstance(limit, dict) else None
        ) or "assumed"
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
            f"{limit_value or '10'}% ({limit_status}). Use ETF/index evidence "
            "only; never use company revenue, management, lockups, or insider "
            "transactions. Use the exact ETF code in every tool call."
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
        "fund profile and announcements, tracking-index news and policy, "
        "same-index peer fees/AUM/liquidity comparison, and rule alerts for share "
        "or turnover deterioration. "
        "Prohibited evidence: company financials, earnings forecasts, management, "
        "insider transactions, lockups, Dragon Tiger Board, premium/discount without "
        "IOPV, tracking error, index weights, PCF, or claims about real-time holdings. "
        f"Active capabilities: {', '.join(capabilities or [])}."
    )


def build_general_debate_points(analysis_mode: str, side: str) -> str:
    """Mode-specific thesis bullets injected into the shared bull/bear prompt body."""
    if analysis_mode == "etf":
        if side == "bull":
            return (
                "General bull points:\n"
                "- Index Momentum: Tracking-index trend, relative strength, and breadth\n"
                "- Policy / Theme Support: Policy or industry catalysts that affect the index\n"
                "- ETF Tradability: Liquidity, disclosed shares/AUM direction, and data quality\n"
                "- Bear Counterpoints: Refute bear claims with dated ETF/index evidence\n"
                "- Engagement: Argue conversationally against the bear analyst"
            )
        return (
            "General bear points:\n"
            "- Index Deterioration: Weakening trend, crowded theme, or policy reversal\n"
            "- Tradability Risk: Thin liquidity, stale disclosures, or tracking uncertainty\n"
            "- Overconfidence: Challenge bull claims that over-read share changes or news\n"
            "- Bull Counterpoints: Expose optimistic assumptions with dated evidence\n"
            "- Engagement: Argue conversationally against the bull analyst"
        )
    if side == "bull":
        return (
            "General bull points:\n"
            "- Growth Potential: Market opportunities, revenue projections, and scalability\n"
            "- Competitive Advantages: Unique products, dominant market positioning, or moat\n"
            "- Positive Indicators: Financial health, industry trends, and recent positive news\n"
            "- Bear Counterpoints: Critically analyze the bear argument with specific data\n"
            "- Engagement: Present your argument conversationally with the bear analyst"
        )
    return (
        "General bear points:\n"
        "- Risks and Challenges: Market saturation, financial instability, or macro threats\n"
        "- Competitive Weaknesses: Weaker positioning, declining innovation, or competitors\n"
        "- Negative Indicators: Evidence from financials, market trends, or adverse news\n"
        "- Bull Counterpoints: Expose over-optimistic assumptions with specific data\n"
        "- Engagement: Present your argument conversationally with the bull analyst"
    )


def build_trading_constraints(analysis_mode: str, instrument_profile: dict | None = None) -> str:
    """Return the trading-rule block for trader/PM without duplicating prompt files."""
    if analysis_mode == "etf":
        limit = 10
        limit_status = "assumed"
        if isinstance(instrument_profile, dict):
            raw = instrument_profile.get("price_limit_pct")
            if isinstance(raw, dict):
                limit = raw.get("value") or 10
                limit_status = raw.get("status") or "assumed"
            elif raw is not None:
                limit = raw
        return (
            "ETF trading constraints (must factor into the decision):\n"
            "- T+1 settlement for secondary-market ETF shares\n"
            f"- Daily price limit: ±{limit}% ({limit_status}); do not invent board-specific stock rules\n"
            "- Minimum lot: 100 shares\n"
            "- Use only ETF technical, liquidity, structure, and index-news evidence\n"
            "- Do not cite company financials, management, lockups, or insider activity\n"
            "- Trading hours follow the A-share session calendar"
        )
    return (
        "A-Stock Trading Constraints (must factor into your decision):\n"
        "- T+1 settlement: shares bought today cannot be sold until the next trading day\n"
        "- Daily price limits: main board ±10%, STAR/ChiNext ±20%, Beijing Stock Exchange ±30%. "
        "ST/*ST do NOT get a narrower band after 2026-07-06\n"
        "- Newly listed stocks have no price limit for their first 5 trading days "
        "(Beijing Stock Exchange: first day only)\n"
        "- Minimum lot: 100 shares on main board and ChiNext; STAR 200 shares minimum; "
        "Beijing Stock Exchange 100 shares minimum\n"
        "- Trading hours (Beijing time): call auction 09:15-09:25, continuous "
        "09:30-11:30 / 13:00-14:57, closing auction 14:57-15:00, after-hours "
        "fixed-price session 15:05-15:30\n"
        "- ST/delisting risk: ST or *ST status signals regulatory warning; factor into position sizing\n"
        "- Margin eligibility: not all A-shares are margin-eligible; assume cash-only unless stated"
    )


def build_risk_framework(analysis_mode: str, posture: str) -> str:
    """Return the mode-dependent risk framework injected into one shared prompt."""
    if analysis_mode != "etf":
        return {
            "aggressive": (
                "A-Share Aggressive Framework — leverage these China-specific upside arguments:\n"
                "- Limit-Up Momentum (涨停板效应): In A-shares, consecutive limit-ups create powerful "
                "momentum; T+1 actually helps by preventing same-day profit-taking, allowing multi-day runs\n"
                "- Policy-Driven Sectors: When Beijing backs a sector (e.g. AI, chips, new energy), the "
                "policy put is real — government support creates a floor that doesn't exist in Western markets\n"
                "- Hot Money Conviction: When top hot money seats (游资席位) pile in with strong reason "
                "tags, the short-term upside can be explosive; missing these moves is also a risk\n"
                "- Northbound Validation: If foreign institutions via Stock Connect are net buying "
                "alongside domestic momentum, this dual confirmation is a strong signal\n"
                "- PE Expansion Phase: In A-share bull cycles, PEs routinely expand to 50-100x for "
                "thematic leaders; applying US-market valuation discipline too early means missing the main move\n"
                "- Retail Sentiment Tailwind: A-shares are 80% retail; when sentiment turns positive, the "
                "herd effect amplifies gains far beyond what fundamentals alone would suggest"
            ),
            "conservative": (
                "A-Share Conservative Framework — emphasize these China-specific downside risks:\n"
                "- T+1 Settlement Lock: Any position taken today CANNOT be exited until tomorrow. If the "
                "stock gaps down at open (e.g. after overnight policy news or global sell-off), losses are "
                "locked in with no recourse. This is the single most important structural risk in A-shares.\n"
                "- Daily Price Limit Trap (涨跌停板): If a stock hits limit-down (main board -10%, "
                "STAR/ChiNext -20%, Beijing Stock Exchange -30%), the order book on the buy side is "
                "typically empty, so sell orders queue but rarely fill. Since 2026-07-06 the after-hours "
                "fixed-price session (15:05-15:30, at the closing price) covers all A-shares, so exiting is "
                "not strictly impossible — but it still depends on finding a counterparty, which is exactly "
                "what is missing on a limit-down day. Treat it as \"effectively trapped\", not \"literally "
                "unable to place an order\". Multiple consecutive limit-downs can cause catastrophic losses "
                "with no practical ability to exit.\n"
                "- Lockup Expiry Overhang: Large lockup expiries (限售解禁) create massive potential sell "
                "pressure. Even if insiders haven't started selling, the OPTION to sell depresses sentiment "
                "and caps upside.\n"
                "- Policy Reversal Risk: A-shares are a policy market (政策市). What the government gives, "
                "it can take away overnight — sector support can turn to sector crackdown with a single "
                "State Council directive.\n"
                "- Hot Money Exit Risk (游资撤退): Hot money moves fast in both directions. Today's "
                "limit-up star is tomorrow's limit-down casualty. Retail investors are the last to know "
                "when hot money exits.\n"
                "- Valuation Discipline: PE > 50x with PEG > 2 is speculative territory regardless of "
                "growth narrative. The 30x PE digestion framework should be the anchor — if it takes 5+ "
                "years to digest, the position is overvalued.\n"
                "- ST/Delisting Risk: For companies with consecutive losses, ST designation signals "
                "regulatory risk warning, restricts which investors may buy (a risk-warning-board "
                "permission is required), removes the stock from margin-trading eligibility, and often "
                "triggers institutional forced selling. Note it does NOT narrow the daily band: main-board "
                "ST/*ST is ±10% since 2026-07-06, and STAR/ChiNext ST/*ST is ±20%. The danger is the "
                "delisting path and the shrinking buyer pool, not a tighter price limit."
            ),
            "neutral": (
                "A-Share Neutral Framework — use these China-specific balancing considerations:\n"
                "- T+1 as Double-Edged Sword: T+1 locks in losses (conservative point) BUT also prevents "
                "panic selling and allows multi-day momentum to develop (aggressive point). The neutral "
                "view: size positions so that a single overnight gap-down is survivable.\n"
                "- Policy Sensitivity Calibration: Not all policy signals are equal. Distinguish between "
                "top-level State Council directives (high conviction) vs local government incentives "
                "(lower reliability) vs market rumors (noise). Weight your risk assessment accordingly.\n"
                "- Northbound Flow as Smart Money Gauge: Foreign institutional flow via Stock Connect is "
                "more informed than retail flow, but also more fickle — they exit faster than domestic "
                "funds. Use it as a confirming signal, not a primary thesis.\n"
                "- Valuation Band Approach: Rather than rigid \"PE > 30x is expensive\" or \"PE doesn't "
                "matter in growth\", propose a valuation band — what PE range is defensible given the "
                "earnings trajectory? Use the PE digestion timeframe as a practical anchor.\n"
                "- Lockup Expiry Timing: The neutral view is not to panic at lockup dates but to monitor "
                "actual reduction filings (减持公告). The risk is real but the timing is uncertain — "
                "reducing exposure gradually near lockup windows is more sensible than binary all-in/all-out.\n"
                "- Sector Rotation Awareness: A-share themes rotate fast (typically 2-4 weeks). The "
                "neutral question is: where are we in the rotation cycle? Early rotation = room to run; "
                "late rotation = reduced upside with elevated downside.\n"
                "- Position Sizing over Direction: In a market with ±10-20% daily limits and T+1 "
                "settlement, position sizing is more important than directional conviction. A moderate "
                "position captures upside while limiting locked-in loss scenarios."
            ),
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
        from tradingagents.dataflows.analysis_capabilities import report_field_is_active

        capabilities = state.get("analysis_capabilities")
        sections = [
            ("market_report", "ETF technical report"),
            ("etf_liquidity_report", "ETF liquidity report"),
            ("etf_profile_report", "ETF structure report"),
            ("etf_index_news_report", "Index news and policy report"),
            ("etf_compare_report", "ETF peer comparison and rule alerts"),
        ]
        parts = []
        for field, label in sections:
            if report_field_is_active(field, capabilities):
                parts.append(f"{label}:\n{state.get(field, '')}")
        unavailable = state.get("analysis_unavailable_capabilities") or {}
        if unavailable:
            parts.append(
                "Unavailable data:\n"
                + "\n".join(f"- {k}: {v}" for k, v in unavailable.items())
            )
        return "\n\n".join(parts)
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
        "bull": (
            "A-Share Bull Framework — prioritize these China-specific bullish catalysts:\n"
            "- Policy Tailwinds: Government subsidies, industry support policies (e.g. \"专精特新\", "
            "national strategic sectors), favorable regulatory signals from CSRC/State Council\n"
            "- Northbound Capital (北向资金): Sustained net inflow from Hong Kong Stock Connect "
            "indicates foreign institutional conviction\n"
            "- Hot Money Momentum (游资接力): Consecutive limit-ups with volume confirmation, strong "
            "theme attribution (reason tags), sector rotation just beginning\n"
            "- Valuation Growth Story: Use forward PE, PEG, and PE digestion timeframe (30x anchor for "
            "A-stock growth stocks) to argue the current premium is justified by earnings trajectory\n"
            "- Lockup Expiry Cleared: If major lockup periods have passed or insiders are NOT reducing, "
            "this removes a key overhang"
        ),
        "bear": (
            "A-Share Bear Framework — prioritize these China-specific risk factors:\n"
            "- Policy Headwinds: Sudden regulatory crackdowns (e.g. industry rectification, antitrust), "
            "CSRC window guidance (窗口指导), sector-wide trading restrictions, or political risk signals\n"
            "- Lockup & Insider Selling: Upcoming lockup expiry dates with large overhang, controlling "
            "shareholders in pre-disclosure reduction windows, equity pledge liquidation risk\n"
            "- Hot Money Withdrawal (游资撤退): Volume divergence after limit-ups (放量滞涨), declining "
            "limit-up board count (连板断裂), sector rotation moving away from this theme\n"
            "- Valuation Bubble: PE far above 30x A-stock growth anchor with EPS unable to digest within "
            "3 years, PEG > 2 indicating overpriced growth, retail-driven speculative premium\n"
            "- T+1 Trap: After a sharp rally, buyers today cannot exit until tomorrow — if sentiment "
            "reverses overnight or a gap-down opens, losses are locked in\n"
            "- Northbound Retreat: Net outflow from Stock Connect signals foreign institutions reducing "
            "exposure"
        ),
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


        
