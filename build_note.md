# Build Note

## Why this slice

Change propagation sits at the intersection of data consistency, fault tolerance, and multi-system orchestration in BetterUp's hiring ecosystem. While point solutions like isolated validation scripts or standalone dashboard UIs treat superficial symptoms, building change propagation forces:
- A canonical domain representation (`Employee`) reconciling pre-hire and post-hire schemas.
- Per-system fan-out logic with fine-grained field-to-system routing (`SYSTEMS_FOR_FIELD`).
- Resilient, idempotent delivery guarantees that prevent duplicate writes across downstream providers.
- Real-time exception isolation where partial downstream outages do not compromise healthy integrations.

By validating fields inline during transformation, we prevent bad data cascades without introducing extra microservices. Furthermore, identity conflict disambiguation leverages Claude 3.5 Sonnet only where heuristic matching reaches its limits, preserving deterministic execution for standard operations.

---

## Key design decisions

### Data model
- **Canonical Pydantic v2 Models**: Enforced strict typing across all modules (`Employee`, `Address`, `ChangeEvent`, `FieldDelta`, `LedgerEntry`, `AuditLogEntry`, `ConflictResolution`, `ProcessResult`).
- **Timezone-Aware UTC**: All timestamps strictly adhere to ISO-8601 UTC with explicit `Z` suffixes (`datetime.now(timezone.utc)`), avoiding deprecated `datetime.utcnow()`.
- **Field-Level Granularity**: `FieldDelta` captures `old_value` and `new_value` to enable no-op delta dropping (`old_value == new_value`) before validation or downstream fan-out.
- **Partial Field Validation**: `validate_fields()` drops malformed or invalid fields (e.g., numeric characters in legal names, incomplete address objects, or dates prior to event receipt) into `AuditLogEntry(action="VALIDATION_REJECTED")` while allowing remaining valid fields in the same payload to propagate unimpeded.

### Failure handling & idempotency
- **Cryptographic Idempotency Keys**: Deterministically computed via SHA-256:
  $$\text{idempotency\_key} = \text{sha256}(f\text{"}\{\text{employee\_id}\}:\{\text{field\_name}\}:\{\text{new\_value}\}:\{\text{target\_system}\}\text{"})$$
- **Pre-Write Ledger Verification**: The engine checks `store.get_ledger_entry(key)`. If an entry exists with status `ACKED`, the write is immediately bypassed and logged as `NO_OP_SKIPPED`.
- **Exponential Backoff with Jitter-Free Injection**: Implements exponential backoff:
  $$\text{delay} = 0.1 \times 2^{\text{attempt\_number}}\quad (\text{seconds}), \quad \text{max\_attempts}=3$$
  Using injectable clock fixtures (`sleep_fn = lambda _: None`), the entire retry test suite executes in $< 20\,\text{ms}$ with zero wall-clock sleep.
- **Failure Isolation**: Connector writes are independently wrapped in discrete `try/except` blocks. If expoIT fails (e.g., during hardware shipment outages), Workday, Okta, Lumos, and Tracker updates succeed without obstruction.
- **Terminal FAILED State**: Exceeded retries transition the ledger entry to `FAILED`, which automatically surfaces through `store.needs_attention()`.

### The off-cycle / no-single-source-of-truth decision (Section 3)
In BetterUp's operational environment, Ashby serves as the authority pre-hire, while Workday is the system of record post-hire. When direct off-cycle hires originate in Workday without an antecedent Ashby candidate profile, the sync engine recognizes Workday as the primary authority for that record and assigns `source_system="WORKDAY_OFFCYCLE"`. 

We deliberately **do not construct fictitious Ashby records or synthetic pre-hire ATS artifacts**. Doing so would introduce ghost entity tracking, false recruiter attribution, and artificial lifecycle states.

---

## What I'd productionize

- **Real Webhooks & Ingestion Gateway**: Replace static JSON file ingestion with an authenticated webhook receiver endpoint (HMAC signature verification for Ashby and Workday outbound notifications).
- **Relational / Distributed Database**: Replace atomic local JSON files (`employees.json`, `ledger.json`) with PostgreSQL using row-level locking or optimistic concurrency control, and partition audit logs into BigQuery / Snowflake.
- **Production OAuth 2.0 Client Credentials Flow**:
  - Implement an enterprise OAuth2 client-credentials flow per downstream provider (Workday, Okta, Lumos, expoIT).
  - Securely fetch client IDs and secrets from an enterprise secrets manager (e.g., AWS Secrets Manager, HashiCorp Vault) rather than static files.
  - In-memory JWT/bearer token caching with TTL inspection and automatic renewal via a connector-level `_get_token()` hook prior to downstream dispatch.
- **Real-Time Slack & PagerDuty Alerting**:
  - Direct integration hook off `store.needs_attention()` triggering formatted Slack notifications to `#people-ops-triage` and `#it-ops-alerts` when writes reach `FAILED` status or identity conflicts require human decision-making.
- **Distributed Event Queue**: Integrate with an existing message broker (e.g., AWS SQS or n8n workflow engine) to ensure durable cross-region replay and dead-letter queue (DLQ) management.

---

## What I chose not to add, and why

- **No Heavy Database Servers (PostgreSQL / MySQL / Redis)**:
  Local atomic JSON persistence with directory locking satisfies all requirements at interview prototype scale. It provides immediate readability, transparent inspection, and deterministic test isolation without requiring background services or Docker daemons.
- **No Heavy Message Queues (Kafka / RabbitMQ / Celery)**:
  An in-process orchestrator with explicit ledger persistence cleanly proves the idempotency and retry mechanics. In a full production deployment, the existing n8n/orchestrator stack can provide external triggers and queueing.
- **No Unnecessary Web Frameworks (FastAPI / Flask / Django)**:
  A clean, POSIX-compliant CLI (`src/main.py`) paired with an official stdio Model Context Protocol (MCP) server provides complete scriptability, zero-dependency dry-run simulation, and live LLM invocation without web server overhead.

---

## AI tools used

- **Developer AI Assistant (LLM Code Generation & Refactoring)**: Used for scaffolding repetitive boilerplate models, connector mock stubs, and unit test fixture templates.
- **Google Gemini API (`google-genai` SDK / `gemini-2.5-flash`)**: Domain-specific identity conflict disambiguation using structured JSON outputs with confidence safety gating via `GeminiHandler`.
- **Model Context Protocol (MCP) SDK**: stdio interface (`src/mcp_server.py`) exposing identity resolution tools directly to AI desktop clients and IDE agent toolchains.

---

## One thing the AI got wrong, and how I caught it

During the implementation of the MCP server and test fixtures:
1. **MCP SDK FastMCP Module Location**: The AI originally pulled `mcp` version `2.0.0`, where the internal structure deprecated `mcp.server.fastmcp` in favor of `mcp.server.mcpserver`. Running the test suite immediately surfaced `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. I caught this by running `py -3.14 -m pytest`, pinpointed the breaking version delta, pinned `mcp>=1.2.0,<2.0.0` in [requirements.txt](file:///c:/Projects/Sync%20engine%20-%20BetterUp/requirements.txt), and installed `mcp-1.29.0`.
2. **Enum Literal Mismatch on ChangeEvent**: In `test_audit_log.py`, the AI attempted to construct a `ChangeEvent` with `source_system="WORKDAY_OFFCYCLE"`. Pydantic immediately raised a `ValidationError` because `ChangeEvent.source_system` is strictly constrained to `Literal["ASHBY", "WORKDAY"]` (the external origin of the webhook), whereas `"WORKDAY_OFFCYCLE"` is exclusively assigned to the canonical `Employee.source_system` model during normalization. I identified the schema boundary violation from the pytest stacktrace and corrected the test fixture to pass `source_system="WORKDAY"`.
