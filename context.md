# BetterUp AI Automation Engineer — Take-Home Build Spec & Context (v2)

> **Slice**: Change Propagation (with validation nested inline, monitoring as stretch)  
> **Source**: Based on `Problemstatement.txt` (v2)

---

## 0. How to Use & Global Code Rules

- **Execution Context**: Build spec for an IDE AI agent (Cursor / Antigravity). Every section is a hard requirement unless marked `(stretch)` or `(optional)`.
- **Phase Order**: Build strictly following Section 18.
- **Scope & Restraint**: Do not add infrastructure, libraries, or services beyond Section 4.
- **Python Version**: Python 3.11+, standard library first.
- **Timestamps**: All datetimes are timezone-aware UTC (`datetime.now(timezone.utc)` — never deprecated `datetime.utcnow()`). All JSON timestamps are ISO-8601 with a `Z` suffix (e.g., `"2026-08-20T10:15:00Z"`).
- **Idempotency & Retry**: Every downstream write goes through the idempotency + retry path in Section 9. No direct connector calls from anywhere else.
- **Data Integrity**: Every function touching employee data takes/returns the `Employee` model in Section 5. No ad-hoc dicts crossing module boundaries.
- **Function Signatures**: Use exact function signatures specified in Section 8.
- **Simplicity**: Explicit, readable code over unnecessary abstractions (no generic connector factories or complex plugin systems for a 2-hour interview prototype).

---

## 1. Business Context

BetterUp's onboarding coordination spans five systems with no single source of truth:

| System | Role | Authority / Lifecycle |
|---|---|---|
| **Ashby** | ATS | Source of truth **BEFORE** the hire (offer, name, start date, address). |
| **Workday** | HRIS | System of record **AFTER** the hire. Can receive off-cycle hires created directly, bypassing Ashby. |
| **Okta** | Identity / SSO | Owns login + auth. |
| **Lumos** | Access Governance | Sits on top of Okta; governs app access driven by HRIS lifecycle events (joiner/mover/leaver). |
| **expoIT** | IT Hardware Vendor | Ships laptop; requires correct shipping address. |
| **Cohort Tracker** | Checklist / Status | Internal tracking system read by humans. |

### Three Failure Modes:
1. **Change Propagation**: A name/start-date/address change after offer or an off-cycle hire outside Ashby never ripples downstream.
2. **Bad Data Cascades**: Wrong name/address in Ashby flows unchecked into Workday, Okta email, and the shipping label.
3. **Nobody's Watching the Gates**: Hardware form, background check, Okta provisioning have ~7-day deadlines nobody tracks.

---

## 2. Chosen Slice — And Why

**Chosen Slice**: **CHANGE PROPAGATION**, with validation nested inline (validated at the moment a field is transformed for a downstream write, not as a separate system), and a thin exception-monitoring read endpoint as a stretch goal over the same state store.

### Rationale (Defend in Debrief):
- **Core Engineering Depth**: Only slice forcing a canonical data model, a diffing mechanism, and per-system idempotent writes.
- **Inline Validation**: Nearly free once propagation exists (validate during transform, before writing).
- **Exception Monitoring**: Simple read-only view over state already maintained by propagation.
- **Targeted LLM Usage**: LLM has a legitimate job in resolving genuinely ambiguous near-duplicate conflicts (Section 10), rather than acting as a redundant system router.

---

## 3. Off-Cycle / No-Single-Source-of-Truth Problem

- **Ashby**: Authoritative pre-hire.
- **Workday**: Authoritative post-hire.
- **Off-Cycle Hires**: Can appear directly in Workday without an Ashby record.
- **Key Design Decision**: When no Ashby record exists for an `employee_id`, Workday is authoritative for that record, tagged `source_system=WORKDAY_OFFCYCLE`. **Do not reconstruct a fictitious Ashby record.**

---

## 4. Constraints

- **Mocked Downstream Systems**: No real credentials or API calls to Ashby/Workday/Okta/Lumos/expoIT/Cohort Tracker (all mocked in-memory + local JSON-backed).
- **Single Real External Call**: Anthropic API for Section 10 conflict resolution, and **ONLY** in integration test runs (`pytest -m integration`). Never in default unit tests.
- **Environment Variables**:
  - `ANTHROPIC_API_KEY` (never hardcoded)
  - `CLAUDE_MODEL` (defaults to `claude-sonnet-5` if unset)
- **Allowed Dependencies**:
  - `pydantic>=2.0,<3.0`
  - `anthropic>=0.40.0`
  - `pytest>=8.0`
  - `python-dotenv>=1.0` (optional, for `.env` loading in `main.py`)
  - `mcp` (stretch goal only)
- **Forbidden Infrastructure**: No message queues (Kafka/SQS/RabbitMQ), no DB servers (Postgres/Mongo), no Docker/Terraform/SaaS tools. Local JSON files for persistence.

---

## 5. Canonical Data Model (Pydantic v2)

### `Employee`
```python
employee_id: str
legal_first_name: str
legal_last_name: str
preferred_name: str | None
personal_email: str
work_email: str | None            # assigned by Okta, absent pre-hire
start_date: date
address: Address
position_title: str
department: str
manager_id: str | None
source_system: Literal["ASHBY", "WORKDAY_OFFCYCLE"]
last_updated_at: datetime          # tz-aware UTC
last_updated_by_event_id: str
```

### `Address`
```python
line1: str
line2: str | None
city: str
state: str
postal_code: str
country: str
```

### `FieldDelta`
```python
old_value: Any
new_value: Any
```

### `ChangeEvent`
```python
event_id: str                     # uuid4
event_type: Literal["FIELD_CHANGE", "OFFCYCLE_HIRE_DETECTED"]
employee_id: str
source_system: Literal["ASHBY", "WORKDAY"]
changed_fields: dict[str, FieldDelta]   # {} for OFFCYCLE_HIRE_DETECTED
raw_payload: dict
received_at: datetime             # tz-aware UTC
```

### `LedgerEntry`
```python
employee_id: str
target_system: Literal["WORKDAY", "OKTA", "LUMOS", "EXPOIT", "TRACKER"]
idempotency_key: str
status: Literal["PENDING", "SENT", "ACKED", "FAILED", "RETRYING"]
attempts: int
last_attempt_at: datetime | None
error_message: str | None
system_ref_id: str | None
```

### `AuditLogEntry`
```python
event_id: str
employee_id: str
target_system: str | None
action: str   # "FIELD_CHANGE_PROPAGATED" | "VALIDATION_REJECTED" |
              # "NO_OP_SKIPPED" | "CLAUDE_CONFLICT_RESOLVED" |
              # "NEEDS_HUMAN_REVIEW"
before_state: dict | None
after_state: dict | None
triggered_by: str
timestamp: datetime               # tz-aware UTC
```

### `ConflictResolution`
```python
decision: Literal["same_person", "different_person", "needs_human_review"]
confidence: float                 # 0.0-1.0
reasoning: str
```

> **No-Op Rule**: If an incoming field delta has `old_value == new_value`, drop it before validation and log `NO_OP_SKIPPED`.

---

## 6. System Architecture & Flow

```
ChangeEvent (sample_events/*.json)
        |
        v
  normalize_event()   -> Candidate Employee
        |
        v
  find_near_duplicate()  -> Deterministic pre-filter against StateStore (Section 10)
        |
        v
  IF near-duplicate found -> claude_handler.resolve_conflict()
        -> log CLAUDE_CONFLICT_RESOLVED or NEEDS_HUMAN_REVIEW
        -> low confidence (< 0.7) or parse failure forces needs_human_review
        |
        v
  validate_fields()   -> Per-field validation; rejected field dropped (VALIDATION_REJECTED)
        |
        v
  Fan out valid changed fields to per-system transformers
        (transform_for_workday / okta / lumos / expoit / tracker)
        |
        v
  write_with_retry() per system, per field-group (isolated failure handling)
        |
        v
  audit_log.append()
```

---

## 7. Repository Structure

```
betterup-sync-engine/
├── problem_statement.txt
├── context.md
├── README.md
├── requirements.txt
├── .env.example
├── pytest.ini                    # registers the "integration" marker
├── systems_map.md                # Deliverable 1
├── build_note.md                 # Deliverable 3
├── src/
│   ├── __init__.py
│   ├── models.py
│   ├── state_store.py
│   ├── validators.py
│   ├── sync_engine.py
│   ├── claude_handler.py
│   ├── mcp_server.py             # stretch
│   ├── audit_log.py
│   ├── main.py
│   └── connectors/
│       ├── __init__.py
│       ├── base.py
│       ├── fake_workday.py
│       ├── fake_okta.py
│       ├── fake_lumos.py
│       ├── fake_expoit.py
│       └── fake_tracker.py
├── sample_events/
│   ├── name_change.json
│   ├── address_change.json
│   ├── start_date_change.json
│   ├── offcycle_hire.json
│   └── ambiguous_name_conflict.json
├── tests/
│   ├── conftest.py               # seeded store, fake clock, fake Anthropic client
│   ├── test_idempotency.py
│   ├── test_partial_failure.py
│   ├── test_offcycle_backfill.py
│   ├── test_validation.py
│   └── test_claude_conflict.py   # unit (mocked) + 1 integration test
└── data/                          # gitignored, runtime state
    ├── employees.json
    ├── ledger.json
    └── audit_log.jsonl            # append-only JSONL
```

---

## 8. Component Contracts & Exact Signatures

### `state_store.py`
```python
class StateStore:
    def __init__(self, data_dir: Path = Path("data")): ...
    def get_employee(self, employee_id: str) -> Employee | None: ...
    def save_employee(self, employee: Employee) -> None: ...
    def all_employees(self) -> list[Employee]: ...
    def get_ledger_entry(self, idempotency_key: str) -> LedgerEntry | None: ...
    def save_ledger_entry(self, entry: LedgerEntry) -> None: ...
    def needs_attention(self) -> list[LedgerEntry]: ...
```

### `validators.py`
```python
def validate_fields(
    employee: Employee, changed_field_names: set[str]
) -> tuple[set[str], list[AuditLogEntry]]:
    """Returns (valid_field_names, rejection_audit_entries). A rejected
    field is removed from the fan-out set; the rest still propagate."""

def is_near_duplicate(candidate: Employee, existing: Employee) -> bool:
    """Deterministic pre-filter — see Section 10. Must NOT call Claude."""
```

### `sync_engine.py`
```python
def normalize_event(event: ChangeEvent, store: StateStore) -> Employee:
    """FIELD_CHANGE: merge changed_fields onto existing stored Employee.
    OFFCYCLE_HIRE_DETECTED: build new Employee from raw_payload (source_system=WORKDAY_OFFCYCLE)."""

def process_event(
    event: ChangeEvent,
    store: StateStore,
    connectors: dict[str, Connector],
    claude_handler: "ClaudeHandler | None" = None,
) -> ProcessResult:
    """Top-level orchestration returning ProcessResult."""

def write_with_retry(
    connector: Connector,
    employee: Employee,
    idempotency_key: str,
    store: StateStore,
    max_attempts: int = 3,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> LedgerEntry:
    """Injectable sleep_fn for fast unit tests."""
```

### `claude_handler.py`
```python
class ClaudeHandler:
    def __init__(
        self,
        client: "anthropic.Anthropic | None" = None,
        model: str | None = None,
    ): ...

    def resolve_conflict(
        self, record_a: Employee, record_b: Employee, context: str
    ) -> ConflictResolution: ...
```

### `main.py`
```python
def main(argv: list[str] | None = None) -> int:
    """CLI parsing --event, --data-dir, --dry-run. Returns 0 on success, 1 on failures."""
```

---

## 9. Idempotency & Failure Handling

1. **Idempotency Key Formula**:
   $$\text{idempotency\_key} = \text{sha256}(f\text{"}\{\text{employee\_id}\}:\{\text{field\_name}\}:\{\text{new\_value}\}:\{\text{target\_system}\}\text{"})$$
2. **Pre-Write Check**: If ledger entry exists with status `ACKED`, skip write and log a no-op.
3. **Failure Isolation**: Connector writes are individually wrapped in `try/except`. Failure in one system does not block attempts to others.
4. **Retry Backoff Formula**:
   $$\text{delay} = 0.1 \times 2^{\text{attempt\_number}}\quad (\text{seconds}), \quad \text{max\_attempts}=3$$
   Tested using injectable `sleep_fn=lambda _: None`.
5. **Terminal State**: After 3 failed attempts, status becomes `FAILED` and surfaces via `needs_attention()`.

---

## 10. Validation Rules & Near-Duplicate Algorithm

### Field Validation (`validate_fields`)
- `legal_first_name` / `legal_last_name`: Non-empty after strip, no digits.
- `address`: All fields (`line1`, `city`, `state`, `postal_code`, `country`) non-empty.
- `start_date`: Not before `event.received_at` (calendar date comparison).

### Near-Duplicate Pre-Filter (`is_near_duplicate`)
```python
from difflib import SequenceMatcher

def is_near_duplicate(candidate: Employee, existing: Employee) -> bool:
    if candidate.employee_id == existing.employee_id:
        return False  # same record, not a conflict
    if candidate.start_date != existing.start_date:
        return False  # different start dates -> not the same hire
    name_a = f"{candidate.legal_first_name} {candidate.legal_last_name}".lower().strip()
    name_b = f"{existing.legal_first_name} {existing.legal_last_name}".lower().strip()
    if name_a == name_b:
        return False  # exact match is normal update, not ambiguous conflict
    ratio = SequenceMatcher(None, name_a, name_b).ratio()
    return ratio >= 0.75
```

---

## 11. Claude Integration Details

### Prompts
- **System Prompt**:
  > You are resolving a data conflict for an HR onboarding sync system. You will be given two employee records that a deterministic name-similarity check flagged as a possible match. Decide whether they are the same person, different people, or too ambiguous to auto-decide. Respond with ONLY a JSON object, no other text, matching exactly this shape:  
  > `{"decision": "same_person" | "different_person" | "needs_human_review", "confidence": <float 0.0-1.0>, "reasoning": "<one sentence>"}`

- **User Prompt**:
  ```
  Record A (existing, from {record_a.source_system}):
  {record_a as JSON}

  Record B (incoming, from {record_b.source_system}):
  {record_b as JSON}

  Context: {context}
  ```

### Safety Gating
- Parse response into `ConflictResolution`.
- If parsing fails **OR** `confidence < 0.7`, force override decision to `needs_human_review`.
- On `needs_human_review`: Log `NEEDS_HUMAN_REVIEW`, do not merge, do not propagate field, and surface in `needs_attention()`.

---

## 12. MCP Tool (Stretch Goal)

- **Entrypoint**: `python -m src.mcp_server`
- **Tool Name**: `resolve_identity_conflict`
- **Input**: `{record_a: object, record_b: object, context: string}`
- **Output**: `{decision: string, confidence: number, reasoning: string}`
- **Implementation**: Thin wrapper around `ClaudeHandler.resolve_conflict()`. Sync tool registered directly (handled by MCP SDK worker thread).

---

## 13. Auth Approach (Document in Build Note)

OAuth2 client-credentials flow per downstream system. Credentials from environment variables / secrets manager. Access tokens cached in-memory with expiry and refreshed transparently by `_get_token()` before connector writes.

---

## 14. Sample Events Summary

| File | Type | Employee ID | Description |
|---|---|---|---|
| `name_change.json` | `FIELD_CHANGE` | `emp_1001` | Last name change (`Kumar` -> `Kumaar`). |
| `address_change.json` | `FIELD_CHANGE` | `emp_1002` | Address update in Bengaluru. |
| `start_date_change.json` | `FIELD_CHANGE` | `emp_1003` | Start date shift (`2026-09-01` -> `2026-09-15`). |
| `offcycle_hire.json` | `OFFCYCLE_HIRE_DETECTED` | `emp_2001` | Workday direct hire ("Sanjay Iyer"). |
| `ambiguous_name_conflict.json` | `OFFCYCLE_HIRE_DETECTED` | `emp_2002` | Potential conflict hire ("Sanjai Iyer", same start date). |

---

## 15. Mock Connector Behavior

- **Base interface**: `write(self, employee: Employee, idempotency_key: str) -> ConnectorResult`
- **Standard response**: Returns fake `system_ref_id` (e.g., `"WD-00123"`).
- **`fake_expoit.py`**: Raises transient exception when `employee.employee_id == "emp_offcycle_test"`.

---

## 16. CLI & Testing Usage

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Run Tests
pytest                  # Unit tests (mocked Anthropic client, fast)
pytest -m integration   # Integration test (real Anthropic API call)

# CLI Execution
python -m src.main --event sample_events/name_change.json
python -m src.main --event sample_events/name_change.json --dry-run
```

---

## 17. Build Plan Order (Phases 1–11)

1. `models.py` + `state_store.py`
2. `connectors/` (all 5 fakes) + `base.py`
3. `validators.py` (`is_near_duplicate` included)
4. `sync_engine.py` (`normalize_event`, `process_event`, `write_with_retry`)
5. `sample_events/*.json` + `test_idempotency.py` + `test_partial_failure.py`
6. `test_offcycle_backfill.py`
7. `claude_handler.py` + `conftest.py` + `test_claude_conflict.py`
8. `audit_log.py` wiring
9. `main.py` CLI
10. `mcp_server.py` (stretch)
11. `systems_map.md` & `build_note.md` documentation deliverables

---

## 18. Acceptance Criteria Checklist

- [ ] `name_change.json` run twice produces exactly 1 write per downstream system (`test_idempotency.py`).
- [ ] Forced expoIT failure doesn't block Workday/Okta writes (`test_partial_failure.py`).
- [ ] `offcycle_hire.json` handled without fake Ashby record (`test_offcycle_backfill.py`).
- [ ] `is_near_duplicate()` flags `emp_2002` vs `emp_2001`, ignores non-matches.
- [ ] `test_claude_conflict.py` unit tests pass without API key / network; integration test passes with key.
- [ ] Low confidence (<0.7) or malformed Claude responses fallback to `needs_human_review`.
- [ ] Bad fields are dropped without dropping valid fields in the event.
- [ ] `--dry-run` makes zero writes.
- [ ] `systems_map.md` and `build_note.md` follow required headers and are complete.
- [ ] No extra third-party infrastructure added beyond spec.
