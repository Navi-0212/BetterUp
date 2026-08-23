from datetime import date, datetime, timezone
import pytest
from src.models import Address, Employee
from src.validators import is_near_duplicate, validate_fields


@pytest.fixture
def base_employee():
    return Employee(
        employee_id="emp_1001",
        legal_first_name="Naveen",
        legal_last_name="Kumar",
        personal_email="naveen.demo@example.com",
        start_date=date(2026, 9, 15),
        address=Address(
            line1="123 MG Road",
            city="Bengaluru",
            state="KA",
            postal_code="560001",
            country="IN",
        ),
        position_title="AI Automation Engineer",
        department="People Technology",
        source_system="ASHBY",
        last_updated_at=datetime(2026, 8, 20, 10, 15, 0, tzinfo=timezone.utc),
        last_updated_by_event_id="evt-0001",
    )


def test_validate_fields_valid(base_employee):
    changed = {"legal_first_name", "legal_last_name", "address", "start_date"}
    valid, rejections = validate_fields(base_employee, changed)
    assert valid == changed
    assert len(rejections) == 0


def test_validate_fields_name_digits_and_empty(base_employee):
    base_employee.legal_first_name = "Naveen2"
    base_employee.legal_last_name = "   "
    changed = {"legal_first_name", "legal_last_name"}
    valid, rejections = validate_fields(base_employee, changed)
    assert valid == set()
    assert len(rejections) == 2
    actions = [r.action for r in rejections]
    assert actions == ["VALIDATION_REJECTED", "VALIDATION_REJECTED"]


def test_validate_fields_invalid_address(base_employee):
    base_employee.address.postal_code = " "
    changed = {"address", "position_title"}
    valid, rejections = validate_fields(base_employee, changed)
    assert valid == {"position_title"}
    assert len(rejections) == 1
    assert rejections[0].after_state["rejected_field"] == "address"


def test_validate_fields_past_start_date(base_employee):
    # Event timestamp is 2026-08-20, start_date is set to 2026-08-01
    base_employee.start_date = date(2026, 8, 1)
    changed = {"start_date", "legal_first_name"}
    valid, rejections = validate_fields(base_employee, changed)
    assert valid == {"legal_first_name"}
    assert len(rejections) == 1
    assert rejections[0].after_state["rejected_field"] == "start_date"


def test_is_near_duplicate(base_employee):
    # Same employee ID -> False
    same_emp = base_employee.model_copy()
    assert is_near_duplicate(base_employee, same_emp) is False

    # Different start date -> False
    diff_date_emp = base_employee.model_copy(
        update={"employee_id": "emp_2001", "start_date": date(2026, 10, 1)}
    )
    assert is_near_duplicate(base_employee, diff_date_emp) is False

    # Exact name match -> False
    exact_name_emp = base_employee.model_copy(
        update={"employee_id": "emp_2001", "legal_first_name": "Naveen", "legal_last_name": "Kumar"}
    )
    assert is_near_duplicate(base_employee, exact_name_emp) is False

    # Near duplicate (Sanjay vs Sanjai) -> True
    emp_sanjay = base_employee.model_copy(
        update={"employee_id": "emp_2001", "legal_first_name": "Sanjay", "legal_last_name": "Iyer", "start_date": date(2026, 9, 8)}
    )
    emp_sanjai = base_employee.model_copy(
        update={"employee_id": "emp_2002", "legal_first_name": "Sanjai", "legal_last_name": "Iyer", "start_date": date(2026, 9, 8)}
    )
    assert is_near_duplicate(emp_sanjai, emp_sanjay) is True

    # Completely different name -> False
    emp_arjun = base_employee.model_copy(
        update={"employee_id": "emp_1003", "legal_first_name": "Arjun", "legal_last_name": "Mehta", "start_date": date(2026, 9, 8)}
    )
    assert is_near_duplicate(emp_sanjay, emp_arjun) is False
