from abc import ABC, abstractmethod
from pydantic import BaseModel, ConfigDict

from src.models import Employee


class ConnectorResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: bool
    system_ref_id: str | None = None
    error_message: str | None = None


class Connector(ABC):
    @abstractmethod
    def write(self, employee: Employee, idempotency_key: str) -> ConnectorResult:
        """Write employee data to the downstream system idempotently."""
        pass
