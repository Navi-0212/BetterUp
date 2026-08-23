// BetterUp Sync Engine Frontend Application — Obsidian Ember Refined

function getApiBase() {
  const custom = localStorage.getItem("betterup_api_base");
  if (custom) return custom.replace(/\/$/, "");
  if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
    return "";
  }
  return window.DEFAULT_API_BACKEND_URL || "";
}

const API_BASE = getApiBase();

// State
let currentSamples = [];
let isProcessing = false;

// DOM Elements
const sampleSelect = document.getElementById("sample-select");
const eventEditor = document.getElementById("event-editor");
const toggleDryRun = document.getElementById("toggle-dry-run");
const dryRunLabel = document.getElementById("dry-run-label");
const btnProcess = document.getElementById("btn-process");
const resultBox = document.getElementById("result-box");
const execStatusBadge = document.getElementById("execution-status-badge");

const statEmployees = document.getElementById("stat-employees");
const statLedger = document.getElementById("stat-ledger");
const statAudit = document.getElementById("stat-audit");
const statAttention = document.getElementById("stat-attention");

const badgeEmployees = document.getElementById("badge-employees");
const badgeAudit = document.getElementById("badge-audit");
const badgeAttention = document.getElementById("badge-attention");

const employeesTbody = document.getElementById("employees-tbody");
const ledgerTbody = document.getElementById("ledger-tbody");
const auditFeedList = document.getElementById("audit-feed-list");
const auditFilterAction = document.getElementById("audit-filter-action");
const employeeSearch = document.getElementById("employee-search");

const attentionAlertBox = document.getElementById("attention-alert-box");
const attentionAlertTitle = document.getElementById("attention-alert-title");

// AI Conflict Lab Elements
const aiRecA = document.getElementById("ai-rec-a");
const aiRecB = document.getElementById("ai-rec-b");
const btnRunAiLab = document.getElementById("btn-run-ai-lab");
const btnLoadAmbiguous = document.getElementById("btn-load-ambiguous-demo");
const aiLabDecisionBadge = document.getElementById("ai-lab-decision-badge");
const aiLabConfidence = document.getElementById("ai-lab-confidence");
const aiGaugeCircle = document.getElementById("ai-gauge-circle");
const aiLabReasoning = document.getElementById("ai-lab-reasoning");
const aiDecisionBox = document.getElementById("ai-decision-box");
const aiDecisionIcon = document.getElementById("ai-decision-icon");
const aiModelBadge = document.getElementById("ai-model-badge");

// Pipeline Visualizer Nodes
const nodeNormalize = document.getElementById("node-normalize");
const nodePrefilter = document.getElementById("node-prefilter");
const nodeValidate = document.getElementById("node-validate");
const nodeFanout = document.getElementById("node-fanout");

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initEventListeners();
  loadAllData();
  initAiLabDefaults();
});

// Tabs Navigation
function initTabs() {
  const navItems = document.querySelectorAll(".nav-item");
  const tabContents = document.querySelectorAll(".tab-content");

  navItems.forEach(item => {
    item.addEventListener("click", () => {
      const tabId = item.getAttribute("data-tab");
      navItems.forEach(n => n.classList.remove("active"));
      tabContents.forEach(t => t.classList.remove("active"));

      item.classList.add("active");
      const target = document.getElementById(tabId);
      if (target) target.classList.add("active");

      // Tab specific reloads
      if (tabId === "tab-employees") loadEmployees();
      if (tabId === "tab-ledger") loadLedger();
      if (tabId === "tab-audit") loadAuditLogs();
      if (tabId === "tab-systems") loadSystems();
    });
  });
}

// Event Listeners
function initEventListeners() {
  sampleSelect.addEventListener("change", (e) => {
    const selected = currentSamples.find(s => s.filename === e.target.value);
    if (selected) {
      eventEditor.value = JSON.stringify(selected.content, null, 2);
    }
  });

  toggleDryRun.addEventListener("change", (e) => {
    dryRunLabel.textContent = e.target.checked ? "Dry Run (Simulation Only)" : "Live Execution (Persisted)";
  });

  btnProcess.addEventListener("click", handleProcessEvent);

  document.getElementById("btn-seed").addEventListener("click", async () => {
    try {
      const res = await fetch(`${API_BASE}/api/seed-demo-data`, { method: "POST" });
      const data = await res.json();
      alert("✅ " + data.message);
      loadAllData();
    } catch (e) {
      alert("Failed to seed demo data: " + e);
    }
  });

  document.getElementById("btn-reset").addEventListener("click", async () => {
    if (!confirm("Are you sure you want to clear all state store and audit log data?")) return;
    try {
      const res = await fetch(`${API_BASE}/api/reset-data`, { method: "POST" });
      const data = await res.json();
      alert("🧹 " + data.message);
      loadAllData();
    } catch (e) {
      alert("Failed to reset data: " + e);
    }
  });

  document.getElementById("btn-config-api").addEventListener("click", () => {
    const current = localStorage.getItem("betterup_api_base") || "";
    const updated = prompt(
      "Enter your Railway Backend API URL (e.g. https://betterup-backend.up.railway.app)\nLeave blank to use relative / local API:",
      current
    );
    if (updated !== null) {
      if (updated.trim()) {
        localStorage.setItem("betterup_api_base", updated.trim());
      } else {
        localStorage.removeItem("betterup_api_base");
      }
      window.location.reload();
    }
  });

  auditFilterAction.addEventListener("change", () => {
    loadAuditLogs(auditFilterAction.value);
  });

  employeeSearch.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    const rows = employeesTbody.querySelectorAll("tr");
    rows.forEach(r => {
      const text = r.textContent.toLowerCase();
      r.style.display = text.includes(q) ? "" : "none";
    });
  });

  btnRunAiLab.addEventListener("click", handleRunAiLab);

  if (btnLoadAmbiguous) {
    btnLoadAmbiguous.addEventListener("click", initAiLabDefaults);
  }

  const btnKeepA = document.getElementById("btn-keep-a");
  if (btnKeepA) {
    btnKeepA.addEventListener("click", () => {
      alert("Record A preserved in canonical store.");
    });
  }

  const btnKeepB = document.getElementById("btn-keep-b");
  if (btnKeepB) {
    btnKeepB.addEventListener("click", () => {
      alert("Record B selected. Updating canonical employee profile.");
    });
  }
}

// Global Loaders
async function loadAllData() {
  loadOverview();
  loadSampleEvents();
  loadEmployees();
  loadLedger();
  loadAuditLogs();
  loadSystems();
}

async function loadOverview() {
  try {
    const res = await fetch(`${API_BASE}/api/overview`);
    const data = await res.json();

    statEmployees.textContent = data.employee_count;
    statLedger.textContent = data.ledger_entry_count;
    statAudit.textContent = data.audit_log_count;
    statAttention.textContent = data.needs_attention_count;

    badgeEmployees.textContent = data.employee_count;
    badgeAudit.textContent = data.audit_log_count;

    if (data.needs_attention_count > 0) {
      badgeAttention.textContent = data.needs_attention_count;
      badgeAttention.style.display = "inline-flex";
      statAttention.style.color = "var(--error)";
    } else {
      badgeAttention.style.display = "none";
      statAttention.style.color = "var(--tertiary)";
    }

    if (data.llm_model && aiModelBadge) {
      aiModelBadge.textContent = data.llm_model;
    }
  } catch (e) {
    console.error("Overview error:", e);
  }
}

async function loadSampleEvents() {
  try {
    const res = await fetch(`${API_BASE}/api/sample-events`);
    currentSamples = await res.json();
    sampleSelect.innerHTML = '<option value="">-- Choose Sample Event --</option>';
    currentSamples.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.filename;
      opt.textContent = `${s.name} (${s.event_type})`;
      sampleSelect.appendChild(opt);
    });

    if (currentSamples.length > 0 && !eventEditor.value) {
      sampleSelect.value = currentSamples[0].filename;
      eventEditor.value = JSON.stringify(currentSamples[0].content, null, 2);
    }
  } catch (e) {
    console.error("Sample events error:", e);
  }
}

// Process Event Handler
async function handleProcessEvent() {
  if (isProcessing) return;
  let payload;
  try {
    payload = JSON.parse(eventEditor.value);
  } catch (e) {
    alert("Invalid JSON payload: " + e.message);
    return;
  }

  isProcessing = true;
  btnProcess.disabled = true;
  execStatusBadge.className = "badge badge-neutral";
  execStatusBadge.textContent = "Executing Pipeline...";

  // Animate Pipeline visualizer
  resetPipelineVisualizer();
  await animateNode(nodeNormalize, 150);
  await animateNode(nodePrefilter, 200);
  await animateNode(nodeValidate, 150);
  await animateNode(nodeFanout, 200);

  const dryRun = toggleDryRun.checked;

  try {
    const res = await fetch(`${API_BASE}/api/process-event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_data: payload, dry_run: dryRun }),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Server error processing event");
    }

    renderExecutionResult(data.result, dryRun, data.employee);
    loadOverview();
  } catch (e) {
    resultBox.innerHTML = `
      <div style="color:var(--error); font-family:var(--font-mono); font-size:0.85rem;">
        <span class="badge badge-danger">Processing Error</span>
        <p style="margin-top:8px;">${e.message}</p>
      </div>
    `;
    execStatusBadge.className = "badge badge-danger";
    execStatusBadge.textContent = "Failed";
  } finally {
    isProcessing = false;
    btnProcess.disabled = false;
  }
}

function resetPipelineVisualizer() {
  [nodeNormalize, nodePrefilter, nodeValidate, nodeFanout].forEach(n => n.classList.remove("active"));
}

async function animateNode(node, duration) {
  node.classList.add("active");
  return new Promise(r => setTimeout(r, duration));
}

function renderExecutionResult(result, dryRun, employee) {
  let statusBadge = "";
  if (result.needs_human_review) {
    statusBadge = '<span class="badge badge-warning">NEEDS_HUMAN_REVIEW</span>';
    execStatusBadge.className = "badge badge-warning";
    execStatusBadge.textContent = "Needs Review";
  } else if (result.systems_failed && result.systems_failed.length > 0) {
    statusBadge = '<span class="badge badge-danger">PARTIAL_FAILURE</span>';
    execStatusBadge.className = "badge badge-danger";
    execStatusBadge.textContent = "Partial Failure";
  } else {
    statusBadge = '<span class="badge badge-success">SUCCESS</span>';
    execStatusBadge.className = "badge badge-success";
    execStatusBadge.textContent = "Completed";
  }

  let html = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h4 style="font-family:var(--font-headline); font-size:0.95rem; color:var(--text-primary);">
        Output: ${dryRun ? "DRY RUN SIMULATION" : "LIVE STATE UPDATE"}
      </h4>
      ${statusBadge}
    </div>
    
    <div style="font-size:0.8rem; color:var(--text-variant); margin-bottom:12px; font-family:var(--font-mono);">
      Event ID: <strong style="color:#FFF;">${result.event_id}</strong> | Employee: <strong style="color:#FFF;">${result.employee_id}</strong>
    </div>

    <div style="margin-bottom:12px;">
      <div style="font-family:var(--font-mono); font-size:0.72rem; color:var(--text-muted); text-transform:uppercase; margin-bottom:4px;">
        Propagated Fields (${result.fields_propagated.length})
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:6px;">
        ${result.fields_propagated.length > 0 
          ? result.fields_propagated.map(f => `<span class="badge badge-success">✓ ${f}</span>`).join("")
          : '<span class="badge badge-neutral">None</span>'}
      </div>
    </div>

    <div style="margin-bottom:12px;">
      <div style="font-family:var(--font-mono); font-size:0.72rem; color:var(--text-muted); text-transform:uppercase; margin-bottom:4px;">
        Rejected Fields (${result.fields_rejected.length})
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:6px;">
        ${result.fields_rejected.length > 0 
          ? result.fields_rejected.map(f => `<span class="badge badge-danger">✗ ${f}</span>`).join("")
          : '<span class="badge badge-neutral">None (All fields valid)</span>'}
      </div>
    </div>

    <div style="margin-bottom:12px;">
      <div style="font-family:var(--font-mono); font-size:0.72rem; color:var(--text-muted); text-transform:uppercase; margin-bottom:4px;">
        Systems Written (${result.systems_written.length})
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:6px;">
        ${result.systems_written.length > 0
          ? result.systems_written.map(s => `<span class="badge badge-ashby">${s}</span>`).join("")
          : '<span class="badge badge-neutral">None</span>'}
      </div>
    </div>
  `;

  if (result.systems_failed && result.systems_failed.length > 0) {
    html += `
      <div style="margin-bottom:12px;">
        <div style="font-family:var(--font-mono); font-size:0.72rem; color:var(--error); text-transform:uppercase; margin-bottom:4px;">
          Failed Systems (${result.systems_failed.length})
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:6px;">
          ${result.systems_failed.map(s => `<span class="badge badge-danger">${s} (Max Retries)</span>`).join("")}
        </div>
      </div>
    `;
  }

  if (result.conflict_resolution) {
    html += `
      <div style="background:rgba(194,65,12,0.1); padding:10px; border-radius:6px; border:1px solid rgba(194,65,12,0.25); margin-top:8px;">
        <div style="font-family:var(--font-mono); font-size:0.75rem; color:var(--primary); font-weight:600;">Gemini Conflict Evaluation</div>
        <div style="font-size:0.8rem; margin-top:3px;">
          Decision: <strong>${result.conflict_resolution.decision}</strong> | Confidence: <strong>${(result.conflict_resolution.confidence * 100).toFixed(0)}%</strong>
          <p style="margin-top:2px; color:var(--text-variant); font-size:0.78rem;">${result.conflict_resolution.reasoning}</p>
        </div>
      </div>
    `;
  }

  resultBox.innerHTML = html;
}

// Load Employees Store
async function loadEmployees() {
  try {
    const res = await fetch(`${API_BASE}/api/employees`);
    const employees = await res.json();

    if (employees.length === 0) {
      employeesTbody.innerHTML = '<tr><td colspan="7" class="text-center p-4">No employee records in store. Click "Seed Demo" to load data.</td></tr>';
      return;
    }

    employeesTbody.innerHTML = employees.map(emp => `
      <tr>
        <td class="mono"><strong>${emp.employee_id}</strong></td>
        <td>${emp.legal_first_name} ${emp.legal_last_name}</td>
        <td>
          <div>${emp.position_title || "N/A"}</div>
          <span style="font-size:0.72rem; color:var(--text-muted);">${emp.department || "General"}</span>
        </td>
        <td class="mono">${emp.start_date}</td>
        <td class="mono">${emp.work_email || '<span style="color:var(--text-muted);">Unassigned</span>'}</td>
        <td>
          <span class="badge ${emp.source_system === 'ASHBY' ? 'badge-ashby' : 'badge-workday'}">
            ${emp.source_system}
          </span>
        </td>
        <td class="mono" style="font-size:0.75rem; color:var(--text-muted);">${emp.last_updated_by_event_id}</td>
      </tr>
    `).join("");
  } catch (e) {
    console.error("Load employees error:", e);
  }
}

// Load Ledger & Triage
async function loadLedger() {
  try {
    const res = await fetch(`${API_BASE}/api/ledger`);
    const data = await res.json();
    const entries = data.entries || [];
    const needsAttn = data.needs_attention || [];

    if (needsAttn.length > 0) {
      attentionAlertBox.style.display = "flex";
      attentionAlertTitle.textContent = `${needsAttn.length} Downstream System(s) Failed Write Attempts`;
    } else {
      attentionAlertBox.style.display = "none";
    }

    if (entries.length === 0) {
      ledgerTbody.innerHTML = '<tr><td colspan="7" class="text-center p-4">Ledger is empty. No downstream writes recorded yet.</td></tr>';
      return;
    }

    ledgerTbody.innerHTML = entries.map(e => `
      <tr>
        <td><strong>${e.target_system}</strong></td>
        <td class="mono" title="${e.idempotency_key}">${e.idempotency_key.substring(0, 16)}...</td>
        <td>
          <span class="badge ${e.status === 'ACKED' ? 'badge-success' : 'badge-danger'}">
            ${e.status}
          </span>
        </td>
        <td class="mono">${e.attempt_count} / 3</td>
        <td class="mono">${e.system_ref_id || '—'}</td>
        <td class="mono" style="font-size:0.75rem; color:var(--text-muted);">${e.updated_at ? new Date(e.updated_at).toLocaleTimeString() : '—'}</td>
        <td style="color:var(--error); font-size:0.8rem;">${e.error_message || '<span style="color:var(--text-muted);">None</span>'}</td>
      </tr>
    `).join("");
  } catch (e) {
    console.error("Load ledger error:", e);
  }
}

// Load Audit Logs Stream
async function loadAuditLogs(actionFilter = "") {
  try {
    let url = `${API_BASE}/api/audit-logs?limit=50`;
    if (actionFilter) url += `&action=${actionFilter}`;
    const res = await fetch(url);
    const logs = await res.json();

    if (logs.length === 0) {
      auditFeedList.innerHTML = '<div class="text-center p-4">No audit log entries recorded yet.</div>';
      return;
    }

    auditFeedList.innerHTML = logs.map(l => {
      let badgeClass = "badge-neutral";
      if (l.action === "FIELD_CHANGE_PROPAGATED") badgeClass = "badge-success";
      if (l.action === "VALIDATION_REJECTED") badgeClass = "badge-danger";
      if (l.action === "CLAUDE_CONFLICT_RESOLVED") badgeClass = "badge-warning";
      if (l.action === "NEEDS_HUMAN_REVIEW") badgeClass = "badge-danger";

      return `
        <div class="audit-entry-card">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span class="badge ${badgeClass}">${l.action}</span>
            <span class="mono" style="font-size:0.72rem; color:var(--text-muted);">${new Date(l.timestamp).toLocaleString()}</span>
          </div>
          <div style="display:flex; gap:12px; font-size:0.8rem; color:var(--text-variant); font-family:var(--font-mono);">
            <span>Event: <strong>${l.event_id}</strong></span>
            <span>Employee: <strong>${l.employee_id}</strong></span>
            ${l.target_system ? `<span>Target: <strong>${l.target_system}</strong></span>` : ''}
            <span>Trigger: <code>${l.triggered_by}</code></span>
          </div>
          ${(l.before_state || l.after_state) ? `
            <div class="audit-diff">
              ${l.before_state ? `<div class="diff-remove">- Before: ${JSON.stringify(l.before_state)}</div>` : ''}
              ${l.after_state ? `<div class="diff-add">+ After: ${JSON.stringify(l.after_state)}</div>` : ''}
            </div>
          ` : ''}
        </div>
      `;
    }).join("");
  } catch (e) {
    console.error("Load audit error:", e);
  }
}

// AI Conflict Lab Defaults & Handler
function initAiLabDefaults() {
  const sampleA = {
    employee_id: "emp_2001",
    legal_first_name: "Sanjay",
    legal_last_name: "Iyer",
    personal_email: "sanjay.demo@example.com",
    start_date: "2026-09-08",
    address: {
      line1: "12 Whitefield Main Rd",
      city: "Bengaluru",
      state: "KA",
      postal_code: "560066",
      country: "IN"
    },
    position_title: "Contractor - Data",
    department: "Analytics",
    source_system: "WORKDAY_OFFCYCLE",
    status: "ACTIVE",
    last_updated_at: "2026-08-21T08:00:00Z",
    last_updated_by_event_id: "evt-0004"
  };

  const sampleB = {
    employee_id: "emp_2002",
    legal_first_name: "Sanjai",
    legal_last_name: "Iyer",
    personal_email: "sanjai.demo@example.com",
    start_date: "2026-09-08",
    address: {
      line1: "12 Whitefield Main Rd",
      city: "Bengaluru",
      state: "KA",
      postal_code: "560066",
      country: "IN"
    },
    position_title: "Contractor - Data",
    department: "Analytics",
    source_system: "WORKDAY_OFFCYCLE",
    status: "ACTIVE",
    last_updated_at: "2026-08-22T08:00:00Z",
    last_updated_by_event_id: "evt-0005"
  };

  aiRecA.value = JSON.stringify(sampleA, null, 2);
  aiRecB.value = JSON.stringify(sampleB, null, 2);

  // Set default gauge position
  setAiGauge(0, "Awaiting Evaluation", "Click 'Resolve with Gemini' to execute confidence-gated deduplication.", "waiting");
}

function setAiGauge(confidenceRatio, decision, reasoning, stateType = "success") {
  const pct = Math.round(confidenceRatio * 100);
  aiLabConfidence.textContent = `${pct}%`;

  // Circumference = 2 * PI * 40 = 251.2
  const offset = 251.2 * (1 - confidenceRatio);
  aiGaugeCircle.style.strokeDashoffset = offset;

  if (stateType === "same_person") {
    aiGaugeCircle.setAttribute("stroke", "#4edea3");
    aiDecisionBox.style.background = "rgba(0,125,85,0.2)";
    aiDecisionBox.style.borderColor = "var(--tertiary-container)";
    aiDecisionIcon.style.color = "var(--tertiary)";
    aiDecisionIcon.textContent = "check_circle";
    aiLabDecisionBadge.style.color = "var(--tertiary)";
    aiLabDecisionBadge.textContent = "SAME_PERSON (Auto-Merge)";
  } else if (stateType === "different_person") {
    aiGaugeCircle.setAttribute("stroke", "#ffb59d");
    aiDecisionBox.style.background = "rgba(194,65,12,0.2)";
    aiDecisionBox.style.borderColor = "var(--primary-container)";
    aiDecisionIcon.style.color = "var(--primary)";
    aiDecisionIcon.textContent = "swap_horiz";
    aiLabDecisionBadge.style.color = "var(--primary)";
    aiLabDecisionBadge.textContent = "DIFFERENT_PERSON (Distinct Records)";
  } else {
    aiGaugeCircle.setAttribute("stroke", "#ffb4ab");
    aiDecisionBox.style.background = "rgba(147,0,10,0.2)";
    aiDecisionBox.style.borderColor = "var(--error-container)";
    aiDecisionIcon.style.color = "var(--error)";
    aiDecisionIcon.textContent = "warning";
    aiLabDecisionBadge.style.color = "var(--error)";
    aiLabDecisionBadge.textContent = stateType === "waiting" ? "AWAITING EVALUATION" : "NEEDS_HUMAN_REVIEW (Gated)";
  }

  aiLabReasoning.textContent = reasoning;
}

async function handleRunAiLab() {
  let recA, recB;
  try {
    recA = JSON.parse(aiRecA.value);
    recB = JSON.parse(aiRecB.value);
  } catch (e) {
    alert("Invalid JSON in Record A or Record B: " + e.message);
    return;
  }

  btnRunAiLab.disabled = true;
  btnRunAiLab.innerHTML = '<span>Evaluating with Gemini...</span>';

  try {
    const res = await fetch(`${API_BASE}/api/resolve-conflict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ record_a: recA, record_b: recB, context: "Interactive AI Lab test" }),
    });
    const resolution = await res.json();

    setAiGauge(
      resolution.confidence || 0,
      resolution.decision,
      resolution.reasoning || "No explanation provided.",
      resolution.decision
    );
  } catch (e) {
    alert("Gemini AI resolution error: " + e);
  } finally {
    btnRunAiLab.disabled = false;
    btnRunAiLab.innerHTML = `
      <span>Resolve with Gemini</span>
      <span class="material-symbols-outlined" style="font-size:16px;">auto_awesome</span>
    `;
  }
}

// Load Systems Health
function loadSystems() {
  const systems = [
    { name: "Ashby", role: "ATS (Applicant Tracking)", writes: "Inbound Events", status: "ONLINE", fields: "Pre-hire name, address, start date" },
    { name: "Workday", role: "HRIS System of Record", writes: "Full Employee Record", status: "ONLINE", fields: "Legal identity, worker ID, hierarchy" },
    { name: "Okta", role: "Identity Provider & SSO", writes: "Identity & Work Email", status: "ONLINE", fields: "Work email, SSO groups, status" },
    { name: "Lumos", role: "Access Governance", writes: "Role Entitlements", status: "ONLINE", fields: "App assignments, access gates" },
    { name: "expoIT", role: "Hardware Logistics", writes: "Shipment Orders", status: "ONLINE", fields: "Hardware specs, shipping address" },
    { name: "Cohort Tracker", role: "Onboarding Tracker", writes: "Checklists & Milestones", status: "ONLINE", fields: "Onboarding readiness milestones" },
  ];

  const grid = document.getElementById("systems-grid");
  grid.innerHTML = systems.map(s => `
    <div class="glass-panel" style="padding:18px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <h3 style="font-family:var(--font-headline); font-size:1.05rem;">${s.name}</h3>
        <span class="badge badge-success">${s.status}</span>
      </div>
      <div style="font-size:0.75rem; color:var(--text-muted); font-family:var(--font-mono);">${s.role}</div>
      <div style="font-size:0.8rem; color:var(--text-variant); margin-top:10px;">
        <div><strong>Writes:</strong> ${s.writes}</div>
        <div style="margin-top:2px;"><strong>Fields:</strong> ${s.fields}</div>
      </div>
    </div>
  `).join("");
}
