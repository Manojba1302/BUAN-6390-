
from app.services.chat_privacy import redact_text, redact_data


def test_ssn_is_redacted():
    text = "My SSN is 123-45-6789."
    assert "123-45-6789" not in redact_text(text)
    assert "[SSN REDACTED]" in redact_text(text)


def test_phone_is_redacted():
    text = "Call me at (214) 555-0199."
    assert "(214) 555-0199" not in redact_text(text)
    assert "[PHONE REDACTED]" in redact_text(text)


def test_dob_is_redacted():
    text = "DOB: 08/09/2000"
    assert "08/09/2000" not in redact_text(text)
    assert "[DOB REDACTED]" in redact_text(text)


def test_nested_chat_reply_is_redacted():
    reply = {
        "answer": "SSN: 123-45-6789",
        "evidence": [
            {"content": "Phone: 214-555-0199"}
        ],
    }

    result = redact_data(reply)

    assert "123-45-6789" not in result["answer"]
    assert "214-555-0199" not in result["evidence"][0]["content"]


def test_non_sensitive_text_is_preserved():
    text = "Your bank statement is on page 2."
    assert redact_text(text) == text


from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services import chat_history


def test_begin_redacts_question_before_storage():
    conversation = SimpleNamespace(
        conversation_id=uuid4(),
        updated_at=None,
    )

    db = MagicMock()
    db.scalar.return_value = None

    question = "My SSN is 123-45-6789."

    row = chat_history.begin(db, conversation, question)

    assert row.question == "My SSN is [SSN REDACTED]."
    assert "123-45-6789" not in row.question
    db.add.assert_called_once_with(row)
    db.commit.assert_called_once()


def test_finish_redacts_reply_before_storage():
    turn_id = uuid4()

    row = SimpleNamespace(
        reply=None,
        error=None,
        status="pending",
        source_versions={},
        completed_at=None,
    )

    db = MagicMock()
    db.get.return_value = row

    customer = SimpleNamespace(customer_id=uuid4())

    reply = {
        "answer": "Your SSN is 123-45-6789.",
        "evidence": [
            {
                "file_id": str(uuid4()),
                "content": "Phone: 214-555-0199",
            }
        ],
    }

    with patch.object(chat_history, "source_versions", return_value={}):
        chat_history.finish(
            db,
            customer,
            turn_id,
            reply=reply,
        )

    assert "123-45-6789" not in row.reply["answer"]
    assert "[SSN REDACTED]" in row.reply["answer"]

    assert "evidence" not in row.reply
    assert "214-555-0199" not in str(row.reply)

    assert row.status == "completed"
    db.commit.assert_called_once()


from app.services.chat_privacy import protect_chat_response


def test_protect_response_removes_raw_evidence():
    reply = {
        "answer": "Your SSN is 123-45-6789.",
        "citations": [
            {"file_id": "document-123", "page": 1}
        ],
        "evidence": [
            {
                "file_id": "document-123",
                "original_name": "Social Security Card.pdf",
                "content": "SSN: 123-45-6789",
            }
        ],
    }

    result = protect_chat_response(reply)

    assert "evidence" not in result
    assert "123-45-6789" not in result["answer"]
    assert result["citations"][0]["page"] == 1
    assert result["document_links"][0]["file_id"] == "document-123"


def test_protect_response_preserves_existing_links():
    reply = {
        "answer": "Please review your document.",
        "document_links": [
            {
                "file_id": "document-456",
                "original_name": "Bank Statement.pdf",
            }
        ],
        "evidence": [
            {
                "file_id": "document-456",
                "content": "Account: 123456789",
            }
        ],
    }

    result = protect_chat_response(reply)

    assert "evidence" not in result
    assert len(result["document_links"]) == 1
    assert result["document_links"][0]["file_id"] == "document-456"


def test_serialise_protects_chat_response(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import uuid4
    from app.services import chat_history

    monkeypatch.setattr(
        chat_history,
        "source_status",
        lambda db, customer, application_id, versions: {},
    )

    row = SimpleNamespace(
        turn_id=uuid4(),
        question="What is my SSN 123-45-6789?",
        reply={
            "answer": "Your SSN is 123-45-6789.",
            "citations": [
                {"file_id": "document-123", "page": 1}
            ],
            "evidence": [
                {
                    "file_id": "document-123",
                    "original_name": "Identity.pdf",
                    "page": 1,
                    "content": "SSN: 123-45-6789",
                }
            ],
        },
        status="completed",
        error=None,
        source_versions={},
        created_at=datetime.now(timezone.utc),
    )

    conversation = SimpleNamespace(application_id=uuid4())

    result = chat_history.serialise(
        None, None, conversation, row
    )

    assert "123-45-6789" not in result["question"]
    assert "123-45-6789" not in result["reply"]["answer"]
    assert "evidence" not in result["reply"]
    assert result["reply"]["citations"][0]["page"] == 1
    assert result["reply"]["document_links"][0]["original_name"] == "Identity.pdf"


def test_direct_chat_endpoint_protects_response(monkeypatch):
    from app.api.v1 import chat

    def fake_ask(body, db, customer):
        return {
            "answer": "Your SSN is 123-45-6789.",
            "citations": [
                {"file_id": "document-123", "page": 1}
            ],
            "evidence": [
                {
                    "file_id": "document-123",
                    "original_name": "Identity.pdf",
                    "page": 1,
                    "content": "SSN: 123-45-6789",
                }
            ],
        }

    monkeypatch.setattr(chat, "ask", fake_ask)

    result = chat.ask_endpoint(
        chat.Ask(question="What is my SSN?"),
        db=None,
        customer=None,
    )

    assert "123-45-6789" not in result["answer"]
    assert "evidence" not in result
    assert result["citations"][0]["page"] == 1
    assert result["document_links"][0]["original_name"] == "Identity.pdf"


def test_bank_account_number_is_redacted():
    from app.services.chat_privacy import redact_text

    result = redact_text(
        "Account number: 1234567890123456"
    )

    assert "1234567890123456" not in result
    assert "[ACCOUNT REDACTED]" in result


def test_mortgage_amount_is_preserved():
    from app.services.chat_privacy import redact_text

    result = redact_text(
        "The mortgage balance is $285,000 and monthly income is $6,500."
    )

    assert "$285,000" in result
    assert "$6,500" in result

def test_authenticated_http_chat_response_is_privacy_protected(monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient

    from app.main import app
    from app.api.v1 import chat
    from app.core.security import current_customer
    from app.db.session import get_db

    fake_customer = SimpleNamespace(customer_id="test-customer")
    fake_db = object()

    def fake_current_customer():
        return fake_customer

    def fake_get_db():
        return fake_db

    def fake_ask(body, db, customer):
        assert body.question == "What is my mortgage balance?"
        assert db is fake_db
        assert customer is fake_customer

        return {
            "answer": (
                "Your mortgage balance is $285,000. "
                "SSN: 123-45-6789. "
                "Phone: 214-555-0199."
            ),
            "citations": [
                {"file_id": "test-file-001", "page": 2}
            ],
            "evidence": [
                {
                    "file_id": "test-file-001",
                    "original_name": "mortgage_statement.pdf",
                    "page": 2,
                    "content": "SSN: 123-45-6789",
                }
            ],
        }

    monkeypatch.setattr(chat, "ask", fake_ask)

    app.dependency_overrides[current_customer] = fake_current_customer
    app.dependency_overrides[get_db] = fake_get_db

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/chat",
                json={"question": "What is my mortgage balance?"},
                headers={"Origin": "http://localhost:5173"},
            )

        assert response.status_code == 200

        data = response.json()

        assert "$285,000" in data["answer"]
        assert "123-45-6789" not in response.text
        assert "214-555-0199" not in response.text
        assert "[SSN REDACTED]" in data["answer"]
        assert "[PHONE REDACTED]" in data["answer"]

        assert "evidence" not in data

        assert data["citations"] == [
            {"file_id": "test-file-001", "page": 2}
        ]

        assert any(
            link["file_id"] == "test-file-001"
            for link in data["document_links"]
        )

    finally:
        app.dependency_overrides.pop(current_customer, None)
        app.dependency_overrides.pop(get_db, None)

def test_finish_preserves_source_versions_without_storing_evidence():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch
    from uuid import uuid4

    from app.services import chat_history

    turn_id = uuid4()
    file_id = str(uuid4())

    row = SimpleNamespace(
        reply=None,
        error=None,
        status="pending",
        source_versions={},
        completed_at=None,
    )

    db = MagicMock()
    db.get.return_value = row

    customer = SimpleNamespace(customer_id=uuid4())

    reply = {
        "answer": "The monthly income is $6,500.",
        "citations": [
            {"file_id": file_id, "page": 2}
        ],
        "evidence": [
            {
                "file_id": file_id,
                "original_name": "paystub.pdf",
                "page": 2,
                "content": "Sensitive raw document information",
            }
        ],
    }

    expected_versions = {file_id: "test-document-fingerprint"}

    with patch.object(
        chat_history,
        "source_versions",
        return_value=expected_versions,
    ) as mocked_source_versions:
        chat_history.finish(
            db,
            customer,
            turn_id,
            reply=reply,
        )

    assert "evidence" not in row.reply
    assert row.reply["answer"] == "The monthly income is $6,500."
    assert row.reply["citations"] == [{"file_id": file_id, "page": 2}]
    assert row.source_versions == expected_versions

    mocked_source_versions.assert_called_once_with(db, customer, reply)
    db.commit.assert_called_once()

def test_follow_up_remembers_previous_document():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from uuid import uuid4

    from app.services import chat_history

    file_id = uuid4()
    customer_id = uuid4()
    application_id = uuid4()
    conversation_id = uuid4()

    customer = SimpleNamespace(customer_id=customer_id)

    conversation = SimpleNamespace(
        conversation_id=conversation_id,
        application_id=application_id,
    )

    previous_turn = SimpleNamespace(
        status="completed",
        source_versions={str(file_id): "test-document-fingerprint"},
    )

    document = SimpleNamespace(
        file_id=file_id,
        customer_id=customer_id,
        application_id=application_id,
        original_name="paystub.pdf",
    )

    db = MagicMock()
    db.scalar.return_value = previous_turn
    db.scalars.return_value.all.return_value = [document]

    question = "And what about the annual amount in that same document?"

    resolved_question, clarification = chat_history.follow_up(
        db,
        customer,
        conversation,
        question,
    )

    assert clarification is None
    assert question in resolved_question
    assert "paystub.pdf" in resolved_question
    assert resolved_question.endswith("in paystub.pdf")

def test_follow_up_requests_clarification_for_multiple_documents():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from uuid import uuid4

    from app.services import chat_history

    customer_id = uuid4()
    application_id = uuid4()
    file_id_1 = uuid4()
    file_id_2 = uuid4()

    customer = SimpleNamespace(customer_id=customer_id)

    conversation = SimpleNamespace(
        conversation_id=uuid4(),
        application_id=application_id,
    )

    previous_turn = SimpleNamespace(
        status="completed",
        source_versions={
            str(file_id_1): "fingerprint-1",
            str(file_id_2): "fingerprint-2",
        },
    )

    documents = [
        SimpleNamespace(
            file_id=file_id_1,
            customer_id=customer_id,
            application_id=application_id,
            original_name="paystub_january.pdf",
        ),
        SimpleNamespace(
            file_id=file_id_2,
            customer_id=customer_id,
            application_id=application_id,
            original_name="paystub_february.pdf",
        ),
    ]

    db = MagicMock()
    db.scalar.return_value = previous_turn
    db.scalars.return_value.all.return_value = documents

    question = "And what about the annual amount in that document?"

    resolved_question, clarification = chat_history.follow_up(
        db,
        customer,
        conversation,
        question,
    )

    assert resolved_question == question
    assert clarification is not None
    assert "Which document do you mean?" in clarification["answer"]
    assert len(clarification["document_links"]) == 2

    returned_ids = {
        item["file_id"]
        for item in clarification["document_links"]
    }

    assert returned_ids == {str(file_id_1), str(file_id_2)}

def test_validated_answer_does_not_expose_support_quotes():
    from app.api.v1 import chat

    file_id = "11111111-1111-4111-8111-111111111111"

    passages = [
        {
            "file_id": file_id,
            "page": 1,
            "original_name": "paystub.pdf",
            "content": "Gross monthly income is $5,200.",
        }
    ]

    model_answer = {
        "answer": "The gross monthly income is $5,200.",
        "citations": [
            {"file_id": file_id, "page": 1}
        ],
        "support": [
            {
                "file_id": file_id,
                "page": 1,
                "quote": "Gross monthly income is $5,200.",
            }
        ],
    }

    result = chat._validated_answer(model_answer, passages)

    assert result["answer"] == "The gross monthly income is $5,200."
    assert result["citations"] == [{"file_id": file_id, "page": 1}]
    assert "support" not in result

def test_recent_context_returns_only_completed_turns():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from uuid import uuid4

    from app.services import chat_history

    conversation_id = uuid4()
    other_conversation_id = uuid4()

    conversation = SimpleNamespace(
        conversation_id=conversation_id
    )

    rows = [
        SimpleNamespace(
            conversation_id=conversation_id,
            status="completed",
            question="What is my monthly income?",
            reply={"answer": "Your monthly income is $5,200."},
        ),
        SimpleNamespace(
            conversation_id=conversation_id,
            status="completed",
            question="Which document shows that?",
            reply={"answer": "Your January paystub."},
        ),
    ]

    db = MagicMock()
    db.scalars.return_value.all.return_value = list(reversed(rows))

    context = chat_history.recent_context(
        db,
        conversation,
        limit=3,
    )

    assert len(context) == 2
    assert context[0]["question"] == "What is my monthly income?"
    assert context[0]["answer"] == "Your monthly income is $5,200."
    assert context[1]["question"] == "Which document shows that?"
    assert context[1]["answer"] == "Your January paystub."

    query = db.scalars.call_args.args[0]
    compiled = str(query)

    assert "conversation_id" in compiled
    assert "status" in compiled
    assert "LIMIT" in compiled.upper()

def test_recent_context_redacts_sensitive_information():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from uuid import uuid4

    from app.services import chat_history

    conversation = SimpleNamespace(
        conversation_id=uuid4()
    )

    previous_turn = SimpleNamespace(
        status="completed",
        question="My SSN is 123-45-6789. What is my income?",
        reply={
            "answer": "Your phone number is 214-555-1234."
        },
    )

    db = MagicMock()
    db.scalars.return_value.all.return_value = [previous_turn]

    context = chat_history.recent_context(
        db,
        conversation,
        limit=3,
    )

    assert len(context) == 1

    assert "123-45-6789" not in context[0]["question"]
    assert "214-555-1234" not in context[0]["answer"]

    assert "[SSN REDACTED]" in context[0]["question"]
    assert "[PHONE REDACTED]" in context[0]["answer"]

def test_prompt_includes_previous_conversation_safely():
    from app.api.v1 import chat

    context = [
        {
            "question": "What is my monthly income?",
            "answer": "Your monthly income is $5,200.",
        },
        {
            "question": "My SSN is 123-45-6789. What about annually?",
            "answer": "The annual amount requires verification.",
        },
    ]

    passages = [
        {
            "file_id": "11111111-1111-4111-8111-111111111111",
            "page": 1,
            "original_name": "paystub.pdf",
            "content": "Gross monthly income: $5,200.",
        }
    ]

    prompt = chat._prompt(
        "How much is that annually?",
        passages,
        context=context,
    )

    assert "Previous conversation" in prompt
    assert "What is my monthly income?" in prompt
    assert "Your monthly income is $5,200." in prompt

    assert "123-45-6789" not in prompt
    assert "[SSN REDACTED]" in prompt

    assert "Gross monthly income: $5,200." in prompt
    assert "not evidence" in prompt
    assert "Support every factual claim using the Evidence section." in prompt

    assert prompt.endswith(
        "Question: How much is that annually?\n"
    )