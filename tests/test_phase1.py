from datetime import date, datetime, timezone
import pytest
from src.models import Address, Employee, FieldDelta, ChangeEvent, LedgerEntry, AuditLogEntry, ConflictResolution, ProcessResult
from src.state_store import StateStore


def test_models_instantiation():
    addr = Address(
        line1="123 MG Road",
        line2=None,
        city="Bengaluru",
        state="KA",
        postal_code="560001",
        country="IN"
    )
    emp = Employee(
        employee_id="emp_1001",
        legal_first_name="Naveen",
        legal_last_name="Kumar",
        preferred_name=None,
        personal_email="naveen.demo@example.com",
        work_email=None,
        start_date=date(2026, 9, 15),
        address=addr,
        position_title="AI Automation Engineer",
        department="People Technology",
        manager_id="emp_0500",
        source_system="ASHBY",
        last_updated_at=datetime.now(timezone.utc),
        last_updated_by_event_id="evt-0001"
    )
    assert emp.employee_id == "emp_1001"
    assert emp.source_system == "ASHBY"

    delta = FieldDelta(old_value="Kumar", new_value="Kumaar")
    assert delta.old_value == "Kumar"

    event = ChangeEvent(
        event_id="evt-0001",
        event_type="FIELD_CHANGE",
        employee_id="emp_1001",
        source_system="ASHBY",
        changed_fields={"legal_last_name": delta},
        raw_payload={},
        received_at=datetime.now(timezone.utc)
    )
    assert event.event_id == "evt-0001"

    ledger = LedgerEntry(
        employee_id="emp_1001",
        target_system="WORKDAY",
        idempotency_key="key-123",
        status="ACKED",
        attempts=1,
        system_ref_id="WD-001"
    )
    assert ledger.status == "ACKED"

    res = ConflictResolution(
        decision="same_person",
        confidence=0.95,
        reasoning="Matching names and details"
    )
    assert res.decision == "same_person"


def test_state_store(tmp_path):
    store = StateStore(data_dir=tmp_path)
    addr = Address(
        line1="123 MG Road",
        city="Bengaluru",
        state="KA",
        postal_code="560001",
        country="IN"
    )
    emp = Employee(
        employee_id="emp_1001",
        legal_first_name="Naveen",
        legal_last_name="Kumar",
        personal_email="naveen.demo@example.com",
        start_date=date(2026, 9, 15),
        address=addr,
        position_title="AI Automation Engineer",
        department="People Technology",
        source_system="ASHBY",
        last_updated_at=datetime.now(timezone.utc),
        last_updated_by_event_id="evt-0001"
    )

    # Save & Retrieve employee
    store.save_employee(emp)
    retrieved = store.get_employee("emp_1001")
    assert retrieved is not None
    assert retrieved.legal_first_name == "Naveen"
    assert len(store.all_employees()) == 1

    # Non-existent employee
    assert store.get_employee("non_existent") is None

    # Ledger entry save & retrieve
    entry_acked = LedgerEntry(
        employee_id="emp_1001",
        target_system="WORKDAY",
        idempotency_key="key-acked",
        status="ACKED",
        attempts=1
    )
    entry_failed = LedgerEntry(
        employee_id="emp_1001",
        target_system="EXPOIT",
        idempotency_key="key-failed",
        status="FAILED",
        attempts=3,
        error_message="Network timeout"
    )

    store.save_ledger_entry(entry_acked)
    store.save_ledger_entry(entry_failed)

    assert store.get_ledger_entry("key-acked").status == "ACKED"
    assert store.get_ledger_entry("key-failed").status == "FAILED"
    assert store.get_ledger_entry("key-none") is None

    # needs_attention
    failed_items = store.needs_attention()
    assert len(failed_items) == 1
    assert failed_items[0].idempotency_key == "key-failed"
