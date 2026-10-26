
"""LangGraph workflow for HomeFlow's document chatbot."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class ChatState(TypedDict):
    """State passed between chatbot workflow steps."""

    question: str
    context: list[dict]
    clarification: dict | None
    reply: dict | None


def _route(state: ChatState) -> str:
    """Choose the appropriate conversation path."""
    return "clarify" if state["clarification"] is not None else "answer"


def _clarify_node(state: ChatState) -> dict:
    """Return an existing clarification without calling the model."""
    return {"reply": state["clarification"]}


def build_chat_graph(answer_question):
    """Build a conditional chatbot workflow."""

    def answer_node(state: ChatState) -> dict:
        return {
            "reply": answer_question(
                state["question"],
                state["context"],
            )
        }

    workflow = StateGraph(ChatState)
    workflow.add_node("clarify", _clarify_node)
    workflow.add_node("answer", answer_node)
    workflow.add_conditional_edges(
        START,
        _route,
        {"clarify": "clarify", "answer": "answer"},
    )
    workflow.add_edge("clarify", END)
    workflow.add_edge("answer", END)

    return workflow.compile()
