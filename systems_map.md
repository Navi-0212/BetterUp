# Systems Map

## Where data lives and moves

| System | Role in BetterUp Lifecycle | Upstream Dependencies | Downstream Consumers | Data Owned / Maintained |
|---|---|---|---|---|
| **Ashby** | ATS (Applicant Tracking System) | Candidate / Recruiter entry | Workday, BetterUp Sync Engine | Pre-hire candidate identity, offer data, legal name, initial personal email, proposed start date, home address, position, department. |
| **Workday** | Core HRIS (System of Record post-hire) | Ashby (via sync) or Direct HR Entry (Off-Cycle) | Okta, Lumos, expoIT, Cohort Tracker | Post-hire employee records, worker ID, employee status (Active/Terminated), legal entity, supervisor hierarchy, off-cycle hire provenance. |
| **Okta** | Identity Provider (IdP / SSO / Auth) | Workday (or Ashby pre-hire) | Lumos, Downstream Cloud Apps (Google, Slack, BetterUp Platform) | Corporate work email (`@betterup.co`), user credentials, identity groups, authentication tokens, SSO state. |
| **Lumos** | Access Governance & App Provisioning | Okta, Workday | SaaS Applications, Internal Tools | Role-based app assignments, zero-trust access policies, time-bound elevated entitlements, joiner/mover/leaver access workflows. |
| **expoIT** | Hardware Vendor & Logistics Reseller | Workday / Ashby (via Sync Engine) | Hardware Couriers (FedEx, DHL), Employee Home | Hardware shipment order, asset serial tracking, laptop delivery status, employee residential shipping address. |
| **Cohort Tracker** | Internal Coordination & Onboarding Tracking | Ashby, Workday, Okta, expoIT | People Ops, Hiring Managers, IT Coordinators | Onboarding readiness checklist, milestone gates (background check, I-9, laptop delivered, IT account ready), start date cohort grouping. |

---

## Where it breaks today

The manual and point-to-point synchronization across these five disparate systems introduces three primary failure modes in production:

1. **Change Propagation Failures**:
   - Post-offer modifications (e.g., an updated legal name, an international or local address change, or a postponed start date) made in Ashby often fail to cascade to downstream systems.
   - When changes do not reach expoIT, laptops are shipped to outdated residential addresses.
   - When start dates shift in Ashby but not in Okta or Lumos, accounts are provisioned either too early (security risk) or late (day-one blocker).
   - Off-cycle hires created directly in Workday bypass Ashby entirely, causing downstream identity, access, and logistics sync to stall.

2. **Bad Data Cascades**:
   - Incomplete or malformed data in Ashby (such as names containing digits/test strings, empty address lines, or impossible retroactive start dates) flows directly into Workday, Okta, and shipping manifests unchecked.
   - This leads to corrupted corporate email addresses, failed hardware dispatches, and manual engineering triage.

3. **Ungated Milestones & Missing Exception Visibility**:
   - Critical prerequisites (e.g., identity verification, hardware dispatch confirmation, and day-one SSO account readiness) operate against loose 7-day deadlines without unified tracking.
   - When a downstream system fails (e.g., expoIT API outage), the error remains silent until the new hire’s start day, leading to last-minute operational fires.

---

## Slice chosen and why

**Chosen Slice**: **Change Propagation with Inline Field Validation & Deterministic Pre-Filtering** (plus an MCP identity resolution tool and audit logging).

### Strategic Justification for the Debrief:
1. **Core Engineering Depth**:
   Change propagation is the only architectural slice that necessitates a canonical unified data model (`Employee`), an event-driven delta normalizer, and per-system idempotent retry mechanisms. It solves the foundational root cause rather than patching symptoms.

2. **Zero-Overhead Inline Validation**:
   Validation is embedded at the moment field deltas are transformed for downstream fan-out. By filtering invalid fields at the boundary without discarding valid field updates from the same event, bad data cascades are prevented with zero added network hops.

3. **Targeted, Non-Gimmicky LLM Utilization**:
   LLMs are not used as generic brittle system glue or rigid routing rules. Instead, Claude 3.5 Sonnet is deployed strictly for ambiguous identity deduplication (e.g., distinguishing between a near-duplicate rehire and an off-cycle collision) under strict deterministic confidence thresholds ($\ge 0.70$).

4. **Extensible Observability**:
   With append-only JSON Lines audit logging and ledger-backed idempotency tracking, exception monitoring (`needs_attention()`) and Model Context Protocol (MCP) server endpoints become lightweight read models on top of clean state.
