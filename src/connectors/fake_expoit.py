from src.connectors.base import Connector, ConnectorResult
from src.models import Employee


class FakeExpoITConnector(Connector):
    def __init__(self) -> None:
        self.call_count = 0

    def write(self, employee: Employee, idempotency_key: str) -> ConnectorResult:
        self.call_count += 1
        if employee.employee_id == "emp_offcycle_test":
            raise RuntimeError(f"Simulated expoIT transient hardware shipping error for {employee.employee_id}")
        ref_id = f"EXPOIT-{employee.employee_id}-{idempotency_key[:8]}"
        return ConnectorResult(success=True, system_ref_id=ref_id)
