import json
from pathlib import Path
from typing import Any

from src.models import Employee, LedgerEntry


class StateStore:
    def __init__(self, data_dir: Path = Path("data")) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.employees_path = self.data_dir / "employees.json"
        self.ledger_path = self.data_dir / "ledger.json"

    def _read_json(self, file_path: Path) -> dict[str, Any]:
        if not file_path.exists():
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_json(self, file_path: Path, data: dict[str, Any]) -> None:
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        temp_path.replace(file_path)

    def get_employee(self, employee_id: str) -> Employee | None:
        records = self._read_json(self.employees_path)
        raw = records.get(employee_id)
        if raw is None:
            return None
        return Employee.model_validate(raw)

    def save_employee(self, employee: Employee) -> None:
        records = self._read_json(self.employees_path)
        records[employee.employee_id] = employee.model_dump(mode="json")
        self._write_json(self.employees_path, records)

    def all_employees(self) -> list[Employee]:
        records = self._read_json(self.employees_path)
        return [Employee.model_validate(val) for val in records.values()]

    def get_ledger_entry(self, idempotency_key: str) -> LedgerEntry | None:
        records = self._read_json(self.ledger_path)
        raw = records.get(idempotency_key)
        if raw is None:
            return None
        return LedgerEntry.model_validate(raw)

    def save_ledger_entry(self, entry: LedgerEntry) -> None:
        records = self._read_json(self.ledger_path)
        records[entry.idempotency_key] = entry.model_dump(mode="json")
        self._write_json(self.ledger_path, records)

    def all_ledger_entries(self) -> list[LedgerEntry]:
        """Returns all entries recorded in the ledger."""
        records = self._read_json(self.ledger_path)
        return [LedgerEntry.model_validate(val) for val in records.values()]

    def needs_attention(self) -> list[LedgerEntry]:
        """Entries with status FAILED — the monitoring stretch goal reads this."""
        records = self._read_json(self.ledger_path)
        failed_entries: list[LedgerEntry] = []
        for raw in records.values():
            entry = LedgerEntry.model_validate(raw)
            if entry.status == "FAILED":
                failed_entries.append(entry)
        return failed_entries

    def clear(self) -> None:
        """Clear all employees and ledger entries."""
        if self.employees_path.exists():
            self.employees_path.unlink()
        if self.ledger_path.exists():
            self.ledger_path.unlink()
