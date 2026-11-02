/*
  frontend/src/dashboard.ts
  ===========================
  The project dashboard (static/dashboard.html). One page, three audiences:

    customer  - sees their own project(s): a stage tracker, then a dropdown
                per stage with the actions for it (request a call, pick a
                site-visit date/time, upload approval documents).
    engineer  - sees projects assigned to them, with controls to confirm /
                complete appointments, review documents, set the start date.
    admin     - sees every project, can also assign engineers and manage
                user roles.

  The server enforces all of this (see app/auth.py + app/projects.py); the
  checks below only decide what to SHOW. Hiding a button is never security.
*/
import { api, escapeHtml, fetchCurrentUser } from "./shared.js";
import { initChat } from "./chat.js";
// --- State ----------------------------------------------------------------
let user;
let chat = null;
let projects = [];
let detail = null;
let engineers = [];
let adminUsers = [];
let roles = [];
let view = "projects";
const openStages = new Set();
const root = document.getElementById("app");
const toast = document.getElementById("toast");
const can = (permission) => user.permissions.includes(permission);
const isStaff = () => can("appointment:manage");
// --- Formatting -----------------------------------------------------------
const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const formatDateTime = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const formatDate = (iso) => new Date(iso + "T00:00:00").toLocaleDateString(undefined, { dateStyle: "long" });
/** Value for a <input type="datetime-local"> from a Date, in LOCAL time. */
function toLocalInputValue(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
function showToast(message, isError = false) {
    toast.textContent = message;
    toast.className =
        "fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl px-5 py-3 text-sm font-semibold shadow-[0_16px_40px_rgba(12,26,22,0.3)] " +
            (isError ? "bg-red-700 text-white" : "bg-dark text-gold-light");
    toast.hidden = false;
    window.setTimeout(() => (toast.hidden = true), 3500);
}
// --- Small view helpers -----------------------------------------------------
const STATUS_STYLE = {
    completed: "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200",
    in_progress: "bg-accent-light text-accent-dark ring-1 ring-accent/30",
    pending: "bg-stone-100 text-ink-muted ring-1 ring-border",
};
const STATUS_LABEL = {
    completed: "Completed",
    in_progress: "In progress",
    pending: "Not started",
};
const APPT_STYLE = {
    requested: "bg-amber-100 text-amber-800",
    confirmed: "bg-blue-100 text-blue-800",
    completed: "bg-green-100 text-green-800",
    cancelled: "bg-stone-100 text-ink-muted",
    change_requested: "bg-purple-100 text-purple-800",
    pending: "bg-amber-100 text-amber-800",
    approved: "bg-green-100 text-green-800",
    rejected: "bg-red-100 text-red-800",
};
const APPT_LABEL = {
    requested: "Requested",
    confirmed: "Confirmed",
    change_requested: "Time change requested",
    completed: "Completed",
    cancelled: "Cancelled",
};
const badge = (text, style) => `<span class="inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${style}">${escapeHtml(text)}</span>`;
const BTN = "rounded-xl px-4 py-2.5 text-sm font-semibold transition disabled:opacity-60";
const BTN_PRIMARY = `${BTN} bg-dark text-white shadow-[0_8px_20px_rgba(12,26,22,0.18)] hover:-translate-y-0.5 hover:bg-dark-2`;
const BTN_SECONDARY = `${BTN} border border-border bg-surface text-ink hover:border-accent hover:text-accent-dark`;
const INPUT = "rounded-xl border border-border bg-bg px-3.5 py-2.5 text-sm focus:outline-2 focus:outline-accent";
const CARD = "rounded-3xl border border-border bg-surface shadow-[0_20px_50px_rgba(12,26,22,0.06)]";
const initials = (name) => name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((part) => part[0].toUpperCase()).join("") || "?";
/** One small line icon per stage, keyed by stage.key. */
const STAGE_ICON = {
    quote: `<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>`,
    discussion: `<path d="M21 11.5a8.4 8.4 0 0 1-12.3 7.4L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5Z"/>`,
    site_visit: `<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11Z"/><circle cx="12" cy="10" r="2.5"/>`,
    documents: `<path d="M4 4h6l2 2h8v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><path d="m9 13 2 2 4-4"/>`,
    work_start: `<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9"/>`,
};
const icon = (paths, size = "h-5 w-5") => `<svg class="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
// --- Stage tracker (the "graph") -------------------------------------------
function renderTracker(stages, progress) {
    const steps = stages
        .map((stage, index) => {
        const circle = stage.status === "completed"
            ? "border-dark bg-dark text-gold"
            : stage.status === "in_progress"
                ? "border-accent bg-accent-light text-accent-dark ring-4 ring-accent/15"
                : "border-border bg-surface text-ink-muted";
        const line = index === 0
            ? ""
            : `<span class="absolute top-5 right-1/2 h-0.5 w-full ${stages[index - 1].status === "completed" ? "bg-accent" : "bg-border"}" aria-hidden="true"></span>`;
        const mark = stage.status === "completed"
            ? `<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5L20 7"/></svg>`
            : icon(STAGE_ICON[stage.key] ?? "", "h-4 w-4");
        return `<li class="relative flex flex-1 flex-col items-center gap-2 text-center">
                ${line}
                <span class="relative z-10 flex h-10 w-10 items-center justify-center rounded-full border-2 text-sm font-bold ${circle}">${mark}</span>
                <span class="text-xs font-bold leading-tight">${escapeHtml(stage.label)}</span>
                <span class="text-[0.7rem] ${stage.status === "in_progress" ? "font-semibold text-accent-dark" : "text-ink-muted"}">${STATUS_LABEL[stage.status]}</span>
            </li>`;
    })
        .join("");
    const percent = Math.round((progress.done / progress.total) * 100);
    return `<div class="${CARD} p-5 sm:p-7">
        <div class="mb-4 flex flex-wrap items-end justify-between gap-2">
            <div><p class="m-0 text-[0.7rem] font-bold uppercase tracking-[0.18em] text-accent">Project progress</p>
                <strong class="text-2xl font-extrabold tracking-tight">${percent}%<span class="ml-2 text-sm font-medium text-ink-muted">complete</span></strong></div>
            <span class="text-sm text-ink-muted">${progress.done} of ${progress.total} stages done</span>
        </div>
        <div class="mb-7 h-2.5 overflow-hidden rounded-full bg-bg ring-1 ring-border" role="progressbar" aria-valuenow="${percent}" aria-valuemin="0" aria-valuemax="100">
            <div class="bg-gold-gradient h-full rounded-full transition-all" style="width:${percent}%"></div>
        </div>
        <div class="overflow-x-auto"><ol class="m-0 flex min-w-[520px] list-none gap-1 p-0">${steps}</ol></div>
    </div>`;
}
// --- Stage sections (the dropdowns) -----------------------------------------
function section(stage, body) {
    const tone = stage.status === "completed" ? "bg-dark text-gold" : stage.status === "in_progress" ? "bg-accent-light text-accent-dark" : "bg-bg text-ink-muted";
    return `<details data-stage="${stage.key}" ${openStages.has(stage.key) ? "open" : ""} class="group rounded-2xl border border-border bg-surface shadow-[0_6px_20px_rgba(12,26,22,0.04)] transition open:shadow-[0_16px_40px_rgba(12,26,22,0.08)]">
        <summary class="flex cursor-pointer list-none items-center justify-between gap-3 p-4 font-bold sm:px-5 [&::-webkit-details-marker]:hidden">
            <span class="flex items-center gap-3"><span class="flex h-10 w-10 items-center justify-center rounded-xl ${tone}">${icon(STAGE_ICON[stage.key] ?? "")}</span>${escapeHtml(stage.label)}</span>
            <span class="flex items-center gap-3">${badge(STATUS_LABEL[stage.status], STATUS_STYLE[stage.status])}
                <svg class="h-4 w-4 text-ink-muted transition group-open:rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
            </span>
        </summary>
        <div class="border-t border-border p-4 text-sm sm:px-5">${body}</div>
    </details>`;
}
function renderQuote(q) {
    const rows = [
        ["Location", q.location],
        ["Area per floor", `${q.area_sqft_per_floor} sq ft`],
        ["Floors", String(q.floors)],
        ["Total built-up area", `${q.total_built_up_area} sq ft`],
        ["Rate", `${money.format(q.rate_per_sqft)} / sq ft`],
        ["Car parking", q.with_car_parking ? `Included (${money.format(q.car_parking_cost)})` : "Not included"],
        ["Construction cost", money.format(q.base_cost)],
        ["Materials (approx. 60%)", money.format(q.material_cost)],
        ["Labour (approx. 40%)", money.format(q.labour_cost)],
        ["Estimated timeline", `${q.estimated_months} months`],
    ];
    const body = rows
        .map(([k, v]) => `<tr><td class="py-1.5 pr-4 text-ink-muted">${k}</td><td class="py-1.5 font-medium">${escapeHtml(v)}</td></tr>`)
        .join("");
    return `<table class="w-full"><tbody>${body}
        <tr class="border-t border-border"><td class="pt-3 pr-4 font-bold">Total estimate</td><td class="pt-3 text-lg font-extrabold text-accent-dark">${money.format(q.total_cost)}</td></tr>
    </tbody></table>
    <p class="mb-0 mt-3 text-xs text-ink-muted">This is an estimate from our chat assistant; your engineer will confirm the final figures after the site visit.</p>`;
}
/** The admin's "please change the time" request, with the client's answers. */
function changeRequestBlock(a) {
    if (a.status !== "change_requested" || !a.proposed_for) {
        return "";
    }
    const respond = !isStaff()
        ? `<div class="mt-3 flex flex-wrap items-center gap-2">
            <button data-action="appt-accept-change" data-id="${a.id}" class="${BTN_PRIMARY}">Accept ${formatDateTime(a.proposed_for)}</button>
        </div>
        <form data-form="appt-counter" data-id="${a.id}" class="mt-2 flex flex-wrap items-center gap-2">
            <input name="when" type="datetime-local" required min="${toLocalInputValue(new Date())}" class="${INPUT}" aria-label="Another time" />
            <button type="submit" class="${BTN_SECONDARY}">Suggest another time</button>
        </form>`
        : "";
    return `<div class="mt-2 rounded-lg border border-purple-200 bg-purple-50 p-3 text-sm">
        <strong>We'd like to move this to ${formatDateTime(a.proposed_for)}.</strong>
        ${a.admin_note ? `<p class="mb-0 mt-1">&ldquo;${escapeHtml(a.admin_note)}&rdquo;</p>` : ""}
        ${respond}
    </div>`;
}
/** Top-of-page updates for the client: things that need an answer, and confirmations. */
function renderUpdates(project) {
    if (isStaff()) {
        return "";
    }
    const notes = [];
    for (const a of project.appointments) {
        const noun = a.kind === "discussion" ? "call with our engineer" : "site visit";
        if (a.status === "change_requested" && a.proposed_for) {
            notes.push(`<div class="rounded-2xl border border-purple-200 bg-purple-50 p-4 text-sm shadow-sm"><strong>Action needed:</strong> we'd like to move your ${noun} to <strong>${formatDateTime(a.proposed_for)}</strong>. Open the &ldquo;${a.kind === "discussion" ? "Discussion with engineer" : "Site visit"}&rdquo; section below to accept or suggest another time.</div>`);
        }
        else if (a.status === "confirmed") {
            notes.push(`<div class="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm shadow-sm"><strong>Confirmed:</strong> your ${noun} is on <strong>${formatDateTime(a.scheduled_for)}</strong>.</div>`);
        }
    }
    return notes.length ? `<div class="mb-4 flex flex-col gap-2">${notes.join("")}</div>` : "";
}
function renderAppointments(kind, project) {
    const mine = project.appointments.filter((a) => a.kind === kind);
    const live = mine.find((a) => a.status === "requested" || a.status === "confirmed" || a.status === "change_requested");
    const noun = kind === "discussion" ? "call" : "site visit";
    const list = mine
        .map((a) => {
        const staffButtons = isStaff() && (a.status === "requested" || a.status === "confirmed" || a.status === "change_requested")
            ? `<div class="mt-2 flex flex-wrap items-center gap-2">
                    ${a.status === "requested" ? `<button data-action="appt-status" data-id="${a.id}" data-status="confirmed" class="${BTN_PRIMARY}">Confirm</button>` : ""}
                    ${a.status === "confirmed" ? `<button data-action="appt-status" data-id="${a.id}" data-status="completed" class="${BTN_PRIMARY}">Mark completed</button>` : ""}
                    <input type="datetime-local" data-resched="${a.id}" min="${toLocalInputValue(new Date())}" class="${INPUT}" aria-label="New time" />
                    <button data-action="appt-resched" data-id="${a.id}" class="${BTN_SECONDARY}">Reschedule</button>
                    <button data-action="appt-status" data-id="${a.id}" data-status="cancelled" class="${BTN_SECONDARY}">Cancel</button>
                </div>`
            : "";
        const customerCancel = !isStaff() && (a.status === "requested" || a.status === "confirmed" || a.status === "change_requested")
            ? `<button data-action="appt-status" data-id="${a.id}" data-status="cancelled" class="${BTN_SECONDARY} mt-2">Cancel ${noun}</button>`
            : "";
        return `<li class="rounded-xl border border-border bg-bg p-3.5">
                <div class="flex flex-wrap items-center justify-between gap-2">
                    <strong>${formatDateTime(a.scheduled_for)}</strong>${badge(APPT_LABEL[a.status], APPT_STYLE[a.status])}
                </div>
                ${a.notes ? `<p class="mb-0 mt-1 text-ink-muted">${escapeHtml(a.notes)}</p>` : ""}
                ${a.status === "requested" ? `<p class="mb-0 mt-1 text-xs text-ink-muted">Waiting for our engineer to confirm.</p>` : ""}
                ${changeRequestBlock(a)}
                ${staffButtons}${customerCancel}
            </li>`;
    })
        .join("");
    const form = can("appointment:request") && !live
        ? `<form data-form="appt" data-kind="${kind}" class="mt-3 grid gap-3 sm:grid-cols-2">
                <label class="flex flex-col gap-1 text-xs font-semibold">Preferred date &amp; time
                    <input name="when" type="datetime-local" required min="${toLocalInputValue(new Date())}" class="${INPUT} font-normal" />
                </label>
                <label class="flex flex-col gap-1 text-xs font-semibold">Notes (optional)
                    <input name="notes" type="text" maxlength="500" placeholder="${kind === "discussion" ? "What would you like to discuss?" : "Gate / landmark / who will be there"}" class="${INPUT} font-normal" />
                </label>
                <div class="sm:col-span-2"><button type="submit" class="${BTN_PRIMARY}">${kind === "discussion" ? "Request a call" : "Schedule site visit"}</button></div>
            </form>`
        : "";
    const intro = kind === "discussion"
        ? "Talk through your plans, budget and materials with one of our engineers."
        : "An engineer visits your plot to measure, check the soil and confirm the quote.";
    return `<p class="mt-0 text-ink-muted">${intro}</p>
        ${list ? `<ul class="m-0 flex list-none flex-col gap-2 p-0">${list}</ul>` : `<p class="text-ink-muted">Nothing scheduled yet.</p>`}
        ${form}`;
}
function renderDocuments(project) {
    const rows = project.documents
        .map((slot) => {
        const up = slot.upload;
        const canUpload = can("document:upload") && up?.status !== "approved";
        const reviewButtons = can("document:review") && up
            ? `<button data-action="doc-review" data-id="${up.id}" data-status="approved" class="${BTN_PRIMARY}" ${up.status === "approved" ? "disabled" : ""}>Approve</button>
                       <button data-action="doc-review" data-id="${up.id}" data-status="rejected" class="${BTN_SECONDARY}">Reject</button>`
            : "";
        return `<li class="rounded-xl border border-border bg-bg p-3.5">
                <div class="flex flex-wrap items-center justify-between gap-2">
                    <strong>${escapeHtml(slot.label)}</strong>
                    ${up ? badge(up.status[0].toUpperCase() + up.status.slice(1), APPT_STYLE[up.status]) : badge("Required", "bg-stone-100 text-ink-muted")}
                </div>
                ${up ? `<p class="mb-0 mt-1"><a class="text-accent-dark underline" href="/api/documents/${up.id}/download">${escapeHtml(up.original_name)}</a> <span class="text-xs text-ink-muted">(${Math.max(1, Math.round(up.size_bytes / 1024))} KB)</span></p>` : ""}
                ${up?.review_note ? `<p class="mb-0 mt-1 text-red-800">Engineer's note: ${escapeHtml(up.review_note)}</p>` : ""}
                <div class="mt-2 flex flex-wrap items-center gap-2">
                    ${canUpload ? `<input type="file" accept=".pdf,.png,.jpg,.jpeg" data-file="${slot.doc_type}" class="max-w-[14rem] text-xs" />
                    <button data-action="doc-upload" data-type="${slot.doc_type}" class="${BTN_PRIMARY}">${up ? "Replace" : "Upload"}</button>` : ""}
                    ${reviewButtons}
                </div>
            </li>`;
    })
        .join("");
    return `<p class="mt-0 text-ink-muted">Upload clear PDF, PNG or JPG files (max 10 MB each). Your engineer reviews each one; the stage completes when all are approved.</p>
        <ul class="m-0 flex list-none flex-col gap-2 p-0">${rows}</ul>`;
}
function renderStart(project) {
    const date = project.work_start_date;
    const message = date
        ? `<p class="mt-0">Work ${new Date(date + "T00:00:00") <= new Date() ? "started" : "is scheduled to start"} on <strong>${formatDate(date)}</strong>.</p>`
        : `<p class="mt-0 text-ink-muted">Your engineer will set the start date once the site visit and documents are done.</p>`;
    const form = can("project:schedule_start")
        ? `<form data-form="start" class="flex flex-wrap items-center gap-2">
            <input name="date" type="date" value="${date ?? ""}" class="${INPUT}" aria-label="Work start date" />
            <button type="submit" class="${BTN_PRIMARY}">Save start date</button>
            ${date ? `<button type="button" data-action="clear-start" class="${BTN_SECONDARY}">Clear</button>` : ""}
        </form>`
        : "";
    return message + form;
}
function renderProject(project) {
    const stage = (key) => project.stages.find((s) => s.key === key);
    const assign = can("project:assign")
        ? `<label class="flex items-center gap-2 text-sm">Engineer
            <select data-select="engineer" class="${INPUT}">
                <option value="">Unassigned</option>
                ${engineers.map((e) => `<option value="${e.id}" ${e.name === project.engineer_name ? "selected" : ""}>${escapeHtml(e.name)}</option>`).join("")}
            </select></label>`
        : `<div class="flex items-center gap-3 rounded-2xl border border-border bg-bg px-3.5 py-2.5">
            <span class="flex h-9 w-9 items-center justify-center rounded-full bg-gold-gradient text-xs font-bold text-dark">${project.engineer_name ? initials(project.engineer_name) : "?"}</span>
            <span class="leading-tight"><span class="block text-[0.7rem] font-semibold uppercase tracking-wide text-ink-muted">Your engineer</span><strong class="text-sm">${escapeHtml(project.engineer_name ?? "To be assigned")}</strong></span>
        </div>`;
    const who = isStaff() ? `<span class="text-sm text-ink-muted">${escapeHtml(project.customer_name)} &middot; ${escapeHtml(project.customer_email)}</span>` : "";
    const q = project.quote;
    const tile = (label, value, paths) => `<div class="flex items-center gap-3 rounded-2xl border border-border bg-bg p-3.5">
            <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-dark text-gold">${icon(paths)}</span>
            <div class="min-w-0"><p class="m-0 text-[0.7rem] font-semibold uppercase tracking-wide text-ink-muted">${label}</p><p class="m-0 truncate font-bold">${value}</p></div>
        </div>`;
    const start = project.work_start_date ? formatDate(project.work_start_date) : "To be scheduled";
    return `<div class="${CARD} mb-5 overflow-hidden">
            <div class="flex flex-wrap items-start justify-between gap-4 p-5 sm:p-7">
                <div>
                    <span class="inline-flex items-center gap-2 rounded-full bg-accent-light px-3 py-1 text-xs font-bold text-accent-dark"><span class="h-1.5 w-1.5 rounded-full bg-accent"></span>${escapeHtml(project.current_stage)}</span>
                    <h2 class="mb-1 mt-3 text-[1.5rem] font-extrabold tracking-tight">Project #${project.id} &middot; ${escapeHtml(project.location ?? "")}</h2>${who}
                </div>
                ${assign}
            </div>
            <div class="grid gap-3 border-t border-border p-5 sm:grid-cols-2 sm:p-7 lg:grid-cols-4">
                ${tile("Estimate", money.format(q.total_cost), `<path d="M6 4h12M6 9h12M9 4c4 0 6 2 6 5s-2 5-6 5H6l8 7"/>`)}
                ${tile("Built-up area", `${q.total_built_up_area} sq ft`, `<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 12h16M12 4v16"/>`)}
                ${tile("Timeline", `${q.estimated_months} months`, `<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>`)}
                ${tile("Work start", start, `<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>`)}
            </div>
        </div>
        ${renderUpdates(project)}
        ${renderTracker(project.stages, project.progress)}
        <div class="mt-5 flex flex-col gap-3">
            ${section(stage("quote"), renderQuote(project.quote))}
            ${section(stage("discussion"), renderAppointments("discussion", project))}
            ${section(stage("site_visit"), renderAppointments("site_visit", project))}
            ${section(stage("documents"), renderDocuments(project))}
            ${section(stage("work_start"), renderStart(project))}
        </div>`;
}
function renderProjectList() {
    if (projects.length === 0) {
        return isStaff()
            ? `<p class="${CARD} p-6 text-ink-muted">No projects ${can("project:view_all") ? "yet" : "assigned to you yet"}.</p>`
            : `<div class="${CARD} px-6 py-14 text-center">
                <span class="mx-auto mb-5 flex h-20 w-20 items-center justify-center rounded-3xl bg-dark"><img src="/static/images/logo-mark.svg" alt="" class="h-10 w-auto" /></span>
                <h2 class="mt-0 text-xl font-extrabold">No projects yet</h2>
                <p class="mx-auto max-w-sm text-ink-muted">Chat with our assistant to get a quote &mdash; it will appear here automatically.</p>
                <button type="button" data-action="open-chat" class="${BTN_PRIMARY} mt-2">Get a free quote &rarr;</button></div>`;
    }
    const items = projects
        .map((p) => `<button data-action="select-project" data-id="${p.id}" class="w-full rounded-2xl border p-3.5 text-left transition ${detail?.id === p.id ? "border-dark bg-dark text-white shadow-[0_12px_30px_rgba(12,26,22,0.2)]" : "border-border bg-surface hover:border-accent"}">
                <strong class="block text-sm">#${p.id} &middot; ${escapeHtml(p.location ?? "")}</strong>
                ${isStaff() ? `<span class="block text-xs opacity-70">${escapeHtml(p.customer_name)}</span>` : ""}
                <span class="mt-2 block h-1.5 overflow-hidden rounded-full ${detail?.id === p.id ? "bg-white/15" : "bg-bg"}"><span class="bg-gold-gradient block h-full rounded-full" style="width:${Math.round((p.progress.done / p.progress.total) * 100)}%"></span></span>
                <span class="mt-1.5 block text-xs opacity-70">${escapeHtml(p.current_stage)} &middot; ${p.progress.done}/${p.progress.total}</span>
            </button>`)
        .join("");
    return `<div class="flex flex-col gap-2">${items}</div>`;
}
function renderUsers() {
    const rows = adminUsers
        .map((u) => `<tr class="border-t border-border"><td class="py-2 pr-3">${escapeHtml(u.name)}</td><td class="py-2 pr-3">${escapeHtml(u.email)}</td>
            <td class="py-2">${u.id === user.id ? badge(u.role, "bg-stone-100 text-ink-muted") : `<select data-select="role" data-id="${u.id}" class="${INPUT}">${roles.map((r) => `<option ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}</select>`}</td></tr>`)
        .join("");
    return `<div class="${CARD} p-5 sm:p-7"><h2 class="mt-0 text-xl font-extrabold">Users &amp; roles</h2>
        <p class="text-sm text-ink-muted">Promote people to <strong>engineer</strong> so you can assign them to projects. <strong>admin</strong> has full access.</p>
        <div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr class="text-xs uppercase tracking-wide text-ink-muted"><th class="pb-2">Name</th><th class="pb-2">Email</th><th class="pb-2">Role</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
}
function render() {
    const tabs = can("user:manage")
        ? `<div class="mb-4 inline-flex gap-1 rounded-2xl border border-border bg-surface p-1 shadow-sm">
            <button data-action="view" data-view="projects" class="${view === "projects" ? BTN_PRIMARY : BTN_SECONDARY}">Projects</button>
            <button data-action="view" data-view="users" class="${view === "users" ? BTN_PRIMARY : BTN_SECONDARY}">Users</button></div>`
        : "";
    if (view === "users") {
        root.innerHTML = tabs + renderUsers();
        return;
    }
    const multi = isStaff() || projects.length > 1;
    root.innerHTML = `${tabs}<div class="${multi ? "grid gap-6 md:grid-cols-[16rem_1fr]" : ""}">
        ${multi ? `<aside>${renderProjectList()}</aside>` : ""}
        <div>${detail ? renderProject(detail) : multi ? "" : renderProjectList()}</div>
    </div>`;
}
// --- Data loading -----------------------------------------------------------
async function loadProjects(selectId) {
    projects = (await api("/api/projects")).projects;
    const id = selectId ?? detail?.id ?? projects[0]?.id;
    detail = id !== undefined && projects.some((p) => p.id === id) ? await api(`/api/projects/${id}`) : null;
    if (can("project:assign")) {
        engineers = (await api("/api/engineers")).engineers;
    }
    render();
}
async function loadUsers() {
    const data = await api("/api/admin/users");
    adminUsers = data.users;
    roles = data.roles;
}
/** Runs a mutation, refreshes the view, reports success or the server's error. */
async function perform(action, success) {
    try {
        await action();
        await loadProjects();
        showToast(success);
    }
    catch (error) {
        showToast(error.message, true);
    }
}
// --- Events (delegated, since we re-render the whole view) ------------------
root.addEventListener("toggle", (event) => {
    const target = event.target;
    if (target instanceof HTMLDetailsElement && target.dataset.stage) {
        target.open ? openStages.add(target.dataset.stage) : openStages.delete(target.dataset.stage);
    }
}, true);
root.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) {
        return;
    }
    const { action, id, status, type } = button.dataset;
    const projectId = detail?.id;
    switch (action) {
        case "open-chat":
            chat?.open();
            break;
        case "view":
            view = button.dataset.view;
            if (view === "users") {
                await loadUsers();
            }
            render();
            break;
        case "select-project":
            detail = await api(`/api/projects/${id}`);
            render();
            break;
        case "appt-status":
            await perform(() => api(`/api/appointments/${id}`, { method: "PATCH", body: { status } }), `Appointment ${status}.`);
            break;
        case "appt-resched": {
            const input = root.querySelector(`[data-resched="${id}"]`);
            if (!input?.value) {
                showToast("Pick a new date and time first.", true);
                break;
            }
            await perform(() => api(`/api/appointments/${id}`, { method: "PATCH", body: { status: "confirmed", scheduled_for: new Date(input.value).toISOString() } }), "Appointment rescheduled and confirmed.");
            break;
        }
        case "appt-accept-change":
            await perform(() => api(`/api/appointments/${id}/respond`, { method: "POST", body: { action: "accept" } }), "New time accepted.");
            break;
        case "doc-upload": {
            const input = root.querySelector(`[data-file="${type}"]`);
            const file = input?.files?.[0];
            if (!file) {
                showToast("Choose a file first.", true);
                break;
            }
            const form = new FormData();
            form.append("doc_type", type);
            form.append("file", file);
            await perform(() => api(`/api/projects/${projectId}/documents`, { method: "POST", form }), "Document uploaded.");
            break;
        }
        case "doc-review": {
            const note = status === "rejected" ? window.prompt("Reason for rejection (shown to the customer):") : "";
            if (note === null) {
                break;
            }
            await perform(() => api(`/api/documents/${id}`, { method: "PATCH", body: { status, review_note: note } }), `Document ${status}.`);
            break;
        }
        case "clear-start":
            await perform(() => api(`/api/projects/${projectId}/start-date`, { method: "PUT", body: { work_start_date: null } }), "Start date cleared.");
            break;
    }
});
root.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const data = new FormData(form);
    const projectId = detail?.id;
    if (form.dataset.form === "appt") {
        const when = new Date(String(data.get("when")));
        await perform(() => api(`/api/projects/${projectId}/appointments`, {
            method: "POST",
            body: { kind: form.dataset.kind, scheduled_for: when.toISOString(), notes: String(data.get("notes") ?? "") },
        }), form.dataset.kind === "discussion" ? "Call requested - we'll confirm the time." : "Site visit requested - we'll confirm the time.");
    }
    else if (form.dataset.form === "appt-counter") {
        const when = new Date(String(data.get("when")));
        await perform(() => api(`/api/appointments/${form.dataset.id}/respond`, { method: "POST", body: { action: "counter", scheduled_for: when.toISOString() } }), "Sent - we'll confirm the new time.");
    }
    else if (form.dataset.form === "start") {
        const date = String(data.get("date"));
        await perform(() => api(`/api/projects/${projectId}/start-date`, { method: "PUT", body: { work_start_date: date || null } }), "Start date saved.");
    }
});
root.addEventListener("change", async (event) => {
    const select = event.target;
    if (select.dataset.select === "engineer") {
        await perform(() => api(`/api/projects/${detail?.id}/engineer`, { method: "PUT", body: { engineer_id: select.value ? Number(select.value) : null } }), "Engineer updated.");
    }
    else if (select.dataset.select === "role") {
        try {
            await api(`/api/admin/users/${select.dataset.id}`, { method: "PATCH", body: { role: select.value } });
            await loadUsers();
            render();
            showToast("Role updated.");
        }
        catch (error) {
            showToast(error.message, true);
            await loadUsers();
            render();
        }
    }
});
// --- Boot ---------------------------------------------------------------------
async function boot() {
    const current = await fetchCurrentUser();
    if (!current) {
        window.location.href = "/";
        return;
    }
    if (current.role === "admin") {
        // Admins work in their own console, not the client dashboard.
        window.location.href = "/admin";
        return;
    }
    user = current;
    document.getElementById("user-name").textContent = `${user.name || user.email}`;
    document.getElementById("user-role").textContent = user.role;
    document.getElementById("user-initial").textContent = initials(user.name || user.email);
    const firstName = (user.name || "").trim().split(/\s+/)[0];
    document.getElementById("greeting-name").textContent = firstName ? `, ${firstName}` : "";
    if (isStaff()) {
        document.getElementById("greeting-sub").textContent =
            "Your assigned projects, appointments and document reviews.";
    }
    document.getElementById("logout")?.addEventListener("click", async () => {
        await api("/api/auth/logout", { method: "POST" });
        window.location.href = "/";
    });
    if (can("appointment:request")) {
        // Customers can chat for a quote right here; a new quote becomes a project.
        chat = initChat({ userId: user.id, onProjectCreated: () => void loadProjects() });
    }
    try {
        await loadProjects();
    }
    catch (error) {
        root.textContent = error.message;
    }
}
void boot();
//# sourceMappingURL=dashboard.js.map