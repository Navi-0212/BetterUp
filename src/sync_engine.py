from datetime import datetime, timezone
import hashlib
import time
from typing import TYPE_CHECKING, Any, Callable

from src.audit_log import AuditLog
from src.connectors.base import Connector
from src.models import (
    Address,
    AuditLogEntry,
    ChangeEvent,
    Employee,
    LedgerEntry,
    ProcessResult,
)
from src.state_store import StateStore
from src.validators import is_near_duplicate, validate_fields

if TYPE_CHECKING:
    from src.claude_handler import ClaudeHandler


SYSTEMS_FOR_FIELD: dict[str, list[str]] = {
    "legal_first_name": ["WORKDAY", "OKTA", "LUMOS", "TRACKER"],
    "legal_last_name": ["WORKDAY", "OKTA", "LUMOS", "TRACKER"],
    "preferred_name": ["WORKDAY", "OKTA", "LUMOS", "TRACKER"],
    "personal_email": ["WORKDAY", "OKTA", "TRACKER"],
    "address": ["WORKDAY", "EXPOIT", "TRACKER"],
    "start_date": ["WORKDAY", "OKTA", "LUMOS", "EXPOIT", "TRACKER"],
    "position_title": ["WORKDAY", "LUMOS", "TRACKER"],
    "department": ["WORKDAY", "LUMOS", "TRACKER"],
    "manager_id": ["WORKDAY", "TRACKER"],
}

ALL_SYSTEMS: list[str] = ["WORKDAY", "OKTA", "LUMOS", "EXPOIT", "TRACKER"]


def generate_idempotency_key(
    employee_id: str, field_name: str, new_value: Any, target_system: str
) -> str:
    """Generate deterministic SHA-256 idempotency key."""
    raw = f"{employee_id}:{field_name}:{new_value}:{target_system}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_event(event: ChangeEvent, store: StateStore) -> Employee:
    """FIELD_CHANGE: merge changed_fields onto the existing stored Employee.
    OFFCYCLE_HIRE_DETECTED: build a new Employee entirely from raw_payload,
    tagged source_system=WORKDAY_OFFCYCLE."""
    if event.event_type == "OFFCYCLE_HIRE_DETECTED":
        payload = event.raw_payload
        address_raw = payload.get("address", {})
        address = Address(
            line1=address_raw.get("line1", ""),
            line2=address_raw.get("line2"),
            city=address_raw.get("city", ""),
            state=address_raw.get("state", ""),
            postal_code=address_raw.get("postal_code", ""),
            country=address_raw.get("country", ""),
        )
        return Employee(
            employee_id=payload.get("employee_id", event.employee_id),
            legal_first_name=payload.get("legal_first_name", ""),
            legal_last_name=payload.get("legal_last_name", ""),
            preferred_name=payload.get("preferred_name"),
            personal_email=payload.get("personal_email", ""),
            work_email=payload.get("work_email"),
            start_date=payload["start_date"],
            address=address,
            position_title=payload.get("position_title", ""),
            department=payload.get("department", ""),
            manager_id=payload.get("manager_id"),
            source_system="WORKDAY_OFFCYCLE",
            last_updated_at=event.received_at,
            last_updated_by_event_id=event.event_id,
        )

    # FIELD_CHANGE
    existing = store.get_employee(event.employee_id)
    if existing is not None:
        emp_dict = existing.model_dump()
    else:
        # Fallback to raw_payload if store doesn't have it yet
        payload = event.raw_payload
        address_raw = payload.get("address", {})
        emp_dict = {
            "employee_id": payload.get("employee_id", event.employee_id),
            "legal_first_name": payload.get("legal_first_name", ""),
            "legal_last_name": payload.get("legal_last_name", ""),
            "preferred_name": payload.get("preferred_name"),
            "personal_email": payload.get("personal_email", ""),
            "work_email": payload.get("work_email"),
            "start_date": payload.get("start_date"),
            "address": {
                "line1": address_raw.get("line1", ""),
                "line2": address_raw.get("line2"),
                "city": address_raw.get("city", ""),
                "state": address_raw.get("state", ""),
                "postal_code": address_raw.get("postal_code", ""),
                "country": address_raw.get("country", ""),
            },
            "position_title": payload.get("position_title", ""),
            "department": payload.get("department", ""),
            "manager_id": payload.get("manager_id"),
            "source_system": "ASHBY",
            "last_updated_at": event.received_at,
            "last_updated_by_event_id": event.event_id,
        }

    # Apply changed_fields onto emp_dict
    for field_name, delta in event.changed_fields.items():
        if field_name == "address" and isinstance(delta.new_value, dict):
            emp_dict["address"] = delta.new_value
        else:
            emp_dict[field_name] = delta.new_value

    emp_dict["last_updated_at"] = event.received_at
    emp_dict["last_updated_by_event_id"] = event.event_id
    return Employee.model_validate(emp_dict)


def write_with_retry(
    connector: Connector,
    employee: Employee,
    idempotency_key: str,
    store: StateStore,
    max_attempts: int = 3,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> LedgerEntry:
    """See Section 9 for backoff formula. sleep_fn is injectable so tests
    can pass a no-op and run instantly instead of waiting on real backoff."""
    existing = store.get_ledger_entry(idempotency_key)
    if existing is not None and existing.status == "ACKED":
        return existing

    target_system = "WORKDAY"
    conn_name = connector.__class__.__name__.upper()
    for sys in ALL_SYSTEMS:
        if sys in conn_name:
            target_system = sys
            break

    entry = LedgerEntry(
        employee_id=employee.employee_id,
        target_system=target_system,  # type: ignore
        idempotency_key=idempotency_key,
        status="PENDING",
        attempts=0,
        last_attempt_at=None,
        error_message=None,
        system_ref_id=None,
    )

    for attempt in range(1, max_attempts + 1):
        entry.attempts = attempt
        entry.last_attempt_at = datetime.now(timezone.utc)
        try:
            res = connector.write(employee, idempotency_key)
            if res.success:
                entry.status = "ACKED"
                entry.system_ref_id = res.system_ref_id
                entry.error_message = None
                store.save_ledger_entry(entry)
                return entry
            else:
                entry.error_message = res.error_message or "Connector returned failure"
        except Exception as e:
            entry.error_message = str(e)

        if attempt < max_attempts:
            entry.status = "RETRYING"
            store.save_ledger_entry(entry)
            delay = 0.1 * (2**attempt)
            sleep_fn(delay)
        else:
            entry.status = "FAILED"
            store.save_ledger_entry(entry)

    return entry


def process_event(
    event: ChangeEvent,
    store: StateStore,
    connectors: dict[str, Connector],
    claude_handler: "ClaudeHandler | None" = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    dry_run: bool = False,
    audit_log: AuditLog | None = None,
) -> ProcessResult:
    """Top-level orchestration matching the Section 6 diagram. Returns a
    ProcessResult summarizing: fields propagated, fields rejected, systems
    written, systems failed, and any conflict resolution outcome."""
    if audit_log is None:
        audit_log = AuditLog(store.data_dir / "audit_log.jsonl")

    result = ProcessResult(
        event_id=event.event_id,
        employee_id=event.employee_id,
    )

    # 1. Normalize
    candidate = normalize_event(event, store)

    # 2. Filter no-op deltas
    active_changed_fields: set[str] = set()
    if event.event_type == "FIELD_CHANGE":
        for field_name, delta in event.changed_fields.items():
            if delta.old_value == delta.new_value:
                if not dry_run:
                    audit_log.append(
                        AuditLogEntry(
                            event_id=event.event_id,
                            employee_id=candidate.employee_id,
                            target_system=None,
                            action="NO_OP_SKIPPED",
                            before_state={"field": field_name, "value": delta.old_value},
                            after_state={"field": field_name, "value": delta.new_value},
                            triggered_by="sync_engine.process_event",
                            timestamp=datetime.now(timezone.utc),
                        )
                    )
                continue
            active_changed_fields.add(field_name)
    else:
        active_changed_fields = {
            "legal_first_name",
            "legal_last_name",
            "address",
            "start_date",
            "personal_email",
            "position_title",
            "department",
        }

    # 3. Near duplicate check (Section 10 pre-filter)
    near_dupe: Employee | None = None
    for existing in store.all_employees():
        if is_near_duplicate(candidate, existing):
            near_dupe = existing
            break

    if near_dupe is not None:
        if claude_handler is not None:
            context = f"Incoming hire from {event.source_system} matches existing employee {near_dupe.employee_id}"
            resolution = claude_handler.resolve_conflict(near_dupe, candidate, context)
            result.conflict_resolution = resolution

            if resolution.decision == "needs_human_review" or resolution.confidence < 0.7:
                result.needs_human_review = True
                if not dry_run:
                    audit_log.append(
                        AuditLogEntry(
                            event_id=event.event_id,
                            employee_id=candidate.employee_id,
                            target_system=None,
                            action="NEEDS_HUMAN_REVIEW",
                            before_state=near_dupe.model_dump(mode="json"),
                            after_state=candidate.model_dump(mode="json"),
                            triggered_by="claude_handler.resolve_conflict",
                            timestamp=datetime.now(timezone.utc),
                        )
                    )
                return result
            else:
                if not dry_run:
                    audit_log.append(
                        AuditLogEntry(
                            event_id=event.event_id,
                            employee_id=candidate.employee_id,
                            target_system=None,
                            action="CLAUDE_CONFLICT_RESOLVED",
                            before_state=near_dupe.model_dump(mode="json"),
                            after_state={
                                "decision": resolution.decision,
                                "confidence": resolution.confidence,
                                "reasoning": resolution.reasoning,
                            },
                            triggered_by="claude_handler.resolve_conflict",
                            timestamp=datetime.now(timezone.utc),
                        )
                    )
        else:
            result.needs_human_review = True
            if not dry_run:
                audit_log.append(
                    AuditLogEntry(
                        event_id=event.event_id,
                        employee_id=candidate.employee_id,
                        target_system=None,
                        action="NEEDS_HUMAN_REVIEW",
                        before_state=near_dupe.model_dump(mode="json"),
                        after_state=candidate.model_dump(mode="json"),
                        triggered_by="sync_engine.process_event",
                        timestamp=datetime.now(timezone.utc),
                    )
                )
            return result

    # 4. Inline Field Validation
    valid_fields, rejections = validate_fields(candidate, active_changed_fields)
    result.fields_propagated = sorted(list(valid_fields))
    result.fields_rejected = sorted(
        [r.after_state["rejected_field"] for r in rejections if r.after_state]
    )

    if not dry_run:
        for r in rejections:
            audit_log.append(r)

    if not valid_fields:
        return result

    # 5. Persist candidate if not dry run
    if not dry_run:
        store.save_employee(candidate)

    # 6. Target systems fan-out
    target_systems_to_write: set[str] = set()
    if event.event_type == "OFFCYCLE_HIRE_DETECTED":
        target_systems_to_write = set(ALL_SYSTEMS)
    else:
        for f in valid_fields:
            for sys in SYSTEMS_FOR_FIELD.get(f, []):
                target_systems_to_write.add(sys)

    for target_sys in sorted(list(target_systems_to_write)):
        connector = connectors.get(target_sys.lower()) or connectors.get(target_sys)
        if not connector:
            continue

        delta_val = "all"
        if event.event_type == "FIELD_CHANGE" and len(valid_fields) == 1:
            f = next(iter(valid_fields))
            delta = event.changed_fields.get(f)
            delta_val = str(delta.new_value) if delta else "delta"
        else:
            delta_val = f"{candidate.last_updated_by_event_id}"

        key = generate_idempotency_key(
            employee_id=candidate.employee_id,
            field_name=",".join(sorted(valid_fields)),
            new_value=delta_val,
            target_system=target_sys,
        )

        if dry_run:
            result.systems_written.append(target_sys)
            continue

        already_acked = (
            store.get_ledger_entry(key) is not None
            and store.get_ledger_entry(key).status == "ACKED"  # type: ignore
        )

        entry = write_with_retry(
            connector=connector,
            employee=candidate,
            idempotency_key=key,
            store=store,
            sleep_fn=sleep_fn,
        )

        if entry.status == "ACKED":
            result.systems_written.append(target_sys)
            if not dry_run:
                if already_acked:
                    audit_log.append(
                        AuditLogEntry(
                            event_id=event.event_id,
                            employee_id=candidate.employee_id,
                            target_system=target_sys,
                            action="NO_OP_SKIPPED",
                            before_state=None,
                            after_state={"idempotency_key": key, "status": "ACKED"},
                            triggered_by="sync_engine.write_with_retry",
                            timestamp=datetime.now(timezone.utc),
                        )
                    )
                else:
                    audit_log.append(
                        AuditLogEntry(
                            event_id=event.event_id,
                            employee_id=candidate.employee_id,
                            target_system=target_sys,
                            action="FIELD_CHANGE_PROPAGATED",
                            before_state=None,
                            after_state={
                                "system_ref_id": entry.system_ref_id,
                                "fields": list(valid_fields),
                            },
                            triggered_by="sync_engine.write_with_retry",
                            timestamp=datetime.now(timezone.utc),
                        )
                    )
        elif entry.status == "FAILED":
            result.systems_failed.append(target_sys)

    return result
