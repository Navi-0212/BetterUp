import json
import os
from pathlib import Path
import pytest
from dotenv import load_dotenv

load_dotenv()

from src.gemini_handler import GeminiHandler
from src.claude_handler import ClaudeHandler
from src.models import ChangeEvent
from src.sync_engine import normalize_event, process_event
from tests.conftest import FakeGeminiClient


def test_gemini_handler_high_confidence(seeded_store):
    emp_2001 = seeded_store.get_employee("emp_2001")
    assert emp_2001 is not None

    emp_2002 = emp_2001.model_copy(
        update={"employee_id": "emp_2002", "legal_first_name": "Sanjai"}
    )

    client = FakeGeminiClient(
        canned_response_text=json.dumps(
            {
                "decision": "same_person",
                "confidence": 0.95,
                "reasoning": "Name typo with identical address and start date.",
            }
        )
    )
    handler = GeminiHandler(client=client)
    res = handler.resolve_conflict(emp_2001, emp_2002, "Potential duplicate test")

    assert res.decision == "same_person"
    assert res.confidence == 0.95
    assert "typo" in res.reasoning
    assert client.models.call_count == 1


def test_gemini_handler_low_confidence_gating(seeded_store):
    emp_2001 = seeded_store.get_employee("emp_2001")
    assert emp_2001 is not None

    emp_2002 = emp_2001.model_copy(
        update={"employee_id": "emp_2002", "legal_first_name": "Sanjai"}
    )

    client = FakeGeminiClient(
        canned_response_text=json.dumps(
            {
                "decision": "same_person",
                "confidence": 0.65,  # Below 0.70 threshold
                "reasoning": "Uncertain if Sanjai is Sanjay.",
            }
        )
    )
    handler = GeminiHandler(client=client)
    res = handler.resolve_conflict(emp_2001, emp_2002, "Low confidence test")

    # Low confidence must be force overridden to needs_human_review
    assert res.decision == "needs_human_review"
    assert res.confidence == 0.65
    assert "below threshold" in res.reasoning


def test_gemini_handler_malformed_json(seeded_store):
    emp_2001 = seeded_store.get_employee("emp_2001")
    assert emp_2001 is not None
    emp_2002 = emp_2001.model_copy(
        update={"employee_id": "emp_2002", "legal_first_name": "Sanjai"}
    )

    client = FakeGeminiClient(canned_response_text="I think they might be the same person.")
    handler = GeminiHandler(client=client)
    res = handler.resolve_conflict(emp_2001, emp_2002, "Malformed test")

    assert res.decision == "needs_human_review"
    assert res.confidence == 0.0
    assert "fallback due to error" in res.reasoning


def test_ambiguous_name_conflict_pipeline(seeded_store, mock_connectors, no_sleep):
    """End-to-end verification: ambiguous_name_conflict.json triggers near-duplicate against pre-seeded emp_2001."""
    fixture_path = Path("sample_events/ambiguous_name_conflict.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    event = ChangeEvent.model_validate(data)

    client = FakeGeminiClient(
        canned_response_text=json.dumps(
            {
                "decision": "needs_human_review",
                "confidence": 0.50,
                "reasoning": "Too ambiguous to auto-resolve.",
            }
        )
    )
    handler = GeminiHandler(client=client)

    res = process_event(
        event=event,
        store=seeded_store,
        connectors=mock_connectors,
        claude_handler=handler,
        sleep_fn=no_sleep,
    )

    assert res.needs_human_review is True
    assert res.conflict_resolution is not None
    assert res.conflict_resolution.decision == "needs_human_review"
    assert len(res.systems_written) == 0  # Does not propagate on human review


@pytest.mark.integration
@pytest.mark.skipif(
    not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
    reason="Requires GEMINI_API_KEY",
)
def test_gemini_integration_real_api(seeded_store, mock_connectors, no_sleep):
    """Live integration test hitting real Gemini API models endpoint."""
    fixture_path = Path("sample_events/ambiguous_name_conflict.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    event = ChangeEvent.model_validate(data)
    handler = GeminiHandler()  # Uses real client and GEMINI_API_KEY

    res = process_event(
        event=event,
        store=seeded_store,
        connectors=mock_connectors,
        claude_handler=handler,
        sleep_fn=no_sleep,
    )

    assert res.conflict_resolution is not None
    assert res.conflict_resolution.decision in ["same_person", "different_person", "needs_human_review"]
    assert 0.0 <= res.conflict_resolution.confidence <= 1.0
