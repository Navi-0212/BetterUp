import json
import os
from pathlib import Path
from typing import Any, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.audit_log import AuditLog
from src.gemini_handler import GeminiHandler
from src.connectors import (
    FakeExpoITConnector,
    FakeLumosConnector,
    FakeOktaConnector,
    FakeTrackerConnector,
    FakeWorkdayConnector,
)
from src.models import ChangeEvent, Employee, Address
from src.state_store import StateStore
from src.sync_engine import process_event, normalize_event

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

store = StateStore(data_dir=DATA_DIR)
audit_log = AuditLog(log_path=DATA_DIR / "audit_log.jsonl")

app = FastAPI(title="BetterUp Sync Engine API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_connectors():
    return {
        "workday": FakeWorkdayConnector(),
        "okta": FakeOktaConnector(),
        "lumos": FakeLumosConnector(),
        "expoit": FakeExpoITConnector(),
        "tracker": FakeTrackerConnector(),
    }


class ProcessEventRequest(BaseModel):
    event_data: dict[str, Any]
    dry_run: bool = False


class ResolveConflictRequest(BaseModel):
    record_a: dict[str, Any]
    record_b: dict[str, Any]
    context: str = "Interactive Gemini conflict resolution test"


@app.get("/api/overview")
def get_overview():
    employees = store.all_employees()
    ledger_entries = store.all_ledger_entries()
    needs_attn = store.needs_attention()
    audit_entries = audit_log.read_all()

    systems_status = {
        "workday": {"name": "Workday HRIS", "status": "ONLINE", "type": "HRIS System of Record"},
        "okta": {"name": "Okta Identity", "status": "ONLINE", "type": "Identity & SSO"},
        "lumos": {"name": "Lumos Governance", "status": "ONLINE", "type": "Access Governance"},
        "expoit": {"name": "expoIT Hardware", "status": "ONLINE", "type": "Hardware Logistics"},
        "tracker": {"name": "Cohort Tracker", "status": "ONLINE", "type": "Onboarding Tracker"},
    }

    return {
        "status": "HEALTHY",
        "employee_count": len(employees),
        "ledger_entry_count": len(ledger_entries),
        "needs_attention_count": len(needs_attn),
        "audit_log_count": len(audit_entries),
        "systems": systems_status,
        "llm_model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        "has_api_key": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
    }


@app.get("/api/employees")
def get_employees():
    employees = store.all_employees()
    return [emp.model_dump(mode="json") for emp in employees]


@app.get("/api/employees/{employee_id}")
def get_employee(employee_id: str):
    emp = store.get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee {employee_id} not found")
    return emp.model_dump(mode="json")


@app.get("/api/ledger")
def get_ledger():
    entries = store.all_ledger_entries()
    needs_attn = store.needs_attention()
    return {
        "entries": [e.model_dump(mode="json") for e in entries],
        "needs_attention": [e.model_dump(mode="json") for e in needs_attn],
    }


@app.get("/api/audit-logs")
def get_audit_logs(
    action: Optional[str] = None,
    employee_id: Optional[str] = None,
    limit: int = 100,
):
    entries = audit_log.read_all()
    if action:
        entries = [e for e in entries if e.action == action]
    if employee_id:
        entries = [e for e in entries if e.employee_id == employee_id]
    # Return newest first
    reversed_entries = list(reversed(entries))[:limit]
    return [e.model_dump(mode="json") for e in reversed_entries]


@app.get("/api/sample-events")
def get_sample_events():
    events_dir = Path("sample_events")
    sample_files = [
        "name_change.json",
        "address_change.json",
        "start_date_change.json",
        "offcycle_hire.json",
        "ambiguous_name_conflict.json",
    ]
    results = []
    for filename in sample_files:
        file_path = events_dir / filename
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                results.append({
                    "filename": filename,
                    "name": filename.replace(".json", "").replace("_", " ").title(),
                    "event_id": content.get("event_id"),
                    "event_type": content.get("event_type"),
                    "employee_id": content.get("employee_id"),
                    "content": content,
                })
            except Exception:
                continue
    return results


@app.post("/api/process-event")
def api_process_event(req: ProcessEventRequest):
    try:
        event = ChangeEvent.model_validate(req.event_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid ChangeEvent payload: {e}")

    handler = GeminiHandler()
    connectors = get_connectors()

    result = process_event(
        event=event,
        store=store,
        connectors=connectors,
        claude_handler=handler,
        dry_run=req.dry_run,
        audit_log=audit_log,
    )

    return {
        "result": result.model_dump(mode="json"),
        "dry_run": req.dry_run,
        "employee": store.get_employee(event.employee_id).model_dump(mode="json") if store.get_employee(event.employee_id) and not req.dry_run else None,
    }


@app.post("/api/resolve-conflict")
def api_resolve_conflict(req: ResolveConflictRequest):
    try:
        emp_a = Employee.model_validate(req.record_a)
        emp_b = Employee.model_validate(req.record_b)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid employee record: {e}")

    handler = GeminiHandler()
    res = handler.resolve_conflict(emp_a, emp_b, req.context)
    return res.model_dump()


@app.post("/api/seed-demo-data")
def seed_demo_data():
    events_dir = Path("sample_events")
    # 1. Seed offcycle_hire.json (emp_2001)
    offcycle_file = events_dir / "offcycle_hire.json"
    if offcycle_file.exists():
        with open(offcycle_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        event = ChangeEvent.model_validate(data)
        emp = normalize_event(event, store)
        store.save_employee(emp)

    # 2. Seed initial candidate emp_1001 (Naveen Kumar)
    initial_emp_1001 = Employee(
        employee_id="emp_1001",
        legal_first_name="Naveen",
        legal_last_name="Kumar",
        preferred_name=None,
        personal_email="naveen.demo@example.com",
        work_email=None,
        start_date="2026-09-15",
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
        status="ACTIVE",
        last_updated_at="2026-08-15T09:00:00Z",
        last_updated_by_event_id="evt-seed-1001",
    )
    store.save_employee(initial_emp_1001)

    return {
        "message": "Demo data successfully seeded (emp_1001: Naveen Kumar, emp_2001: Sanjay Iyer)",
        "employees": [e.model_dump(mode="json") for e in store.all_employees()],
    }


@app.post("/api/reset-data")
def reset_data():
    audit_log.clear()
    store.clear()
    return {"message": "All state store and audit log data cleared"}


# Mount static frontend files
FRONTEND_DIR = Path("frontend")
FRONTEND_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse({"message": "BetterUp Sync Engine API running. Frontend loading..."})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
