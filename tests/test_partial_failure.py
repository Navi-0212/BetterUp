import json
from pathlib import Path
from src.models import ChangeEvent
from src.state_store import StateStore
from src.sync_engine import process_event


def test_partial_failure_isolation(tmp_path, mock_connectors, no_sleep):
    """A forced expoIT failure must not block Workday/Okta writes, and expoIT must reach FAILED in needs_attention()."""
    store = StateStore(tmp_path)
    fixture_path = Path("sample_events/offcycle_hire.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Set employee_id to trigger simulated expoIT error
    data["employee_id"] = "emp_offcycle_test"
    data["raw_payload"]["employee_id"] = "emp_offcycle_test"

    event = ChangeEvent.model_validate(data)

    res = process_event(
        event=event,
        store=store,
        connectors=mock_connectors,
        sleep_fn=no_sleep,
    )

    # expoIT fails while other systems succeed
    assert "EXPOIT" in res.systems_failed
    assert "WORKDAY" in res.systems_written
    assert "OKTA" in res.systems_written
    assert "LUMOS" in res.systems_written
    assert "TRACKER" in res.systems_written

    # Check mock expoIT attempts
    expo_conn = mock_connectors["expoit"]
    assert expo_conn.call_count == 3

    # Check store needs_attention()
    attention_entries = store.needs_attention()
    assert len(attention_entries) == 1
    failed_entry = attention_entries[0]
    assert failed_entry.target_system == "EXPOIT"
    assert failed_entry.status == "FAILED"
    assert failed_entry.attempts == 3
    assert "Simulated expoIT transient" in (failed_entry.error_message or "")
