import json
from pathlib import Path
import pytest
from src.main import main
from src.models import Employee, Address
from src.state_store import StateStore
from src.audit_log import AuditLog


def test_cli_dry_run_no_mutations(tmp_path, capsys):
    data_dir = tmp_path / "data"
    ret = main([
        "--event", "sample_events/name_change.json",
        "--data-dir", str(data_dir),
        "--dry-run",
    ])

    assert ret == 0
    captured = capsys.readouterr()
    assert "MODE: DRY RUN" in captured.out
    assert "Fields Propagated: ['legal_last_name']" in captured.out
    assert "Systems Written:   ['LUMOS', 'OKTA', 'TRACKER', 'WORKDAY']" in captured.out
    assert "STATUS: SUCCESS" in captured.out

    # Assert no files or mutations were written
    store = StateStore(data_dir)
    assert len(store.all_employees()) == 0
    audit_log = AuditLog(data_dir / "audit_log.jsonl")
    assert len(audit_log.read_all()) == 0


def test_cli_successful_execution(tmp_path, capsys):
    data_dir = tmp_path / "data"
    ret = main([
        "--event", "sample_events/name_change.json",
        "--data-dir", str(data_dir),
    ])

    assert ret == 0
    captured = capsys.readouterr()
    assert "STATUS: SUCCESS" in captured.out
    assert "Systems Written:   ['LUMOS', 'OKTA', 'TRACKER', 'WORKDAY']" in captured.out

    # State verification
    store = StateStore(data_dir)
    emp = store.get_employee("emp_1001")
    assert emp is not None
    assert emp.legal_last_name == "Kumaar"

    audit_log = AuditLog(data_dir / "audit_log.jsonl")
    entries = audit_log.read_all()
    assert len(entries) > 0


def test_cli_missing_event_file(tmp_path, capsys):
    ret = main([
        "--event", "sample_events/non_existent.json",
        "--data-dir", str(tmp_path),
    ])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Error: Event file not found" in captured.err


def test_cli_invalid_json_event(tmp_path, capsys):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{invalid_json: 123", encoding="utf-8")

    ret = main([
        "--event", str(bad_file),
        "--data-dir", str(tmp_path),
    ])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Error loading event JSON" in captured.err


def test_cli_failed_system_exit_code(tmp_path, capsys):
    data_dir = tmp_path / "data"
    # Event with employee_id="emp_offcycle_test" triggers simulated expoIT failure
    offcycle_event = {
        "event_id": "evt-fail-test",
        "event_type": "OFFCYCLE_HIRE_DETECTED",
        "employee_id": "emp_offcycle_test",
        "source_system": "WORKDAY",
        "changed_fields": {},
        "raw_payload": {
            "employee_id": "emp_offcycle_test",
            "legal_first_name": "Test",
            "legal_last_name": "User",
            "personal_email": "test.user@example.com",
            "start_date": "2026-09-08",
            "address": {
                "line1": "123 Main St",
                "city": "Bengaluru",
                "state": "KA",
                "postal_code": "560001",
                "country": "IN",
            },
            "position_title": "Tester",
            "department": "QA",
        },
        "received_at": "2026-08-21T08:00:00Z",
    }
    event_file = tmp_path / "fail_event.json"
    event_file.write_text(json.dumps(offcycle_event), encoding="utf-8")

    ret = main([
        "--event", str(event_file),
        "--data-dir", str(data_dir),
    ])

    assert ret == 1
    captured = capsys.readouterr()
    assert "STATUS: FAILED" in captured.out
    assert "EXPOIT" in captured.out


def test_cli_needs_human_review_exit_code(tmp_path, capsys, monkeypatch):
    data_dir = tmp_path / "data"
    store = StateStore(data_dir)

    # Pre-seed emp_2001 (Sanjay Iyer)
    emp_2001 = Employee(
        employee_id="emp_2001",
        legal_first_name="Sanjay",
        legal_last_name="Iyer",
        preferred_name=None,
        personal_email="sanjay.demo@example.com",
        start_date="2026-09-08",
        address=Address(
            line1="12 Whitefield Main Rd",
            city="Bengaluru",
            state="KA",
            postal_code="560066",
            country="IN",
        ),
        position_title="Contractor - Data",
        department="Analytics",
        source_system="WORKDAY_OFFCYCLE",
        status="ACTIVE",
        last_updated_at="2026-08-21T08:00:00Z",
        last_updated_by_event_id="evt-0004",
    )
    store.save_employee(emp_2001)

    from tests.conftest import FakeGeminiClient
    from src.gemini_handler import GeminiHandler

    fake_client = FakeGeminiClient(
        canned_response_text=json.dumps({
            "decision": "needs_human_review",
            "confidence": 0.50,
            "reasoning": "Low confidence match.",
        })
    )

    def mock_gemini_init(self, client=None, model=None):
        self.client = fake_client
        self.model = "gemini-2.5-flash"

    monkeypatch.setattr(GeminiHandler, "__init__", mock_gemini_init)

    # Run ambiguous_name_conflict.json (Sanjai Iyer) -> triggers needs_human_review
    ret = main([
        "--event", "sample_events/ambiguous_name_conflict.json",
        "--data-dir", str(data_dir),
    ])

    assert ret == 1
    captured = capsys.readouterr()
    assert "STATUS: NEEDS_HUMAN_REVIEW" in captured.out
