from typing import Annotated, TypedDict

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph, add_messages

from tradingagents.dataflows.vendors.base import VendorError
from tradingagents.graph.trading_graph import _vendor_resilient_tool_node


class _State(TypedDict):
    messages: Annotated[list, add_messages]


def _invoke_in_graph(tool, call_id: str):
    node = _vendor_resilient_tool_node([tool])
    graph = StateGraph(_State)
    graph.add_node(
        "request",
        lambda state: {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": tool.__name__, "args": {}, "id": call_id}
                    ],
                )
            ]
        },
    )
    graph.add_node("tools", node)
    graph.add_edge(START, "request")
    graph.add_edge("request", "tools")
    graph.add_edge("tools", END)
    return graph.compile().invoke({"messages": []})


def test_tool_node_degrades_vendor_error_but_not_programming_error():
    def vendor_failure() -> str:
        """Simulate an exhausted external data route."""
        raise VendorError("source offline")

    result = _invoke_in_graph(vendor_failure, "call-1")

    message = result["messages"][-1]
    assert "DATA_UNAVAILABLE" in message.content
    assert "source offline" in message.content


def test_tool_node_still_raises_unclassified_code_errors():
    def code_failure() -> str:
        """Simulate a programming defect rather than a vendor outage."""
        raise AssertionError("broken invariant")

    with pytest.raises(AssertionError, match="broken invariant"):
        _invoke_in_graph(code_failure, "call-2")
