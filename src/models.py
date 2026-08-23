from datetime import date, datetime
from typing import Any, Literal
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ConfigDict, Field


class Address(BaseModel):
    model_config = ConfigDict(extra="ignore")

    line1: str
    line2: str | None = None
    city: str
    state: str
    postal_code: str
    country: str


class Employee(BaseModel):
    model_config = ConfigDict(extra="ignore")

    employee_id: str
    legal_first_name: str
    legal_last_name: str
    preferred_name: str | None = None
    personal_email: str
    work_email: str | None = None
    start_date: date
    address: Address
    position_title: str
    department: str
    manager_id: str | None = None
    source_system: Literal["ASHBY", "WORKDAY_OFFCYCLE"]
    last_updated_at: datetime
    last_updated_by_event_id: str


class FieldDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    old_value: Any = None
    new_value: Any = None


class ChangeEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str
    event_type: Literal["FIELD_CHANGE", "OFFCYCLE_HIRE_DETECTED"]
    employee_id: str
    source_system: Literal["ASHBY", "WORKDAY"]
    changed_fields: dict[str, FieldDelta] = Field(default_factory=dict)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    employee_id: str
    target_system: Literal["WORKDAY", "OKTA", "LUMOS", "EXPOIT", "TRACKER"]
    idempotency_key: str
    status: Literal["PENDING", "SENT", "ACKED", "FAILED", "RETRYING"]
    attempts: int = 0
    last_attempt_at: datetime | None = None
    error_message: str | None = None
    system_ref_id: str | None = None


class AuditLogEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str
    employee_id: str
    target_system: str | None = None
    action: str  # "FIELD_CHANGE_PROPAGATED" | "VALIDATION_REJECTED" | "NO_OP_SKIPPED" | "CLAUDE_CONFLICT_RESOLVED" | "NEEDS_HUMAN_REVIEW"
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    triggered_by: str
    timestamp: datetime


class ConflictResolution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: Literal["same_person", "different_person", "needs_human_review"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class ProcessResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str
    employee_id: str
    fields_propagated: list[str] = Field(default_factory=list)
    fields_rejected: list[str] = Field(default_factory=list)
    systems_written: list[str] = Field(default_factory=list)
    systems_failed: list[str] = Field(default_factory=list)
    conflict_resolution: ConflictResolution | None = None
    needs_human_review: bool = False
