from datetime import date, datetime, timezone
import pytest
from src.models import Address, Employee
from src.connectors import (
    FakeWorkdayConnector,
    FakeOktaConnector,
    FakeLumosConnector,
    FakeExpoITConnector,
    FakeTrackerConnector,
)


@pytest.fixture
def sample_employee():
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
        last_updated_at=datetime.now(timezone.utc),
        last_updated_by_event_id="evt-0001",
    )


def test_connectors_success(sample_employee):
    idempotency_key = "abc123def456"

    wd = FakeWorkdayConnector()
    res_wd = wd.write(sample_employee, idempotency_key)
    assert res_wd.success is True
    assert res_wd.system_ref_id.startswith("WD-emp_1001-abc123de")
    assert wd.call_count == 1

    okta = FakeOktaConnector()
    res_okta = okta.write(sample_employee, idempotency_key)
    assert res_okta.success is True
    assert res_okta.system_ref_id.startswith("OKTA-emp_1001-abc123de")
    assert okta.call_count == 1

    lumos = FakeLumosConnector()
    res_lumos = lumos.write(sample_employee, idempotency_key)
    assert res_lumos.success is True
    assert res_lumos.system_ref_id.startswith("LUMOS-emp_1001-abc123de")
    assert lumos.call_count == 1

    expo = FakeExpoITConnector()
    res_expo = expo.write(sample_employee, idempotency_key)
    assert res_expo.success is True
    assert res_expo.system_ref_id.startswith("EXPOIT-emp_1001-abc123de")
    assert expo.call_count == 1

    trk = FakeTrackerConnector()
    res_trk = trk.write(sample_employee, idempotency_key)
    assert res_trk.success is True
    assert res_trk.system_ref_id.startswith("TRK-emp_1001-abc123de")
    assert trk.call_count == 1


def test_expoit_simulated_failure(sample_employee):
    expo = FakeExpoITConnector()
    sample_employee.employee_id = "emp_offcycle_test"
    with pytest.raises(RuntimeError, match="Simulated expoIT transient"):
        expo.write(sample_employee, "key_test_123")
    assert expo.call_count == 1
