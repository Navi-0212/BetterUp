// BetterUp Sync Engine Frontend Application

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

// AI Lab Elements
const aiRecA = document.getElementById("ai-rec-a");
const aiRecB = document.getElementById("ai-rec-b");
const btnRunAiLab = document.getElementById("btn-run-ai-lab");
const aiLabResultBox = document.getElementById("ai-lab-result-box");
const aiLabDecisionBadge = document.getElementById("ai-lab-decision-badge");
const aiLabConfidence = document.getElementById("ai-lab-confidence");
const aiLabProgressFill = document.getElementById("ai-lab-progress-fill");
const aiLabReasoning = document.getElementById("ai-lab-reasoning");

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

// Tabs Switching
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

      // Reload tab-specific data
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
}

// Load Global Data
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
      statAttention.classList.remove("text-success");
      statAttention.classList.add("text-danger");
    } else {
      badgeAttention.style.display = "none";
      statAttention.classList.add("text-success");
      statAttention.classList.remove("text-danger");
    }

    const llmStatus = document.getElementById("llm-status-text");
    if (data.has_api_key) {
      llmStatus.textContent = `Active (${data.llm_model})`;
    } else {
      llmStatus.textContent = "Mock / Test Mode";
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
    alert("Invalid JSON in editor: " + e.message);
    return;
  }

  isProcessing = true;
  btnProcess.disabled = true;
  execStatusBadge.className = "badge badge-neutral";
  execStatusBadge.textContent = "Executing...";

  // Animate Pipeline visualizer
  resetPipelineVisualizer();
  await animateNode(nodeNormalize, 200);
  await animateNode(nodePrefilter, 250);
  await animateNode(nodeValidate, 200);
  await animateNode(nodeFanout, 250);

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
      <div class="result-section">
        <span class="badge badge-danger">Processing Error</span>
        <p class="mt-4" style="color:var(--accent-rose); font-family:var(--font-mono);">${e.message}</p>
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
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
      <h4>Execution Output (${dryRun ? "DRY RUN SIMULATION" : "LIVE STATE UPDATE"})</h4>
      ${statusBadge}
    </div>
    
    <div class="result-section">
      <div class="result-title">Event Information</div>
      <div style="font-size:0.85rem; color:var(--text-secondary);">
        Event ID: <strong style="color:#FFF;">${result.event_id}</strong> | Employee ID: <strong style="color:#FFF;">${result.employee_id}</strong>
      </div>
    </div>

    <div class="result-section">
      <div class="result-title">Fields Propagated (${result.fields_propagated.length})</div>
      <div class="tag-list">
        ${result.fields_propagated.length > 0 
          ? result.fields_propagated.map(f => `<span class="badge badge-success">✓ ${f}</span>`).join("")
          : '<span class="badge badge-neutral">None</span>'}
      </div>
    </div>

    <div class="result-section">
      <div class="result-title">Fields Rejected by Inline Validation (${result.fields_rejected.length})</div>
      <div class="tag-list">
        ${result.fields_rejected.length > 0 
          ? result.fields_rejected.map(f => `<span class="badge badge-danger">✗ ${f}</span>`).join("")
          : '<span class="badge badge-neutral">None (All fields valid)</span>'}
      </div>
    </div>

    <div class="result-section">
      <div class="result-title">Downstream Systems Written (${result.systems_written.length})</div>
      <div class="tag-list">
        ${result.systems_written.length > 0
          ? result.systems_written.map(s => `<span class="badge badge-ashby">${s}</span>`).join("")
          : '<span class="badge badge-neutral">None</span>'}
      </div>
    </div>
  `;

  if (result.systems_failed && result.systems_failed.length > 0) {
    html += `
      <div class="result-section">
        <div class="result-title" style="color:var(--accent-rose);">Systems Failed (${result.systems_failed.length})</div>
        <div class="tag-list">
          ${result.systems_failed.map(s => `<span class="badge badge-danger">${s} (Max Retries Reached)</span>`).join("")}
        </div>
      </div>
    `;
  }

  if (result.conflict_resolution) {
    html += `
      <div class="result-section" style="background:rgba(99,102,241,0.08); padding:12px; border-radius:8px; border:1px solid rgba(99,102,241,0.2);">
        <div class="result-title" style="color:var(--accent-cyan);">Gemini Identity Conflict Resolution</div>
        <div style="font-size:0.85rem;">
          Decision: <strong>${result.conflict_resolution.decision}</strong> | Confidence: <strong>${(result.conflict_resolution.confidence * 100).toFixed(0)}%</strong>
          <p style="margin-top:4px; color:var(--text-secondary);">${result.conflict_resolution.reasoning}</p>
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
      employeesTbody.innerHTML = '<tr><td colspan="7" class="text-center">No employee records in store. Click "Seed Demo" to load sample records.</td></tr>';
      return;
    }

    employeesTbody.innerHTML = employees.map(emp => `
      <tr>
        <td class="mono"><strong>${emp.employee_id}</strong></td>
        <td>${emp.legal_first_name} ${emp.legal_last_name}</td>
        <td>
          <div>${emp.position_title || "N/A"}</div>
          <span style="font-size:0.75rem; color:var(--text-muted);">${emp.department || "General"}</span>
        </td>
        <td>${emp.start_date}</td>
        <td class="mono">${emp.work_email || '<span style="color:var(--text-muted);">Unassigned (Pre-Hire)</span>'}</td>
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

// Load Ledger & Needs Attention
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
      ledgerTbody.innerHTML = '<tr><td colspan="7" class="text-center">Ledger is empty. No downstream writes have been dispatched yet.</td></tr>';
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
        <td>${e.attempt_count} / 3</td>
        <td class="mono">${e.system_ref_id || '—'}</td>
        <td style="font-size:0.75rem; color:var(--text-muted);">${e.updated_at ? new Date(e.updated_at).toLocaleTimeString() : '—'}</td>
        <td style="color:var(--accent-rose); font-size:0.8rem;">${e.error_message || '<span style="color:var(--text-muted);">None</span>'}</td>
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
      auditFeedList.innerHTML = '<div class="text-center p-4">No audit entries recorded yet.</div>';
      return;
    }

    auditFeedList.innerHTML = logs.map(l => {
      let badgeClass = "badge-neutral";
      if (l.action === "FIELD_CHANGE_PROPAGATED") badgeClass = "badge-success";
      if (l.action === "VALIDATION_REJECTED") badgeClass = "badge-danger";
      if (l.action === "CLAUDE_CONFLICT_RESOLVED") badgeClass = "badge-ashby";
      if (l.action === "NEEDS_HUMAN_REVIEW") badgeClass = "badge-warning";

      return `
        <div class="audit-entry-card">
          <div class="audit-header">
            <span class="badge ${badgeClass}">${l.action}</span>
            <span style="font-size:0.75rem; color:var(--text-muted);">${new Date(l.timestamp).toLocaleString()}</span>
          </div>
          <div class="audit-meta">
            <span>Event: <strong>${l.event_id}</strong></span>
            <span>Employee: <strong>${l.employee_id}</strong></span>
            ${l.target_system ? `<span>Target: <strong>${l.target_system}</strong></span>` : ''}
            <span>Trigger: <code class="mono">${l.triggered_by}</code></span>
          </div>
          ${(l.before_state || l.after_state) ? `
            <div class="audit-diff">
              ${l.before_state ? `<div><span style="color:var(--accent-rose);">- Before:</span> ${JSON.stringify(l.before_state)}</div>` : ''}
              ${l.after_state ? `<div><span style="color:var(--accent-emerald);">+ After:</span> ${JSON.stringify(l.after_state)}</div>` : ''}
            </div>
          ` : ''}
        </div>
      `;
    }).join("");
  } catch (e) {
    console.error("Load audit error:", e);
  }
}

// AI Lab Defaults & Handler
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

    aiLabResultBox.style.display = "block";
    const confPct = Math.round((resolution.confidence || 0) * 100);
    aiLabConfidence.textContent = `${confPct}%`;
    aiLabProgressFill.style.width = `${confPct}%`;

    if (resolution.decision === "same_person") {
      aiLabDecisionBadge.className = "badge badge-success";
      aiLabDecisionBadge.textContent = "SAME PERSON (Auto-Resolve)";
    } else if (resolution.decision === "different_person") {
      aiLabDecisionBadge.className = "badge badge-ashby";
      aiLabDecisionBadge.textContent = "DIFFERENT PERSON (Independent Hires)";
    } else {
      aiLabDecisionBadge.className = "badge badge-warning";
      aiLabDecisionBadge.textContent = "NEEDS HUMAN REVIEW (Gated)";
    }

    aiLabReasoning.textContent = resolution.reasoning || "No explanation provided.";
  } catch (e) {
    alert("Gemini AI resolution error: " + e);
  } finally {
    btnRunAiLab.disabled = false;
    btnRunAiLab.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
      <span>Resolve Conflict with Gemini</span>
    `;
  }
}

// Load Systems Health
function loadSystems() {
  const systems = [
    { name: "Ashby", role: "ATS (Applicant Tracking)", writes: "Inbound Events", icon: "📄", status: "ONLINE", fields: "Pre-hire name, address, start date" },
    { name: "Workday", role: "HRIS System of Record", writes: "Full Employee Record", icon: "🏢", status: "ONLINE", fields: "Legal identity, worker ID, hierarchy" },
    { name: "Okta", role: "Identity Provider & SSO", writes: "Identity & Work Email", icon: "🔑", status: "ONLINE", fields: "Work email, SSO groups, status" },
    { name: "Lumos", role: "Access Governance", writes: "Role Entitlements", icon: "🛡️", status: "ONLINE", fields: "App assignments, access gates" },
    { name: "expoIT", role: "Hardware Logistics", writes: "Shipment Orders", icon: "💻", status: "ONLINE", fields: "Hardware specs, shipping address" },
    { name: "Cohort Tracker", role: "Onboarding Tracker", writes: "Checklists & Milestones", icon: "📋", status: "ONLINE", fields: "Onboarding readiness milestones" },
  ];

  const grid = document.getElementById("systems-grid");
  grid.innerHTML = systems.map(s => `
    <div class="system-card">
      <div class="system-card-header">
        <div>
          <div class="system-name">${s.icon} ${s.name}</div>
          <div class="system-role">${s.role}</div>
        </div>
        <span class="badge badge-success">${s.status}</span>
      </div>
      <div style="font-size:0.82rem; color:var(--text-secondary); margin-top:10px;">
        <div><strong>Writes:</strong> ${s.writes}</div>
        <div style="margin-top:4px;"><strong>Fields:</strong> ${s.fields}</div>
      </div>
    </div>
  `).join("");
}
