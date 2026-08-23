import json
from pathlib import Path

from src.models import AuditLogEntry


class AuditLog:
    def __init__(self, log_path: Path = Path("data/audit_log.jsonl")) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: AuditLogEntry) -> None:
        """Append a single AuditLogEntry to the JSONL log file."""
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def read_all(self) -> list[AuditLogEntry]:
        """Read all AuditLogEntries from the JSONL log file."""
        if not self.log_path.exists():
            return []
        entries: list[AuditLogEntry] = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(AuditLogEntry.model_validate_json(line))
                    except Exception:
                        continue
        return entries

    def get_entries_by_employee(self, employee_id: str) -> list[AuditLogEntry]:
        """Filter audit log entries by employee ID."""
        return [e for e in self.read_all() if e.employee_id == employee_id]

    def get_entries_by_event(self, event_id: str) -> list[AuditLogEntry]:
        """Filter audit log entries by event ID."""
        return [e for e in self.read_all() if e.event_id == event_id]

    def get_entries_by_action(self, action: str) -> list[AuditLogEntry]:
        """Filter audit log entries by action name."""
        return [e for e in self.read_all() if e.action == action]

    def clear(self) -> None:
        """Clear all entries in the audit log."""
        if self.log_path.exists():
            self.log_path.unlink()
