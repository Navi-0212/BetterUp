from datetime import datetime, timezone
from difflib import SequenceMatcher
from src.models import AuditLogEntry, Employee


def is_near_duplicate(candidate: Employee, existing: Employee) -> bool:
    """Deterministic pre-filter — see Section 10. Must NOT call Claude."""
    if candidate.employee_id == existing.employee_id:
        return False  # same record, not a conflict
    if candidate.start_date != existing.start_date:
        return False  # different start dates -> not the same hire
    name_a = f"{candidate.legal_first_name} {candidate.legal_last_name}".lower().strip()
    name_b = f"{existing.legal_first_name} {existing.legal_last_name}".lower().strip()
    if name_a == name_b:
        return False  # exact match is a normal update, not an ambiguous conflict
    ratio = SequenceMatcher(None, name_a, name_b).ratio()
    return ratio >= 0.75


def validate_fields(
    employee: Employee, changed_field_names: set[str]
) -> tuple[set[str], list[AuditLogEntry]]:
    """Returns (valid_field_names, rejection_audit_entries). A rejected
    field is removed from the fan-out set; the rest still propagate."""
    valid_fields: set[str] = set()
    rejections: list[AuditLogEntry] = []

    for field_name in changed_field_names:
        is_valid = True
        reason: str | None = None

        if field_name == "legal_first_name":
            val = employee.legal_first_name
            if not val or not val.strip():
                is_valid = False
                reason = "legal_first_name cannot be empty"
            elif any(char.isdigit() for char in val):
                is_valid = False
                reason = "legal_first_name cannot contain digits"

        elif field_name == "legal_last_name":
            val = employee.legal_last_name
            if not val or not val.strip():
                is_valid = False
                reason = "legal_last_name cannot be empty"
            elif any(char.isdigit() for char in val):
                is_valid = False
                reason = "legal_last_name cannot contain digits"

        elif field_name == "address":
            addr = employee.address
            if not (
                addr.line1 and addr.line1.strip()
                and addr.city and addr.city.strip()
                and addr.state and addr.state.strip()
                and addr.postal_code and addr.postal_code.strip()
                and addr.country and addr.country.strip()
            ):
                is_valid = False
                reason = "address must have non-empty line1, city, state, postal_code, and country"

        elif field_name == "start_date":
            # Compare calendar date of start_date against employee.last_updated_at calendar date
            ref_date = employee.last_updated_at.date()
            if employee.start_date < ref_date:
                is_valid = False
                reason = f"start_date ({employee.start_date}) cannot be before event timestamp ({ref_date})"

        if is_valid:
            valid_fields.add(field_name)
        else:
            entry = AuditLogEntry(
                event_id=employee.last_updated_by_event_id,
                employee_id=employee.employee_id,
                target_system=None,
                action="VALIDATION_REJECTED",
                before_state=None,
                after_state={"rejected_field": field_name, "reason": reason},
                triggered_by="validators.validate_fields",
                timestamp=datetime.now(timezone.utc),
            )
            rejections.append(entry)

    return valid_fields, rejections
