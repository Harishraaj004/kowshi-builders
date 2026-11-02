/*
  frontend/src/chat.ts
  =====================
  The chat assistant for SIGNED-IN customers on the dashboard, so someone
  with no quote yet can get one without leaving the page. It injects the
  same widget the home page has, talks to the same /api/chat endpoint, and
  keeps the same per-user conversation id (so the home page and dashboard
  share one chat history).

  The home page's own widget lives in index.html + main.ts, because there it
  also has to handle guests (sign-up prompt, auth modal).
*/
import { renderMarkdown } from "./markdown.js";
import { api } from "./shared.js";
const WIDGET_HTML = `
<button id="chat-launcher" aria-label="Open chat with Sri Kowshi Builders Assistant" aria-expanded="false"
    class="flex h-[62px] w-[62px] items-center justify-center rounded-full bg-dark text-gold shadow-[0_14px_40px_rgba(12,26,22,0.35)] ring-2 ring-gold/40 transition hover:scale-105 hover:ring-gold">
    <svg class="h-[26px] w-[26px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5Z" />
        <path d="M8 11.5h.01M12 11.5h.01M16 11.5h.01" />
    </svg>
</button>
<div id="chat-panel" hidden class="absolute right-0 bottom-0 flex h-[min(580px,calc(100vh-100px))] w-[min(380px,calc(100vw-32px))] flex-col overflow-hidden rounded-3xl border border-border bg-surface shadow-[0_24px_60px_rgba(12,26,22,0.25)]">
    <header class="flex shrink-0 items-center justify-between bg-dark px-4 py-3.5 text-white">
        <div class="flex items-center gap-3">
            <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/5 ring-1 ring-gold/40">
                <img src="/static/images/logo-mark.svg" alt="" class="h-6 w-auto" width="64" height="48" />
            </span>
            <div>
                <strong class="block text-sm">Sri Kowshi Assistant</strong>
                <span class="flex items-center gap-1.5 text-xs text-dark-muted"><span class="inline-block h-[7px] w-[7px] rounded-full bg-green-400"></span>Online</span>
            </div>
        </div>
        <div class="flex items-center gap-1">
            <button id="chat-new" type="button" aria-label="Start a new chat" title="New chat" class="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-white hover:bg-white/10">
                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14" /><path d="M5 12h14" /></svg>
                New chat
            </button>
            <button id="chat-close" aria-label="Close chat" class="flex rounded-md p-1 text-white hover:bg-white/10">
                <svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18" /><path d="M6 6l12 12" /></svg>
            </button>
        </div>
    </header>
    <section id="messages" class="flex flex-1 flex-col gap-2.5 overflow-y-auto bg-bg p-4" aria-live="polite"></section>
    <div id="quick-actions" hidden class="flex flex-wrap gap-2 bg-bg px-4 pb-3">
        <button type="button" data-quick-message="I'd like a free quote for my project." class="rounded-full border border-border bg-surface px-3.5 py-1.5 text-xs font-medium text-ink hover:border-accent hover:text-accent-dark">Get a Quote</button>
        <button type="button" data-quick-message="What services do you offer?" class="rounded-full border border-border bg-surface px-3.5 py-1.5 text-xs font-medium text-ink hover:border-accent hover:text-accent-dark">Our Services</button>
        <button type="button" data-quick-message="How long does construction usually take?" class="rounded-full border border-border bg-surface px-3.5 py-1.5 text-xs font-medium text-ink hover:border-accent hover:text-accent-dark">Project Timeline</button>
    </div>
    <form id="chat-form" class="flex shrink-0 gap-2 border-t border-border bg-surface p-3">
        <input id="chat-input" type="text" placeholder="Type your message..." autocomplete="off" required
            class="flex-1 rounded-full border border-border bg-bg px-4 py-2.5 text-sm text-ink focus:outline-2 focus:-outline-offset-1 focus:outline-accent" />
        <button type="submit" aria-label="Send message" class="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-full bg-dark text-gold hover:bg-dark-2">
            <svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 2 11 13" /><path d="M22 2 15 22l-4-9-9-4 20-7Z" /></svg>
        </button>
    </form>
</div>`;
/** Adds the chat widget to the page and returns a function that opens it. */
export function initChat(options) {
    const widget = document.createElement("div");
    widget.id = "chat-widget";
    widget.className = "fixed right-4 bottom-4 z-[1000] font-sans sm:right-6 sm:bottom-6";
    widget.innerHTML = WIDGET_HTML;
    document.body.appendChild(widget);
    const el = (id) => widget.querySelector(`#${id}`);
    const launcher = el("chat-launcher");
    const panel = el("chat-panel");
    const messages = el("messages");
    const quick = el("quick-actions");
    const input = el("chat-input");
    // Same key main.ts uses, so one account has one conversation everywhere.
    const storageKey = `kowshiSessionId:${options.userId}`;
    let sessionId = localStorage.getItem(storageKey) ?? crypto.randomUUID();
    localStorage.setItem(storageKey, sessionId);
    function bubble(text, sender) {
        const div = document.createElement("div");
        const base = "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed break-words [&>*:first-child]:mt-0 [&>*:last-child]:mb-0";
        div.className =
            base +
                (sender === "user"
                    ? " self-end rounded-br-md bg-dark text-white"
                    : " self-start rounded-bl-md border border-border bg-surface text-ink");
        if (sender === "agent") {
            div.innerHTML = renderMarkdown(text);
        }
        else {
            div.textContent = text;
        }
        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
    }
    function typing() {
        const div = document.createElement("div");
        div.className = "self-start flex items-center gap-1 rounded-2xl rounded-bl-md border border-border bg-surface px-4 py-3";
        for (let i = 0; i < 3; i++) {
            const dot = document.createElement("span");
            dot.className = "typing-dot inline-block h-2 w-2 rounded-full bg-ink-muted";
            div.appendChild(dot);
        }
        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
        return div;
    }
    function greet() {
        bubble("Hi! I'm the Sri Kowshi assistant. Tell me about your project and I'll prepare a free quote - it will appear on this dashboard automatically.", "agent");
        quick.hidden = false;
    }
    async function send(text) {
        quick.hidden = true;
        bubble(text, "user");
        const wait = typing();
        try {
            const reply = await api("/api/chat", { method: "POST", body: { message: text, session_id: sessionId } });
            wait.remove();
            bubble(reply.reply, "agent");
            if (reply.project_id !== null) {
                bubble("Your project has been added to your dashboard.", "agent");
                options.onProjectCreated();
            }
        }
        catch (error) {
            console.error("Chat request failed:", error);
            wait.remove();
            bubble("(error talking to the backend - see console)", "agent");
        }
    }
    async function loadHistory() {
        try {
            const data = await api(`/api/history/${sessionId}`);
            for (const m of data.messages) {
                bubble(m.content, m.role === "assistant" ? "agent" : "user");
            }
            if (data.messages.length === 0) {
                greet();
            }
        }
        catch {
            greet();
        }
    }
    function open() {
        panel.hidden = false;
        launcher.hidden = true;
        launcher.setAttribute("aria-expanded", "true");
        input.focus();
    }
    function close() {
        panel.hidden = true;
        launcher.hidden = false;
        launcher.setAttribute("aria-expanded", "false");
    }
    launcher.addEventListener("click", open);
    el("chat-close").addEventListener("click", close);
    el("chat-new").addEventListener("click", () => {
        sessionId = crypto.randomUUID();
        localStorage.setItem(storageKey, sessionId);
        messages.replaceChildren();
        input.value = "";
        greet();
        input.focus();
    });
    el("chat-form").addEventListener("submit", (event) => {
        event.preventDefault();
        const text = input.value.trim();
        if (text) {
            input.value = "";
            void send(text);
        }
    });
    quick.querySelectorAll("[data-quick-message]").forEach((button) => button.addEventListener("click", () => void send(button.dataset.quickMessage ?? "")));
    void loadHistory();
    return { open };
}
//# sourceMappingURL=chat.js.map