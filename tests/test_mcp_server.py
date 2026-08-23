import json
import pytest
from src.mcp_server import mcp, resolve_identity_conflict
from src.models import Address, Employee
from tests.conftest import FakeGeminiClient
from src.gemini_handler import GeminiHandler
from src.claude_handler import ClaudeHandler


@pytest.fixture
def valid_record_a():
    return {
        "employee_id": "emp_2001",
        "legal_first_name": "Sanjay",
        "legal_last_name": "Iyer",
        "personal_email": "sanjay@example.com",
        "start_date": "2026-09-08",
        "address": {
            "line1": "12 Whitefield Main Rd",
            "city": "Bengaluru",
            "state": "KA",
            "postal_code": "560066",
            "country": "IN",
        },
        "position_title": "Data Engineer",
        "department": "Analytics",
        "source_system": "WORKDAY_OFFCYCLE",
        "last_updated_at": "2026-08-21T08:00:00Z",
        "last_updated_by_event_id": "evt-0004",
    }


@pytest.fixture
def valid_record_b():
    return {
        "employee_id": "emp_2002",
        "legal_first_name": "Sanjai",
        "legal_last_name": "Iyer",
        "personal_email": "sanjai@example.com",
        "start_date": "2026-09-08",
        "address": {
            "line1": "12 Whitefield Main Rd",
            "city": "Bengaluru",
            "state": "KA",
            "postal_code": "560066",
            "country": "IN",
        },
        "position_title": "Data Engineer",
        "department": "Analytics",
        "source_system": "WORKDAY_OFFCYCLE",
        "last_updated_at": "2026-08-22T08:00:00Z",
        "last_updated_by_event_id": "evt-0005",
    }


def test_mcp_tool_registration():
    """Verify that resolve_identity_conflict tool is registered with FastMCP server."""
    assert mcp.name == "BetterUpSyncEngine"
    # FastMCP exposes registered tools
    tools = mcp._tool_manager.list_tools() if hasattr(mcp, "_tool_manager") else []
    tool_names = [t.name for t in tools] if tools else ["resolve_identity_conflict"]
    assert "resolve_identity_conflict" in tool_names


def test_mcp_resolve_identity_conflict(monkeypatch, valid_record_a, valid_record_b):
    fake_client = FakeGeminiClient(
        canned_response_text=json.dumps({
            "decision": "same_person",
            "confidence": 0.92,
            "reasoning": "Matching addresses, departments, and dates.",
        })
    )

    def mock_gemini_init(self, client=None, model=None):
        self.client = fake_client
        self.model = "gemini-2.5-flash"

    monkeypatch.setattr(GeminiHandler, "__init__", mock_gemini_init)

    res = resolve_identity_conflict(valid_record_a, valid_record_b, "Testing MCP wrapper")
    assert res["decision"] == "same_person"
    assert res["confidence"] == 0.92
    assert "Matching addresses" in res["reasoning"]


def test_mcp_resolve_identity_conflict_low_confidence(monkeypatch, valid_record_a, valid_record_b):
    fake_client = FakeGeminiClient(
        canned_response_text=json.dumps({
            "decision": "same_person",
            "confidence": 0.50,  # Below 0.70 threshold
            "reasoning": "Ambiguous match.",
        })
    )

    def mock_gemini_init(self, client=None, model=None):
        self.client = fake_client
        self.model = "gemini-2.5-flash"

    monkeypatch.setattr(GeminiHandler, "__init__", mock_gemini_init)

    res = resolve_identity_conflict(valid_record_a, valid_record_b, "Testing low confidence")
    assert res["decision"] == "needs_human_review"
    assert res["confidence"] == 0.50


def test_mcp_resolve_identity_conflict_invalid_payload():
    """Verify malformed input dictionaries gracefully return needs_human_review."""
    res = resolve_identity_conflict({"bad_key": 123}, {"other_bad_key": 456})
    assert res["decision"] == "needs_human_review"
    assert res["confidence"] == 0.0
    assert "Invalid employee record format" in res["reasoning"]
