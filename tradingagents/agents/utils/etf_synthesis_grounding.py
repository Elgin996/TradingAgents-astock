"""Fail-closed grounding for ETF decision prose.

The rating still comes from the configured LLM. When its explanation turns a
closed capability into a numeric trigger, invents peer-relative evidence, or
applies the ETF price-limit rule to the index, rebuild the prose from frozen
state fields while preserving that rating.
"""

from __future__ import annotations

import re


_UNSUPPORTED_PATTERNS = (
    re.compile(r"(?:溢价率|折价率|溢价|折价).{0,30}(?:\d|高于|低于|持续|负)", re.DOTALL),
    re.compile(r"基差(?:风险|扩大|收窄|上升|下降)?"),
    re.compile(r"跟踪误差.{0,24}(?:上升|扩大|改善|恢复|高于|低于|\d)", re.DOTALL),
    re.compile(r"指数.{0,30}(?:10%|±10%).{0,12}(?:涨跌幅|限制)|指数.{0,30}涨跌幅限制", re.DOTALL),
    re.compile(r"(?:相对同类|同类机器人ETF|同类产品).{0,30}(?:转弱|转强|跑赢|跑输|领先|落后)", re.DOTALL),
    re.compile(r"均线.{0,16}(?:空头|多头)排列", re.DOTALL),
    re.compile(r"(?:日均量|成交量).{0,18}(?:连续\d+日|低于\d|高于\d)", re.DOTALL),
)


def has_unsupported_etf_synthesis(text: str, state: dict) -> bool:
    if state.get("analysis_mode") != "etf":
        return False
    return any(pattern.search(str(text or "")) for pattern in _UNSUPPORTED_PATTERNS)


def _facts(state: dict) -> str:
    technical = state.get("technical_assessment") or {}
    market_quality = state.get("market_data_quality") or {}
    return (
        f"结构化市场数据门控为 {state.get('market_data_decision', '不可得')}，"
        f"质量等级 {market_quality.get('grade', '不可得')}；"
        f"产品状态 {technical.get('product_state', '不可得')}，"
        f"ETF 价格技术状态 {technical.get('subject_stance', '不可得')}，"
        f"跟踪指数技术状态 {technical.get('reference_stance', '不可得')}，"
        f"价格路径关系 {technical.get('alignment_state', '不可得')}。"
        "流动性报告提供二级市场快照换手率和成交量窗口；基金结构报告的份额/AUM为定期披露。"
        "IOPV、折溢价、正式跟踪误差、指数权重、PCF和实时持仓在本次能力范围内不可得，"
        "只作为信息限制，不作为数值信号。"
    )


def _action(rating: str) -> str:
    return {
        "Buy": "评级方向为买入；执行前仍应核对实时盘口，并使用限价单控制滑点。",
        "Overweight": "评级方向为增配；仅在实时流动性可执行时渐进实施，并使用限价单。",
        "Hold": "维持现有仓位，不主动增减；继续观察 ETF 成交量、快照换手率、指数技术状态及后续定期披露。",
        "Underweight": "评级方向为减配；在实时流动性允许时审慎降低暴露，并使用限价单控制冲击。",
        "Sell": "评级方向为卖出/回避；执行时遵守 T+1，并避免在流动性收缩时使用无保护市价单。",
    }.get(rating, "维持观察，等待可审计数据补充后再评估。")


def grounded_research_plan(state: dict, rating: str) -> str:
    return (
        f"**Recommendation**: {rating}\n\n"
        f"**Rationale**: {_facts(state)} 因此保留模型评级，但移除无证据的数值阈值、同类相对判断和指数涨跌幅表述。\n\n"
        f"**Strategic Actions**: {_action(rating)}"
    )


def grounded_trader_proposal(state: dict, rating: str) -> str:
    return (
        f"**Action**: {rating}\n\n"
        f"**Reasoning**: {_facts(state)} 交易方向沿用研究经理评级，且不使用关闭能力生成价格、仓位或触发阈值。\n\n"
        f"FINAL TRANSACTION PROPOSAL: **{rating.upper()}**"
    )


def grounded_portfolio_decision(state: dict, rating: str) -> str:
    return (
        f"**Rating**: {rating}\n\n"
        f"**Executive Summary**: {_facts(state)} 最终评级保留模型的风险偏好判断，并删除所有未被工具证据支持的具体断言。\n\n"
        f"**Investment Thesis**: {_action(rating)}"
    )
