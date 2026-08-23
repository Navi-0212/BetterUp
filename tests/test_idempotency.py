import json
from pathlib import Path
from src.models import ChangeEvent
from src.state_store import StateStore
from src.sync_engine import process_event


def test_idempotency_name_change(tmp_path, mock_connectors, no_sleep):
    """Processing name_change.json twice must result in exactly 1 write call per downstream connector."""
    store = StateStore(tmp_path)
    fixture_path = Path("sample_events/name_change.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    event = ChangeEvent.model_validate(data)

    # First execution: writes to target systems
    res1 = process_event(
        event=event,
        store=store,
        connectors=mock_connectors,
        sleep_fn=no_sleep,
    )
    assert len(res1.systems_written) > 0
    assert len(res1.systems_failed) == 0

    # Record call counts after first run
    call_counts_run1 = {
        name: conn.call_count for name, conn in mock_connectors.items()
    }
    for sys in res1.systems_written:
        assert call_counts_run1[sys.lower()] == 1

    # Second execution: replay of the same event
    res2 = process_event(
        event=event,
        store=store,
        connectors=mock_connectors,
        sleep_fn=no_sleep,
    )

    # Call counts must NOT increase because the ACKED ledger check short-circuits writes
    for name, conn in mock_connectors.items():
        assert conn.call_count == call_counts_run1[name]
