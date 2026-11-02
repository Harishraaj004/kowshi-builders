/*
  frontend/src/admin.ts
  ======================
  The admin console (static/admin.html): sign in, then three views -
    Requests  - appointment requests; accept one, or ask the client to move it
    Calendar  - a month grid of every appointment and meeting
    Clients   - everyone who has registered, with their open requests

  The server enforces admin-only access (app/admin.py); this file only
  decides what to show.
*/
import { api, escapeHtml } from "./shared.js";
let view = "requests";
let appts = [];
let clients = [];
let monthStart = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
let selectedDay = null; // "YYYY-MM-DD" in local time
let changeFormFor = null;
const $ = (id) => document.getElementById(id);
const root = $("app");
// --- Formatting ------------------------------------------------------------
const fmt = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const timeOnly = (iso) => new Date(iso).toLocaleTimeString(undefined, { timeStyle: "short" });
const pad = (n) => String(n).padStart(2, "0");
const dayKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const toLocalInput = (d) => `${dayKey(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const kindLabel = (k) => (k === "discussion" ? "Call with engineer" : "Site visit");
const STATUS_LABEL = {
    requested: "New request",
    confirmed: "Confirmed",
    change_requested: "Waiting for client",
    completed: "Completed",
    cancelled: "Cancelled",
};
const STATUS_STYLE = {
    requested: "bg-amber-100 text-amber-800",
    confirmed: "bg-blue-100 text-blue-800",
    change_requested: "bg-purple-100 text-purple-800",
    completed: "bg-green-100 text-green-800",
    cancelled: "bg-stone-100 text-ink-muted",
};
const badge = (s) => `<span class="inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS_STYLE[s]}">${STATUS_LABEL[s]}</span>`;
const BTN = "rounded-xl px-4 py-2.5 text-sm font-semibold transition disabled:opacity-60";
const BTN_PRIMARY = `${BTN} bg-dark text-white shadow-[0_8px_20px_rgba(12,26,22,0.18)] hover:-translate-y-0.5 hover:bg-dark-2`;
const BTN_SECONDARY = `${BTN} border border-border bg-surface text-ink hover:border-accent hover:text-accent-dark`;
const INPUT = "rounded-xl border border-border bg-bg px-3.5 py-2.5 text-sm focus:outline-2 focus:outline-accent";
const TAB = "rounded-xl px-4 py-2 text-sm font-semibold transition";
const initials = (name) => name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((part) => part[0].toUpperCase()).join("") || "?";
const avatar = (name, size = "h-10 w-10 text-sm") => `<span class="flex ${size} shrink-0 items-center justify-center rounded-full bg-gold-gradient font-bold text-dark">${escapeHtml(initials(name))}</span>`;
const icon = (paths, size = "h-5 w-5") => `<svg class="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
const KIND_ICON = {
    discussion: `<path d="M21 11.5a8.4 8.4 0 0 1-12.3 7.4L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5Z"/>`,
    site_visit: `<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11Z"/><circle cx="12" cy="10" r="2.5"/>`,
};
function toast(message, isError = false) {
    const el = $("toast");
    el.textContent = message;
    el.className =
        "fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl px-5 py-3 text-sm font-semibold shadow-[0_16px_40px_rgba(12,26,22,0.3)] " +
            (isError ? "bg-red-700 text-white" : "bg-dark text-gold-light");
    el.hidden = false;
    window.setTimeout(() => (el.hidden = true), 3500);
}
// --- Requests ----------------------------------------------------------------
function requestCard(a) {
    const open = a.status === "requested" || a.status === "confirmed" || a.status === "change_requested";
    const formOpen = changeFormFor === a.id;
    const minValue = toLocalInput(new Date());
    return `<li class="rounded-2xl border border-border bg-bg p-4 transition hover:border-accent/40 hover:bg-surface hover:shadow-[0_12px_30px_rgba(12,26,22,0.07)] sm:p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="flex items-center gap-3">
                ${avatar(a.customer_name || a.customer_email)}
                <div>
                    <strong>${escapeHtml(a.customer_name)}</strong>
                    <span class="text-sm text-ink-muted"> &middot; ${escapeHtml(a.customer_email)}</span>
                    <div class="flex items-center gap-1.5 text-sm text-ink-muted"><span class="text-accent-dark">${icon(KIND_ICON[a.kind] ?? "", "h-4 w-4")}</span>${kindLabel(a.kind)}${a.location ? ` &middot; ${escapeHtml(a.location)}` : ""}</div>
                </div>
            </div>
            ${badge(a.status)}
        </div>
        <p class="mb-0 mt-3 inline-flex items-center gap-2 rounded-xl bg-surface px-3 py-2 text-sm ring-1 ring-border">${icon(`<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>`, "h-4 w-4 text-accent-dark")}${a.status === "requested" ? "Requested for" : "Scheduled for"} <strong>${fmt(a.scheduled_for)}</strong></p>
        ${a.notes ? `<p class="mb-0 mt-1 text-sm text-ink-muted">Client note: ${escapeHtml(a.notes)}</p>` : ""}
        ${a.status === "change_requested" && a.proposed_for
        ? `<p class="mb-0 mt-1 text-sm text-purple-800">You asked the client to move it to <strong>${fmt(a.proposed_for)}</strong>${a.admin_note ? ` &mdash; &ldquo;${escapeHtml(a.admin_note)}&rdquo;` : ""}</p>`
        : ""}
        ${open
        ? `<div class="mt-3 flex flex-wrap gap-2">
                    ${a.status === "requested" ? `<button data-action="accept" data-id="${a.id}" class="${BTN_PRIMARY}">Accept</button>` : ""}
                    <button data-action="toggle-change" data-id="${a.id}" class="${BTN_SECONDARY}">${a.status === "change_requested" ? "Propose another time" : "Request a time change"}</button>
                </div>`
        : ""}
        ${formOpen
        ? `<form data-form="change" data-id="${a.id}" class="mt-3 grid gap-3 rounded-xl border border-border bg-surface p-3.5 sm:grid-cols-2">
                    <label class="flex flex-col gap-1 text-xs font-semibold">Proposed new time
                        <input name="when" type="datetime-local" required min="${minValue}" class="${INPUT} font-normal" /></label>
                    <label class="flex flex-col gap-1 text-xs font-semibold">Message to the client (optional)
                        <input name="message" type="text" maxlength="500" placeholder="e.g. Our engineer is on another site that day" class="${INPUT} font-normal" /></label>
                    <div class="flex gap-2 sm:col-span-2">
                        <button type="submit" class="${BTN_PRIMARY}">Send to client</button>
                        <button type="button" data-action="toggle-change" data-id="${a.id}" class="${BTN_SECONDARY}">Cancel</button>
                    </div>
                </form>`
        : ""}
    </li>`;
}
function renderRequests() {
    const groups = [
        { title: "Needs your answer", hint: "New requests from clients.", items: appts.filter((a) => a.status === "requested") },
        { title: "Waiting for the client", hint: "You asked these clients to change the time.", items: appts.filter((a) => a.status === "change_requested") },
        { title: "Confirmed", hint: "Accepted appointments.", items: appts.filter((a) => a.status === "confirmed") },
    ];
    return groups
        .map((g) => `<section class="mb-8 last:mb-0">
                <h2 class="mb-1 mt-0 flex items-center gap-2 text-lg font-extrabold">${g.title} <span class="rounded-full bg-accent-light px-2 py-0.5 text-xs font-bold text-accent-dark">${g.items.length}</span></h2>
                <p class="mb-4 mt-0 text-sm text-ink-muted">${g.hint}</p>
                ${g.items.length ? `<ul class="m-0 flex list-none flex-col gap-3 p-0">${g.items.map(requestCard).join("")}</ul>` : `<p class="rounded-2xl border border-dashed border-border px-4 py-6 text-center text-sm text-ink-muted">Nothing here right now.</p>`}
            </section>`)
        .join("");
}
// --- Calendar ----------------------------------------------------------------
const CHIP = {
    requested: "bg-amber-100 text-amber-900",
    confirmed: "bg-blue-100 text-blue-900",
    change_requested: "bg-purple-100 text-purple-900",
    completed: "bg-green-100 text-green-900",
    cancelled: "",
};
function renderCalendar() {
    const byDay = new Map();
    for (const a of appts) {
        if (a.status === "cancelled") {
            continue;
        }
        const key = dayKey(new Date(a.scheduled_for));
        byDay.set(key, [...(byDay.get(key) ?? []), a]);
    }
    const first = new Date(monthStart);
    const lead = (first.getDay() + 6) % 7; // weeks start on Monday
    const daysInMonth = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
    const todayKey = dayKey(new Date());
    const cells = [];
    for (let i = 0; i < lead; i++) {
        cells.push(`<div class="min-h-24 bg-bg/60"></div>`);
    }
    for (let day = 1; day <= daysInMonth; day++) {
        const key = `${first.getFullYear()}-${pad(first.getMonth() + 1)}-${pad(day)}`;
        const items = byDay.get(key) ?? [];
        const chips = items
            .slice(0, 3)
            .map((a) => `<div class="truncate rounded px-1 py-0.5 text-[0.68rem] font-medium ${CHIP[a.status]}">${timeOnly(a.scheduled_for)} ${escapeHtml(a.customer_name)}</div>`)
            .join("");
        const more = items.length > 3 ? `<div class="text-[0.68rem] text-ink-muted">+${items.length - 3} more</div>` : "";
        cells.push(`<button type="button" data-action="pick-day" data-day="${key}" class="flex min-h-24 flex-col gap-1 bg-surface p-1.5 text-left transition hover:bg-accent-light ${selectedDay === key ? "bg-accent-light outline-2 -outline-offset-2 outline-accent" : ""}">
            <span class="text-xs font-semibold ${key === todayKey ? "inline-flex h-6 w-6 items-center justify-center rounded-full bg-dark text-gold" : "px-1"}">${day}</span>${chips}${more}</button>`);
    }
    const monthName = first.toLocaleDateString(undefined, { month: "long", year: "numeric" });
    const heads = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        .map((d) => `<div class="bg-dark py-2 text-center text-xs font-bold uppercase tracking-wide text-gold">${d}</div>`)
        .join("");
    const dayItems = selectedDay ? byDay.get(selectedDay) ?? [] : [];
    const detail = selectedDay
        ? `<section class="mt-6"><h3 class="mb-2 mt-0 text-base font-bold">${new Date(selectedDay + "T00:00:00").toLocaleDateString(undefined, { dateStyle: "full" })}</h3>
            ${dayItems.length ? `<ul class="m-0 flex list-none flex-col gap-2 p-0">${dayItems
            .map((a) => `<li class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-bg p-3.5 text-sm">
                        <span><strong>${timeOnly(a.scheduled_for)}</strong> &middot; ${escapeHtml(a.customer_name)} &middot; ${kindLabel(a.kind)}${a.location ? ` &middot; ${escapeHtml(a.location)}` : ""}</span>${badge(a.status)}</li>`)
            .join("")}</ul>` : `<p class="text-sm text-ink-muted">No appointments or meetings this day.</p>`}
        </section>`
        : `<p class="mt-4 text-sm text-ink-muted">Select a day to see its appointments.</p>`;
    return `<div class="mb-3 flex items-center justify-between">
            <h2 class="m-0 text-xl font-extrabold">${monthName}</h2>
            <div class="flex gap-2">
                <button data-action="month" data-delta="-1" class="${BTN_SECONDARY}" aria-label="Previous month">&larr;</button>
                <button data-action="month" data-delta="0" class="${BTN_SECONDARY}">Today</button>
                <button data-action="month" data-delta="1" class="${BTN_SECONDARY}" aria-label="Next month">&rarr;</button>
            </div>
        </div>
        <div class="overflow-x-auto"><div class="grid min-w-[40rem] grid-cols-7 gap-px overflow-hidden rounded-2xl border border-border bg-border">${heads}${cells.join("")}</div></div>
        <p class="mb-0 mt-3 flex flex-wrap gap-3 text-xs text-ink-muted">
            <span class="rounded px-1.5 ${CHIP.requested}">New request</span><span class="rounded px-1.5 ${CHIP.change_requested}">Waiting for client</span>
            <span class="rounded px-1.5 ${CHIP.confirmed}">Confirmed</span><span class="rounded px-1.5 ${CHIP.completed}">Completed</span></p>
        ${detail}`;
}
// --- Clients -----------------------------------------------------------------
function renderClients() {
    if (clients.length === 0) {
        return `<p class="m-0 rounded-2xl border border-dashed border-border px-4 py-8 text-center text-ink-muted">No clients have registered yet.</p>`;
    }
    const rows = clients
        .map((c) => `<tr class="border-t border-border">
                <td class="py-3 pr-3"><span class="flex items-center gap-3 font-semibold">${avatar(c.name || c.email, "h-8 w-8 text-xs")}${escapeHtml(c.name)}</span></td>
                <td class="py-2.5 pr-3">${escapeHtml(c.email)}</td>
                <td class="py-2.5 pr-3">${escapeHtml(c.latest_location ?? "-")}</td>
                <td class="py-2.5 pr-3">${c.projects}</td>
                <td class="py-2.5 pr-3">${c.open_requests ? `<span class="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">${c.open_requests} open</span>` : "-"}</td>
                <td class="py-2.5 text-ink-muted">${new Date(c.created_at).toLocaleDateString()}</td></tr>`)
        .join("");
    return `<h2 class="mb-4 mt-0 text-lg font-extrabold">Registered clients</h2><div class="overflow-x-auto"><table class="w-full text-left text-sm">
        <thead><tr class="text-xs uppercase tracking-wide text-ink-muted"><th class="pb-2 pr-3">Name</th><th class="pb-2 pr-3">Email</th><th class="pb-2 pr-3">Latest project</th><th class="pb-2 pr-3">Projects</th><th class="pb-2 pr-3">Requests</th><th class="pb-2">Joined</th></tr></thead>
        <tbody>${rows}</tbody></table></div>`;
}
// --- Shell ---------------------------------------------------------------------
function render() {
    const pending = appts.filter((a) => a.status === "requested").length;
    const tab = (v, label, count = 0) => `<button data-action="view" data-view="${v}" class="${TAB} ${view === v ? "bg-dark text-white shadow-sm" : "text-ink-muted hover:bg-bg hover:text-ink"}">${label}${count ? ` <span class="ml-1 rounded-full bg-gold px-1.5 text-xs font-bold text-dark">${count}</span>` : ""}</button>`;
    $("tabs").innerHTML = tab("requests", "Requests", pending) + tab("calendar", "Calendar") + tab("clients", "Clients");
    const stat = (label, value, paths) => `<div class="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur">
            <span class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gold/15 text-gold">${icon(paths)}</span>
            <div><p class="m-0 text-2xl font-extrabold leading-none">${value}</p><p class="m-0 mt-1 text-xs text-dark-muted">${label}</p></div>
        </div>`;
    $("stats").innerHTML =
        stat("New requests", pending, `<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>`) +
            stat("Waiting for client", appts.filter((a) => a.status === "change_requested").length, `<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>`) +
            stat("Confirmed", appts.filter((a) => a.status === "confirmed").length, `<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18M9 15l2 2 4-4"/>`) +
            stat("Clients", clients.length, `<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0M17 11a3 3 0 1 0 0-6M22 21a6 6 0 0 0-4-5.7"/>`);
    root.innerHTML = view === "requests" ? renderRequests() : view === "calendar" ? renderCalendar() : renderClients();
}
async function load() {
    const [a, c] = await Promise.all([
        api("/api/admin/appointments"),
        api("/api/admin/clients"),
    ]);
    appts = a.appointments;
    clients = c.clients;
    render();
}
async function perform(action, success) {
    try {
        await action();
        changeFormFor = null;
        await load();
        toast(success);
    }
    catch (error) {
        toast(error.message, true);
    }
}
// --- Events ----------------------------------------------------------------------
document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) {
        return;
    }
    const { action, id } = button.dataset;
    switch (action) {
        case "view":
            view = button.dataset.view;
            render();
            break;
        case "accept":
            await perform(() => api(`/api/admin/appointments/${id}/accept`, { method: "POST" }), "Accepted - the client can see it on their dashboard.");
            break;
        case "toggle-change":
            changeFormFor = changeFormFor === Number(id) ? null : Number(id);
            render();
            break;
        case "month": {
            const delta = Number(button.dataset.delta);
            const now = new Date();
            monthStart = delta === 0 ? new Date(now.getFullYear(), now.getMonth(), 1) : new Date(monthStart.getFullYear(), monthStart.getMonth() + delta, 1);
            render();
            break;
        }
        case "pick-day":
            selectedDay = button.dataset.day ?? null;
            render();
            break;
    }
});
document.addEventListener("submit", async (event) => {
    const form = event.target;
    if (form.dataset.form !== "change") {
        return;
    }
    event.preventDefault();
    const data = new FormData(form);
    await perform(() => api(`/api/admin/appointments/${form.dataset.id}/request-change`, {
        method: "POST",
        body: { proposed_for: new Date(String(data.get("when"))).toISOString(), message: String(data.get("message") ?? "") },
    }), "Sent - the client will see your proposed time on their dashboard.");
});
// --- Sign in / boot ---------------------------------------------------------------
async function showConsole(name) {
    $("login-screen").hidden = true;
    $("console").hidden = false;
    $("admin-name").textContent = name;
    try {
        await load();
    }
    catch (error) {
        root.textContent = error.message;
    }
}
$("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = $("login-error");
    const submit = $("login-submit");
    error.hidden = true;
    submit.disabled = true;
    try {
        const { user } = await api("/api/admin/login", {
            method: "POST",
            body: { email: $("login-email").value, password: $("login-password").value },
        });
        await showConsole(user.name || user.email);
    }
    catch (e) {
        error.textContent = e.message;
        error.hidden = false;
    }
    finally {
        submit.disabled = false;
    }
});
$("logout").addEventListener("click", async () => {
    await api("/api/admin/logout", { method: "POST" });
    window.location.reload();
});
async function boot() {
    // Uses the admin cookie only, so a customer signed in on another tab is unaffected.
    try {
        const { user } = await api("/api/admin/me");
        await showConsole(user.name || user.email);
    }
    catch {
        $("login-screen").hidden = false;
    }
}
void boot();
//# sourceMappingURL=admin.js.map