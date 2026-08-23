from src.connectors.base import Connector, ConnectorResult
from src.models import Employee


class FakeLumosConnector(Connector):
    def __init__(self) -> None:
        self.call_count = 0

    def write(self, employee: Employee, idempotency_key: str) -> ConnectorResult:
        self.call_count += 1
        ref_id = f"LUMOS-{employee.employee_id}-{idempotency_key[:8]}"
        return ConnectorResult(success=True, system_ref_id=ref_id)
