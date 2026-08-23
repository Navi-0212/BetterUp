# BetterUp Sync Engine — System Architecture Specification

This document provides a comprehensive technical architecture description of the **BetterUp Change Propagation Sync Engine**, detailing data models, subsystem interactions, control flow, failure domains, idempotency guarantees, and AI-assisted ambiguity resolution.

---

## 1. Executive Architecture Summary

The BetterUp Sync Engine coordinates employee lifecycle changes across 5 downstream systems (**Workday, Okta, Lumos, expoIT, Cohort Tracker**) originating from upstream signals (**Ashby ATS** or **Workday Off-Cycle**).

```mermaid
flowchart TD
    subgraph Ingestion["1. Ingestion & Normalization"]
        CE["ChangeEvent (JSON / Webhook)"] --> NE["normalize_event()"]
        NE --> Candidate["Candidate Employee Model"]
    end

    subgraph ConflictResolution["2. Conflict Detection & AI Resolution"]
        Candidate --> PreFilter{"is_near_duplicate()"}
        PreFilter -- "No match (Ratio < 0.75)" --> ValidLayer["Inline Field Validation"]
        PreFilter -- "Potential Match (Ratio >= 0.75)" --> ClaudeHandler["ClaudeHandler.resolve_conflict()"]
        ClaudeHandler --> ConfGate{"Confidence >= 0.7 & Parsed?"}
        ConfGate -- "Yes (same_person / different_person)" --> ValidLayer
        ConfGate -- "No / Low Confidence" --> FlagHuman["Flag NEEDS_HUMAN_REVIEW\n(Drop & Surface)"]
    end

    subgraph Validation["3. Inline Field Validation"]
        ValidLayer --> VF["validate_fields()"]
        VF --> DropInvalid["Drop Invalid Fields\n(VALIDATION_REJECTED)"]
        VF --> PropagateValid["Valid Fields Set"]
    end

    subgraph FanOut["4. Fan-out & System Transformers"]
        PropagateValid --> T_WD["transform_for_workday()"]
        PropagateValid --> T_OKTA["transform_for_okta()"]
        PropagateValid --> T_LUMOS["transform_for_lumos()"]
        PropagateValid --> T_EXPO["transform_for_expoit()"]
        PropagateValid --> T_TRK["transform_for_tracker()"]
    end

    subgraph Execution["5. Idempotent Retry Execution"]
        T_WD --> W_WD["write_with_retry(Workday)"]
        T_OKTA --> W_OKTA["write_with_retry(Okta)"]
        T_LUMOS --> W_LUMOS["write_with_retry(Lumos)"]
        T_EXPO --> W_EXPO["write_with_retry(expoIT)"]
        T_TRK --> W_TRK["write_with_retry(Tracker)"]
    end

    subgraph Persistence["6. Persistence & Audit"]
        W_WD & W_OKTA & W_LUMOS & W_EXPO & W_TRK --> SS[("StateStore (employees.json, ledger.json)")]
        W_WD & W_OKTA & W_LUMOS & W_EXPO & W_TRK --> AL[("audit_log.jsonl")]
    end
```

---

## 2. Core Architectural Principles

1. **Change Propagation with Inline Validation**:
   Validation is performed directly during field transformation before dispatching downstream writes, ensuring invalid inputs are rejected without halting unaffected valid fields.
2. **Deterministic Pre-Filtering before LLM Gating**:
   LLMs are expensive and non-deterministic. A fast standard-library string similarity algorithm (`SequenceMatcher`) filters out 99%+ of routine traffic. Claude 3.5 Sonnet is invoked *only* when genuine ambiguity exists.
3. **Strict Downstream Idempotency & Fault Isolation**:
   Every downstream write is guarded by a deterministic SHA-256 key in an appendable Ledger. Per-system `try/except` wrappers guarantee that a failure in one connector (e.g. expoIT hardware failure) does not block writes to identity (Okta) or access governance (Lumos).
4. **Canonical Data Modeling (Pydantic v2)**:
   Strict typing and validation boundaries across all modules; no unstructured dictionaries cross internal boundaries.
5. **No Synthetic State Creation (Off-Cycle Design)**:
   Off-cycle hires originating in Workday without an Ashby antecedent are treated as canonical with `source_system = WORKDAY_OFFCYCLE`. Fictitious pre-hire records are never created.

---

## 3. Subsystem Breakdown & Contracts

### 3.1 Ingestion & Normalization (`sync_engine.py`)

Normalizes heterogeneous incoming events into the canonical `Employee` schema.

```mermaid
sequenceDiagram
    autonumber
    participant Source as Event Source (CLI/Webhook)
    participant Engine as sync_engine
    participant Store as StateStore

    Source->>Engine: process_event(ChangeEvent)
    Engine->>Engine: Check event_type
    alt event_type == "FIELD_CHANGE"
        Engine->>Store: get_employee(event.employee_id)
        Store-->>Engine: existing Employee
        Engine->>Engine: Merge changed_fields onto existing
    else event_type == "OFFCYCLE_HIRE_DETECTED"
        Engine->>Engine: Build Employee directly from raw_payload
        Engine->>Engine: Tag source_system = WORKDAY_OFFCYCLE
    end
    Engine-->>Engine: candidate Employee
```

- **Drop No-Op Deltas**: Before any validation, if `delta.old_value == delta.new_value`, drop the delta and record `NO_OP_SKIPPED`.

---

### 3.2 Identity Resolution Pipeline (`validators.py` & `claude_handler.py`)

A two-tiered verification pipeline designed to detect near-duplicates and resolve name variations without manual human intervention unless required.

```mermaid
flowchart LR
    Candidate["Incoming Candidate"] --> PreFilter["Step 1: is_near_duplicate()\n(Difflib SequenceMatcher >= 0.75)"]
    PreFilter -- False --> Safe["Proceed to Validation"]
    PreFilter -- True --> ClaudeCall["Step 2: ClaudeHandler.resolve_conflict()\n(Claude 3.5 Sonnet JSON output)"]
    ClaudeCall --> Eval{"confidence >= 0.7\nand valid JSON?"}
    Eval -- Yes --> Branch{"decision"}
    Branch -- "same_person" --> Merge["Merge / Update Record"]
    Branch -- "different_person" --> Split["Keep as Distinct Entity"]
    Branch -- "needs_human_review" --> HumanReview["Mark NEEDS_HUMAN_REVIEW\nSurface in needs_attention()"]
    Eval -- No --> HumanReview
```

#### Deterministic Filter Rule (`is_near_duplicate`):
1. Returns `False` if `candidate.employee_id == existing.employee_id` (same record).
2. Returns `False` if `candidate.start_date != existing.start_date` (different hire cohorts).
3. Returns `False` if normalized names are exact matches (standard update flow).
4. Calculates `SequenceMatcher(None, name_a, name_b).ratio()`. If $\ge 0.75$, triggers Claude.

#### LLM Gating Rule:
- System prompt forces pure JSON response: `{"decision": "...", "confidence": 0.0-1.0, "reasoning": "..."}`.
- If JSON parsing fails OR `confidence < 0.70`, the system unconditionally overrides the decision to `needs_human_review`.

---

### 3.3 Inline Field Validation (`validators.py`)

Transforms and validates individual fields in isolation:

| Field | Rule | Rejection Behavior |
|---|---|---|
| `legal_first_name` | Non-empty string, no numeric digits | Field dropped; logs `VALIDATION_REJECTED` |
| `legal_last_name` | Non-empty string, no numeric digits | Field dropped; logs `VALIDATION_REJECTED` |
| `address` | `line1`, `city`, `state`, `postal_code`, `country` non-empty | Address group dropped; logs `VALIDATION_REJECTED` |
| `start_date` | Date cannot be before `event.received_at` date | Start date dropped; logs `VALIDATION_REJECTED` |

---

### 3.4 Idempotency & Resilient Retry Engine (`sync_engine.py`)

To prevent duplicate API invocations (such as duplicate laptop shipments or repeated email creations), all writes pass through an atomic Ledger check.

```mermaid
flowchart TD
    Start["write_with_retry(connector, employee, key)"] --> CalcKey["Compute idempotency_key\nsha256(employee_id:field:val:system)"]
    CalcKey --> CheckLedger{"LedgerEntry exists & status == ACKED?"}
    CheckLedger -- "Yes (Already Done)" --> Skip["Log NO_OP_SKIPPED\nReturn existing LedgerEntry"]
    CheckLedger -- "No" --> Loop["Attempt Write (attempt = 1..3)"]
    
    Loop --> TryWrite["connector.write(employee, key)"]
    TryWrite -- Success --> MarkAck["Set status = ACKED\nSave system_ref_id\nSave Ledger"]
    TryWrite -- Failure --> CheckCount{"attempt < 3?"}
    
    CheckCount -- Yes --> Backoff["delay = 0.1 * (2 ** attempt)\nsleep_fn(delay)"]
    Backoff --> Loop
    CheckCount -- No --> MarkFail["Set status = FAILED\nRecord error_message\nSave Ledger"]
    MarkFail --> Notify["Surfaces via needs_attention()"]
```

#### Mathematical Properties:
- **Idempotency Key Hash**:
  $$\text{Key} = \text{SHA256}(f\text{"}\{\text{employee\_id}\}:\{\text{field\_name}\}:\{\text{new\_value}\}:\{\text{target\_system}\}\text{"})$$
- **Exponential Backoff Schedule**:
  $$\Delta t_n = 0.1 \times 2^n \quad \text{for } n \in \{1, 2, 3\}$$
  - Attempt 1 failure: sleep $0.2\,\text{s}$
  - Attempt 2 failure: sleep $0.4\,\text{s}$
  - Attempt 3 failure: sleep $0.8\,\text{s} \rightarrow \text{FAILED}$

---

### 3.5 Storage & Ledger Persistence Architecture (`state_store.py` & `audit_log.py`)

All runtime state is stored in lightweight, zero-dependency, local file structures under `data/`:

```
data/
├── employees.json      # Keyed JSON Object: { "<employee_id>": { ...Employee } }
├── ledger.json         # Keyed JSON Object: { "<idempotency_key>": { ...LedgerEntry } }
└── audit_log.jsonl     # Append-Only JSON Lines: { ...AuditLogEntry }\n
```

```mermaid
classDiagram
    class StateStore {
        +Path data_dir
        +get_employee(employee_id: str) Employee?
        +save_employee(employee: Employee) None
        +all_employees() List~Employee~
        +get_ledger_entry(key: str) LedgerEntry?
        +save_ledger_entry(entry: LedgerEntry) None
        +needs_attention() List~LedgerEntry~
    }

    class AuditLog {
        +Path log_path
        +append(entry: AuditLogEntry) None
        +read_all() List~AuditLogEntry~
    }

    StateStore --> "1" Employee : manages
    StateStore --> "1" LedgerEntry : manages
    AuditLog --> "1" AuditLogEntry : records
```

---

## 4. Downstream Connector Specifications

Each connector adheres to the base interface contract:
```python
class Connector(ABC):
    @abstractmethod
    def write(self, employee: Employee, idempotency_key: str) -> ConnectorResult:
        pass
```

| Connector | Systems Handled | Payload Mappings | Failure Simulation |
|---|---|---|---|
| `fake_workday.py` | HRIS Record | `legal_name`, `address`, `start_date`, `position`, `department` | Returns `"WD-<hash>"` |
| `fake_okta.py` | SSO / Directory | `personal_email`, `legal_name` $\rightarrow$ Generates `work_email` | Returns `"OKTA-<hash>"` |
| `fake_lumos.py` | Access Governance | `department`, `position_title` $\rightarrow$ Role entitlements | Returns `"LUMOS-<hash>"` |
| `fake_expoit.py` | IT Laptop Fulfillment | `shipping_address`, `legal_name` | Throws error if `employee_id == 'emp_offcycle_test'` |
| `fake_tracker.py` | Cohort Tracking | Checklist lifecycle item updates | Returns `"TRK-<hash>"` |

---

## 5. Security & Authentication Architecture (Production Design)

For production deployment (as documented in `build_note.md`), connectors use **OAuth 2.0 Client Credentials Grant**:

```mermaid
sequenceDiagram
    autonumber
    participant Conn as System Connector
    participant TokenCache as In-Memory Token Cache
    participant OAuth as Identity Provider (e.g., Okta/Workday Auth)
    participant API as Downstream REST API

    Conn->>TokenCache: get_token(target_system)
    alt Token valid in cache
        TokenCache-->>Conn: Bearer Token
    else Token missing or expired
        Conn->>OAuth: POST /oauth/token (client_id, client_secret)
        OAuth-->>Conn: access_token, expires_in
        Conn->>TokenCache: cache_token(token, expires_at - 60s)
    end
    Conn->>API: HTTP Request + Authorization: Bearer <token>
    API-->>Conn: HTTP 200 / 201 Response
```

- **Secrets Handling**: Credentials (`CLIENT_ID`, `CLIENT_SECRET`, `ANTHROPIC_API_KEY`) loaded strictly from environment or AWS Secrets Manager / HashiCorp Vault. Zero credentials committed to git.

---

## 6. Stretch Integration: Model Context Protocol (MCP) Server

An optional MCP server (`src/mcp_server.py`) exposes identity conflict resolution to desktop agents (Claude Code, Claude Desktop, Cursor):

```mermaid
flowchart LR
    ClaudeDesktop["Claude Desktop / Claude Code Client"] -- stdio / JSON-RPC --> MCPServer["src/mcp_server.py"]
    MCPServer --> ToolWrapper["Tool: resolve_identity_conflict"]
    ToolWrapper --> Handler["ClaudeHandler.resolve_conflict()"]
    Handler --> AnthropicAPI["Anthropic Messages API"]
```

---

## 7. Quality Assurance & Verification Topology

```mermaid
flowchart TD
    subgraph TestSuite["Test Suite Topology"]
        UT["Unit Tests (Default)"] --> UT1["test_idempotency.py\n(No-op replay check)"]
        UT --> UT2["test_partial_failure.py\n(Isolated expoIT error)"]
        UT --> UT3["test_offcycle_backfill.py\n(Workday offcycle provenance)"]
        UT --> UT4["test_validation.py\n(Malformed fields dropped)"]
        UT --> UT5["test_claude_conflict.py\n(Mocked client, confidence gating)"]
        
        IT["Integration Tests (pytest -m integration)"] --> IT1["test_claude_conflict.py\n(Live Anthropic API call with ambiguous_name_conflict.json)"]
    end
```

- **Speed Guarantee**: `sleep_fn = lambda _: None` allows the entire test suite including 3-attempt exponential retries to execute in $< 200\,\text{ms}$.
- **Air-Gapped Default**: Zero external API dependencies required for standard CI runs.