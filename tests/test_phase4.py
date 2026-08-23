from datetime import date, datetime, timezone
import pytest
from src.connectors import (
    FakeWorkdayConnector,
    FakeOktaConnector,
    FakeLumosConnector,
    FakeExpoITConnector,
    FakeTrackerConnector,
)
from src.models import Address, ChangeEvent, Employee, FieldDelta
from src.state_store import StateStore
from src.sync_engine import normalize_event, process_event, write_with_retry


@pytest.fixture
def connectors():
    return {
        "workday": FakeWorkdayConnector(),
        "okta": FakeOktaConnector(),
        "lumos": FakeLumosConnector(),
        "expoit": FakeExpoITConnector(),
        "tracker": FakeTrackerConnector(),
    }


def test_normalize_event_offcycle(tmp_path):
    store = StateStore(tmp_path)
    event = ChangeEvent(
        event_id="evt-0004",
        event_type="OFFCYCLE_HIRE_DETECTED",
        employee_id="emp_2001",
        source_system="WORKDAY",
        changed_fields={},
        raw_payload={
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
            "position_title": "Contractor - Data",
            "department": "Analytics",
        },
        received_at=datetime(2026, 8, 21, 8, 0, 0, tzinfo=timezone.utc),
    )
    emp = normalize_event(event, store)
    assert emp.employee_id == "emp_2001"
    assert emp.source_system == "WORKDAY_OFFCYCLE"
    assert emp.legal_first_name == "Sanjay"
    assert emp.start_date == date(2026, 9, 8)


def test_write_with_retry_backoff_and_idempotency(tmp_path):
    store = StateStore(tmp_path)
    emp = Employee(
        employee_id="emp_1001",
        legal_first_name="Naveen",
        legal_last_name="Kumar",
        personal_email="naveen@example.com",
        start_date=date(2026, 9, 15),
        address=Address(
            line1="123 MG Rd",
            city="Bengaluru",
            state="KA",
            postal_code="560001",
            country="IN",
        ),
        position_title="Engineer",
        department="Engineering",
        source_system="ASHBY",
        last_updated_at=datetime.now(timezone.utc),
        last_updated_by_event_id="evt-0001",
    )

    delays: list[float] = []

    def mock_sleep(d: float):
        delays.append(d)

    # 1. Normal success
    wd = FakeWorkdayConnector()
    entry = write_with_retry(
        connector=wd,
        employee=emp,
        idempotency_key="key-test-1",
        store=store,
        sleep_fn=mock_sleep,
    )
    assert entry.status == "ACKED"
    assert len(delays) == 0
    assert wd.call_count == 1

    # 2. Idempotent replay: should skip write
    entry_replay = write_with_retry(
        connector=wd,
        employee=emp,
        idempotency_key="key-test-1",
        store=store,
        sleep_fn=mock_sleep,
    )
    assert entry_replay.status == "ACKED"
    assert wd.call_count == 1  # Not incremented


def test_write_with_retry_failure_transition(tmp_path):
    store = StateStore(tmp_path)
    emp_failing = Employee(
        employee_id="emp_offcycle_test",
        legal_first_name="Test",
        legal_last_name="Fail",
        personal_email="fail@example.com",
        start_date=date(2026, 9, 15),
        address=Address(
            line1="123 MG Rd",
            city="Bengaluru",
            state="KA",
            postal_code="560001",
            country="IN",
        ),
        position_title="Engineer",
        department="Engineering",
        source_system="ASHBY",
        last_updated_at=datetime.now(timezone.utc),
        last_updated_by_event_id="evt-0001",
    )

    delays: list[float] = []
    expo = FakeExpoITConnector()
    entry = write_with_retry(
        connector=expo,
        employee=emp_failing,
        idempotency_key="key-fail-1",
        store=store,
        sleep_fn=lambda d: delays.append(d),
    )
    assert entry.status == "FAILED"
    assert entry.attempts == 3
    assert len(delays) == 2  # Delays for attempt 1 and 2
    assert pytest.approx(delays[0]) == 0.2
    assert pytest.approx(delays[1]) == 0.4
    assert len(store.needs_attention()) == 1


def test_process_event_dry_run(tmp_path, connectors):
    store = StateStore(tmp_path)
    event = ChangeEvent(
        event_id="evt-0001",
        event_type="FIELD_CHANGE",
        employee_id="emp_1001",
        source_system="ASHBY",
        changed_fields={
            "legal_last_name": FieldDelta(old_value="Kumar", new_value="Kumaar")
        },
        raw_payload={
            "employee_id": "emp_1001",
            "legal_first_name": "Naveen",
            "legal_last_name": "Kumaar",
            "personal_email": "naveen@example.com",
            "start_date": "2026-09-15",
            "address": {
                "line1": "123 MG Rd",
                "city": "Bengaluru",
                "state": "KA",
                "postal_code": "560001",
                "country": "IN",
            },
            "position_title": "Engineer",
            "department": "Engineering",
        },
        received_at=datetime(2026, 8, 20, 10, 15, 0, tzinfo=timezone.utc),
    )

    res = process_event(
        event=event,
        store=store,
        connectors=connectors,
        sleep_fn=lambda _: None,
        dry_run=True,
    )
    assert res.fields_propagated == ["legal_last_name"]
    assert len(res.systems_written) > 0
    # Dry run should NOT mutate store
    assert store.get_employee("emp_1001") is None
    assert len(store.all_employees()) == 0
