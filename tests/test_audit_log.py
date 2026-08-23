import json
from datetime import datetime, timezone
from pathlib import Path
from src.audit_log import AuditLog
from src.models import (
    Address,
    AuditLogEntry,
    ChangeEvent,
    ConflictResolution,
    Employee,
    FieldDelta,
)
from src.state_store import StateStore
from src.sync_engine import process_event
from tests.conftest import FakeAnthropicClient
from src.claude_handler import ClaudeHandler


def test_audit_log_basic(tmp_path):
    log_file = tmp_path / "audit_log.jsonl"
    audit = AuditLog(log_file)
    assert len(audit.read_all()) == 0


def test_audit_log_append_and_query_helpers(tmp_path):
    log_file = tmp_path / "audit_log.jsonl"
    audit = AuditLog(log_file)

    entry1 = AuditLogEntry(
        event_id="evt-1",
        employee_id="emp_100",
        target_system="WORKDAY",
        action="FIELD_CHANGE_PROPAGATED",
        before_state={"status": "old"},
        after_state={"status": "new"},
        triggered_by="test",
        timestamp=datetime.now(timezone.utc),
    )
    entry2 = AuditLogEntry(
        event_id="evt-2",
        employee_id="emp_200",
        target_system=None,
        action="VALIDATION_REJECTED",
        before_state=None,
        after_state={"rejected_field": "start_date"},
        triggered_by="validators",
        timestamp=datetime.now(timezone.utc),
    )

    audit.append(entry1)
    audit.append(entry2)

    assert len(audit.read_all()) == 2
    assert len(audit.get_entries_by_employee("emp_100")) == 1
    assert audit.get_entries_by_employee("emp_100")[0].event_id == "evt-1"
    assert len(audit.get_entries_by_event("evt-2")) == 1
    assert len(audit.get_entries_by_action("VALIDATION_REJECTED")) == 1
    assert len(audit.get_entries_by_action("NO_OP_SKIPPED")) == 0

    audit.clear()
    assert len(audit.read_all()) == 0


def test_audit_log_corrupt_lines_tolerance(tmp_path):
    log_file = tmp_path / "audit_log.jsonl"
    log_file.write_text(
        "INVALID JSON LINE\n"
        '{"event_id":"evt-1","employee_id":"emp_1","target_system":null,"action":"NO_OP_SKIPPED","before_state":null,"after_state":null,"triggered_by":"test","timestamp":"2026-08-20T10:00:00Z"}\n'
        "\n"
        "{incomplete json\n",
        encoding="utf-8",
    )

    audit = AuditLog(log_file)
    entries = audit.read_all()
    assert len(entries) == 1
    assert entries[0].event_id == "evt-1"


def test_audit_log_lifecycle_actions(tmp_path, mock_connectors, no_sleep):
    log_file = tmp_path / "audit_log.jsonl"
    audit = AuditLog(log_file)
    store = StateStore(tmp_path)

    # 1. Event with valid change and no-op delta
    event = ChangeEvent(
        event_id="evt-audit-1",
        event_type="FIELD_CHANGE",
        employee_id="emp_1001",
        source_system="ASHBY",
        changed_fields={
            "legal_last_name": FieldDelta(old_value="Kumar", new_value="Kumaar"),
            "personal_email": FieldDelta(old_value="same@demo.com", new_value="same@demo.com"),  # No-Op
        },
        raw_payload={
            "employee_id": "emp_1001",
            "legal_first_name": "Naveen",
            "legal_last_name": "Kumaar",
            "personal_email": "same@demo.com",
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
        received_at="2026-08-20T10:15:00Z",
    )

    process_event(
        event=event,
        store=store,
        connectors=mock_connectors,
        sleep_fn=no_sleep,
        audit_log=audit,
    )

    entries = audit.read_all()
    actions = [e.action for e in entries]

    assert "NO_OP_SKIPPED" in actions
    assert "FIELD_CHANGE_PROPAGATED" in actions

    # 2. Replay same event -> produces NO_OP_SKIPPED for writes
    process_event(
        event=event,
        store=store,
        connectors=mock_connectors,
        sleep_fn=no_sleep,
        audit_log=audit,
    )

    entries_after_replay = audit.read_all()
    actions_replay = [e.action for e in entries_after_replay]
    assert actions_replay.count("NO_OP_SKIPPED") > actions.count("NO_OP_SKIPPED")


def test_audit_log_validation_rejected_action(tmp_path, mock_connectors, no_sleep):
    log_file = tmp_path / "audit_log.jsonl"
    audit = AuditLog(log_file)
    store = StateStore(tmp_path)

    # Event with invalid numeric first name
    event = ChangeEvent(
        event_id="evt-val-reject",
        event_type="FIELD_CHANGE",
        employee_id="emp_1002",
        source_system="ASHBY",
        changed_fields={
            "legal_first_name": FieldDelta(old_value="Jane", new_value="Jane99"),
        },
        raw_payload={
            "employee_id": "emp_1002",
            "legal_first_name": "Jane99",
            "legal_last_name": "Doe",
            "personal_email": "jane@example.com",
            "start_date": "2026-09-15",
            "address": {
                "line1": "100 Pine St",
                "city": "San Francisco",
                "state": "CA",
                "postal_code": "94111",
                "country": "US",
            },
            "position_title": "Designer",
            "department": "Design",
        },
        received_at="2026-08-20T10:15:00Z",
    )

    result = process_event(
        event=event,
        store=store,
        connectors=mock_connectors,
        sleep_fn=no_sleep,
        audit_log=audit,
    )

    assert "legal_first_name" in result.fields_rejected
    rejection_entries = audit.get_entries_by_action("VALIDATION_REJECTED")
    assert len(rejection_entries) == 1
    assert rejection_entries[0].after_state["rejected_field"] == "legal_first_name"


def test_audit_log_claude_conflict_actions(tmp_path, mock_connectors, no_sleep):
    log_file = tmp_path / "audit_log.jsonl"
    audit = AuditLog(log_file)
    store = StateStore(tmp_path)

    # Seed existing employee
    existing = Employee(
        employee_id="emp_2001",
        legal_first_name="Jane",
        legal_last_name="Doe",
        preferred_name=None,
        personal_email="jane.doe@personal.com",
        work_email="jane.doe@company.com",
        start_date="2026-09-01",
        address=Address(
            line1="100 Market St",
            city="San Francisco",
            state="CA",
            postal_code="94105",
            country="US",
        ),
        position_title="Software Engineer",
        department="Engineering",
        source_system="ASHBY",
        status="ACTIVE",
        last_updated_at="2026-08-01T10:00:00Z",
        last_updated_by_event_id="evt_seed_2001",
    )
    store.save_employee(existing)

    # Incoming near duplicate hire (Jane Dow vs Jane Doe)
    event = ChangeEvent(
        event_id="evt_claude_audit",
        event_type="OFFCYCLE_HIRE_DETECTED",
        employee_id="emp_2002",
        source_system="WORKDAY",
        changed_fields={},
        raw_payload={
            "employee_id": "emp_2002",
            "legal_first_name": "Jane",
            "legal_last_name": "Dow",
            "personal_email": "jane.dow@personal.com",
            "start_date": "2026-09-01",
            "address": {
                "line1": "100 Market St",
                "city": "San Francisco",
                "state": "CA",
                "postal_code": "94105",
                "country": "US",
            },
            "position_title": "Software Engineer",
            "department": "Engineering",
        },
        received_at="2026-08-20T10:00:00Z",
    )

    # 1. High confidence -> CLAUDE_CONFLICT_RESOLVED
    fake_client_resolved = FakeAnthropicClient(
        json.dumps({
            "decision": "same_person",
            "confidence": 0.95,
            "reasoning": "Matching address, role, start date, slight typo in last name.",
        })
    )
    handler_resolved = ClaudeHandler(client=fake_client_resolved)
    process_event(
        event=event,
        store=store,
        connectors=mock_connectors,
        claude_handler=handler_resolved,
        sleep_fn=no_sleep,
        audit_log=audit,
    )

    resolved_entries = audit.get_entries_by_action("CLAUDE_CONFLICT_RESOLVED")
    assert len(resolved_entries) == 1
    assert resolved_entries[0].after_state["decision"] == "same_person"

    # 2. Low confidence -> NEEDS_HUMAN_REVIEW
    audit.clear()
    fake_client_review = FakeAnthropicClient(
        json.dumps({
            "decision": "different_person",
            "confidence": 0.55,  # Low confidence
            "reasoning": "Unclear similarity.",
        })
    )
    handler_review = ClaudeHandler(client=fake_client_review)
    process_event(
        event=event,
        store=store,
        connectors=mock_connectors,
        claude_handler=handler_review,
        sleep_fn=no_sleep,
        audit_log=audit,
    )

    review_entries = audit.get_entries_by_action("NEEDS_HUMAN_REVIEW")
    assert len(review_entries) == 1


def test_audit_log_dry_run_skips_writes(tmp_path, mock_connectors, no_sleep):
    log_file = tmp_path / "audit_log.jsonl"
    audit = AuditLog(log_file)
    store = StateStore(tmp_path)

    event = ChangeEvent(
        event_id="evt-dry-run",
        event_type="FIELD_CHANGE",
        employee_id="emp_1003",
        source_system="ASHBY",
        changed_fields={
            "legal_last_name": FieldDelta(old_value="Smith", new_value="Smithe"),
        },
        raw_payload={
            "employee_id": "emp_1003",
            "legal_first_name": "Bob",
            "legal_last_name": "Smithe",
            "personal_email": "bob@example.com",
            "start_date": "2026-09-15",
            "address": {
                "line1": "100 Main St",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country": "US",
            },
            "position_title": "Analyst",
            "department": "Data",
        },
        received_at="2026-08-20T10:15:00Z",
    )

    process_event(
        event=event,
        store=store,
        connectors=mock_connectors,
        sleep_fn=no_sleep,
        dry_run=True,
        audit_log=audit,
    )

    assert len(audit.read_all()) == 0
