# TradingAgents/graph/setup.py

from typing import Any, Dict, Optional, Sequence
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState

from .conditional_logic import ConditionalLogic

# Single source of truth for the default analyst set (F7.2).
DEFAULT_ANALYSTS: tuple[str, ...] = (
    "market",
    "social",
    "news",
    "fundamentals",
    "policy",
    "hot_money",
    "lockup",
)
ETF_ANALYSTS: tuple[str, ...] = (
    "market",
    "etf_liquidity",
    "etf_structure",
    "etf_index_news",
    "etf_compare",
)


def resolve_analysts(
    analysis_mode: str,
    capabilities: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Return the only analyst set valid for the identified instrument mode.

    ETF runs further prune analysts whose required capabilities were removed
    after the runtime data-source probe.
    """
    if analysis_mode != "etf":
        return DEFAULT_ANALYSTS
    from tradingagents.dataflows.analysis_capabilities import filter_etf_analysts

    return filter_etf_analysts(ETF_ANALYSTS, capabilities)


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: Dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic

    def setup_graph(
        self,
        selected_analysts: Optional[Sequence[str]] = None,
        analysis_mode: str = "stock",
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst (technical analysis)
                - "social": Social media / sentiment analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
                - "policy": Policy analyst (A-stock specific)
                - "hot_money": Hot money / capital flow tracker (A-stock specific)
                - "lockup": Lockup expiry / reduction watcher (A-stock specific)
        """
        selected_analysts = list(selected_analysts or DEFAULT_ANALYSTS)
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # Create analyst nodes
        analyst_nodes = {}
        delete_nodes = {}
        tool_nodes = {}

        if "market" in selected_analysts:
            analyst_nodes["market"] = create_market_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["market"] = create_msg_delete()
            tool_nodes["market"] = self.tool_nodes["market"]

        if "social" in selected_analysts:
            analyst_nodes["social"] = create_social_media_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["social"] = create_msg_delete()
            tool_nodes["social"] = self.tool_nodes["social"]

        if "news" in selected_analysts:
            analyst_nodes["news"] = create_news_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["news"] = create_msg_delete()
            tool_nodes["news"] = self.tool_nodes["news"]

        if "fundamentals" in selected_analysts:
            analyst_nodes["fundamentals"] = create_fundamentals_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["fundamentals"] = create_msg_delete()
            tool_nodes["fundamentals"] = self.tool_nodes["fundamentals"]

        if "policy" in selected_analysts:
            analyst_nodes["policy"] = create_policy_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["policy"] = create_msg_delete()
            tool_nodes["policy"] = self.tool_nodes["policy"]

        if "hot_money" in selected_analysts:
            analyst_nodes["hot_money"] = create_hot_money_tracker(
                self.quick_thinking_llm
            )
            delete_nodes["hot_money"] = create_msg_delete()
            tool_nodes["hot_money"] = self.tool_nodes["hot_money"]

        if "lockup" in selected_analysts:
            analyst_nodes["lockup"] = create_lockup_watcher(
                self.quick_thinking_llm
            )
            delete_nodes["lockup"] = create_msg_delete()
            tool_nodes["lockup"] = self.tool_nodes["lockup"]

        if "etf_liquidity" in selected_analysts:
            analyst_nodes["etf_liquidity"] = create_etf_liquidity_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["etf_liquidity"] = create_msg_delete()
            tool_nodes["etf_liquidity"] = self.tool_nodes["etf_liquidity"]

        if "etf_structure" in selected_analysts:
            analyst_nodes["etf_structure"] = create_etf_structure_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["etf_structure"] = create_msg_delete()
            tool_nodes["etf_structure"] = self.tool_nodes["etf_structure"]

        if "etf_index_news" in selected_analysts:
            analyst_nodes["etf_index_news"] = create_etf_index_news_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["etf_index_news"] = create_msg_delete()
            tool_nodes["etf_index_news"] = self.tool_nodes["etf_index_news"]

        if "etf_compare" in selected_analysts:
            analyst_nodes["etf_compare"] = create_etf_compare_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["etf_compare"] = create_msg_delete()
            tool_nodes["etf_compare"] = self.tool_nodes["etf_compare"]

        # Create quality gate node (only grade analysts that actually ran)
        quality_gate_node = create_quality_gate(
            self.quick_thinking_llm,
            selected_analysts=selected_analysts,
            analysis_mode=analysis_mode,
        )

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(self.quick_thinking_llm)
        bear_researcher_node = create_bear_researcher(self.quick_thinking_llm)
        research_manager_node = create_research_manager(self.deep_thinking_llm)
        trader_node = create_trader(self.quick_thinking_llm)

        # Create risk analysis nodes
        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add analyst nodes to the graph
        for analyst_type, node in analyst_nodes.items():
            workflow.add_node(f"{analyst_type.capitalize()} Analyst", node)
            workflow.add_node(
                f"Msg Clear {analyst_type.capitalize()}", delete_nodes[analyst_type]
            )
            workflow.add_node(f"tools_{analyst_type}", tool_nodes[analyst_type])

        # Add quality gate + other nodes
        workflow.add_node("Quality Gate", quality_gate_node)
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        # Define edges
        # Start with the first analyst
        first_analyst = selected_analysts[0]
        workflow.add_edge(START, f"{first_analyst.capitalize()} Analyst")

        # Connect analysts in sequence
        for i, analyst_type in enumerate(selected_analysts):
            current_analyst = f"{analyst_type.capitalize()} Analyst"
            current_tools = f"tools_{analyst_type}"
            current_clear = f"Msg Clear {analyst_type.capitalize()}"

            # Add conditional edges for current analyst
            workflow.add_conditional_edges(
                current_analyst,
                getattr(self.conditional_logic, f"should_continue_{analyst_type}"),
                [current_tools, current_clear],
            )
            workflow.add_edge(current_tools, current_analyst)

            # Connect to next analyst or to Bull Researcher if this is the last analyst
            if i < len(selected_analysts) - 1:
                next_analyst = f"{selected_analysts[i+1].capitalize()} Analyst"
                workflow.add_edge(current_clear, next_analyst)
            else:
                workflow.add_edge(current_clear, "Quality Gate")

        workflow.add_conditional_edges(
            "Quality Gate",
            self.conditional_logic.should_continue_after_quality_gate,
            {"Bull Researcher": "Bull Researcher", END: END},
        )

        # Add remaining edges
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Conservative Analyst": "Conservative Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Neutral Analyst": "Neutral Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Aggressive Analyst": "Aggressive Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )

        workflow.add_edge("Portfolio Manager", END)

        return workflow
