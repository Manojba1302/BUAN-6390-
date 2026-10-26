
"""Unit tests for HomeFlow's LangGraph chatbot workflow."""

from app.services.chat_graph import build_chat_graph


def test_graph_generates_answer():
    def mock_answer(question, context):
        return {"answer": "Your income is $5,000.", "citations": []}

    graph = build_chat_graph(mock_answer)
    result = graph.invoke({
        "question": "What is my income?",
        "context": [],
        "clarification": None,
        "reply": None,
    })

    assert result["reply"]["answer"] == "Your income is $5,000."


def test_graph_receives_conversation_context():
    received = {}

    def mock_answer(question, context):
        received["question"] = question
        received["context"] = context
        return {"answer": "Based on the document.", "citations": []}

    context = [{"question": "What is my salary?", "answer": "$5,000"}]
    graph = build_chat_graph(mock_answer)
    graph.invoke({
        "question": "What about deductions?",
        "context": context,
        "clarification": None,
        "reply": None,
    })

    assert received["question"] == "What about deductions?"
    assert received["context"] == context


def test_graph_returns_clarification_without_model():
    def forbidden_answer(question, context):
        raise AssertionError("Answer service should not be called")

    clarification = {
        "answer": "Which document do you mean?",
        "citations": [],
    }

    graph = build_chat_graph(forbidden_answer)
    result = graph.invoke({
        "question": "What about that document?",
        "context": [],
        "clarification": clarification,
        "reply": None,
    })

    assert result["reply"] == clarification
