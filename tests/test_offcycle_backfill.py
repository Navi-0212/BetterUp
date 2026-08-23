import json
from pathlib import Path
from src.models import ChangeEvent
from src.state_store import StateStore
from src.sync_engine import process_event


def test_offcycle_hire_provenance(tmp_path, mock_connectors, no_sleep):
    """Off-cycle hire from Workday must be saved with source_system=WORKDAY_OFFCYCLE and propagate to all downstream systems without fictitious Ashby records."""
    store = StateStore(tmp_path)
    fixture_path = Path("sample_events/offcycle_hire.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    event = ChangeEvent.model_validate(data)

    res = process_event(
        event=event,
        store=store,
        connectors=mock_connectors,
        sleep_fn=no_sleep,
    )

    # 1. Verification of downstream writes
    assert set(res.systems_written) == {"WORKDAY", "OKTA", "LUMOS", "EXPOIT", "TRACKER"}
    assert len(res.systems_failed) == 0

    # 2. Verification of StateStore record and provenance
    saved_emp = store.get_employee("emp_2001")
    assert saved_emp is not None
    assert saved_emp.employee_id == "emp_2001"
    assert saved_emp.legal_first_name == "Sanjay"
    assert saved_emp.legal_last_name == "Iyer"
    assert saved_emp.source_system == "WORKDAY_OFFCYCLE"
    assert saved_emp.last_updated_by_event_id == "evt-0004"

    # 3. Ensure no fictitious Ashby records exist
    all_employees = store.all_employees()
    assert len(all_employees) == 1
    assert all_employees[0].source_system == "WORKDAY_OFFCYCLE"
