import json
from pathlib import Path
import pytest
from src.connectors import (
    FakeWorkdayConnector,
    FakeOktaConnector,
    FakeLumosConnector,
    FakeExpoITConnector,
    FakeTrackerConnector,
)
from src.models import ChangeEvent
from src.state_store import StateStore
from src.sync_engine import normalize_event


class FakeGeminiResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeGeminiModelsAPI:
    def __init__(self, canned_response_text: str = '{"decision": "same_person", "confidence": 0.95, "reasoning": "Identical attributes"}') -> None:
        self.canned_response_text = canned_response_text
        self.call_count = 0
        self.last_kwargs: dict = {}

    def generate_content(self, model: str, contents: str, config: object = None) -> FakeGeminiResponse:
        self.call_count += 1
        self.last_kwargs = {"model": model, "contents": contents, "config": config}
        return FakeGeminiResponse(self.canned_response_text)


class FakeGeminiClient:
    def __init__(self, canned_response_text: str = '{"decision": "same_person", "confidence": 0.95, "reasoning": "Identical attributes"}') -> None:
        self.models = FakeGeminiModelsAPI(canned_response_text)


# Keep FakeAnthropicClient as alias for compatibility
FakeAnthropicClient = FakeGeminiClient


@pytest.fixture
def no_sleep():
    """Injectable no-op sleep function so retries execute with zero delay."""
    return lambda _: None


@pytest.fixture
def mock_connectors():
    """Dictionary containing instances of all five fake connectors."""
    return {
        "workday": FakeWorkdayConnector(),
        "okta": FakeOktaConnector(),
        "lumos": FakeLumosConnector(),
        "expoit": FakeExpoITConnector(),
        "tracker": FakeTrackerConnector(),
    }


@pytest.fixture
def seeded_store(tmp_path):
    """A StateStore pointed at tmp_path, pre-seeded with emp_2001 from offcycle_hire.json."""
    store = StateStore(tmp_path)
    fixture_path = Path("sample_events/offcycle_hire.json")
    if fixture_path.exists():
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        event = ChangeEvent.model_validate(data)
        emp_2001 = normalize_event(event, store)
        store.save_employee(emp_2001)
    return store


@pytest.fixture
def fake_gemini_client():
    """Fake Gemini client returning canned same_person JSON."""
    return FakeGeminiClient()


@pytest.fixture
def fake_anthropic_client():
    """Fake Anthropic client returning canned same_person JSON."""
    return FakeGeminiClient()
