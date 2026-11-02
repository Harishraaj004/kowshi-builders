/**
 * frontend/src/main.ts
 * ======================
 * The TypeScript source for our chat widget + marketing-page dynamics.
 * This compiles to ../static/main.js (see tsconfig.json's outDir) - THAT
 * compiled file is what index.html actually loads via
 * <script type="module" src="/static/main.js">.
 *
 * WHY TYPESCRIPT INSTEAD OF PLAIN JAVASCRIPT?
 * -----------------------------------------------
 * Plain JS (what static/script.js used to be) never checks that the data
 * flowing through your code has the shape you think it does - a typo'd
 * field name, or the backend changing what it sends, both fail silently
 * until something breaks at runtime, often far from the actual mistake.
 * TypeScript adds a compile-time type-checking pass on top of ordinary
 * JavaScript: you describe the SHAPE of your data once (see the
 * interfaces below), and the compiler then verifies every place that
 * data is used matches that shape - catching mismatches in your editor,
 * before the code ever runs.
 *
 * Every type/interface below disappears completely when this compiles to
 * JS - they exist purely to help the compiler (and you) reason about the
 * code; they cost nothing at runtime.
 */
import { api, fetchCurrentUser } from "./shared.js";
import { renderMarkdown } from "./markdown.js";
// --- A small "fail fast" DOM helper ----------------------------------------
// document.getElementById() is typed as returning `HTMLElement | null` -
// TypeScript has no way to know whether an id in your HTML actually
// exists, so it makes you handle the "what if it doesn't?" case. This
// generic helper does that ONCE: if the element is missing, we throw
// immediately with a clear message (the same "fail fast" philosophy as
// app/config.py's missing-API-key check on the backend), rather than
// letting a null slip through and cause a confusing crash three lines
// later. Every call site below gets back a properly-typed, non-null
// element.
function requireElement(id) {
    const element = document.getElementById(id);
    if (!element) {
        throw new Error(`Expected an element with id="${id}", but found none.`);
    }
    return element;
}
const chatForm = requireElement("chat-form");
const chatInput = requireElement("chat-input");
const messagesContainer = requireElement("messages");
const chatLauncher = requireElement("chat-launcher");
const chatPanel = requireElement("chat-panel");
const chatCloseButton = requireElement("chat-close");
const quickActionsContainer = requireElement("quick-actions");
// --- Session ID: how the backend knows which conversation this is -----
// HTTP requests are stateless, so WE hand the backend a token saying "these
// messages belong together". Signed-in users keep theirs in localStorage so
// their chat survives a refresh. Guests only get an in-memory id: refreshing
// the page throws it away, so a guest always starts with an empty chat (the
// "New chat" button does the same thing without a refresh).
// The key includes the user id so two accounts sharing one browser never see
// each other's conversation.
function sessionStorageKey(userId) {
    return `kowshiSessionId:${userId}`;
}
let sessionId = crypto.randomUUID();
function usePersistentSessionId(userId) {
    // Drop the old shared key from earlier versions - it may hold another user's chat.
    localStorage.removeItem("kowshiSessionId");
    let stored = localStorage.getItem(sessionStorageKey(userId));
    if (!stored) {
        stored = crypto.randomUUID();
        localStorage.setItem(sessionStorageKey(userId), stored);
    }
    sessionId = stored;
}
/**
 * Appends one new message bubble to the #messages section.
 */
function addMessageToUI(text, sender) {
    const bubble = document.createElement("div");
    // Tailwind utility classes, chosen based on `sender` - the same
    // "shared base + variant" idea our old hand-written CSS used
    // (.message / .message.user / .message.agent), just expressed as a
    // template string of utility classes instead of custom class names.
    // The "[&>*:first-child]:mt-0 [&>*:last-child]:mb-0" pair trims the
    // extra top/bottom margin renderBlock()'s <p>/<ul>/<table> elements
    // otherwise leave inside the bubble's own padding.
    const base = "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed break-words [&>*:first-child]:mt-0 [&>*:last-child]:mb-0";
    const variant = sender === "user"
        ? "self-end rounded-br-md bg-dark text-white"
        : "self-start rounded-bl-md border border-border bg-surface text-ink";
    bubble.className = `${base} ${variant}`;
    if (sender === "agent") {
        // Agent replies get real Markdown rendering (see renderMarkdown()
        // above) - innerHTML is safe here specifically BECAUSE
        // renderMarkdown() escapes the raw text before turning any of it
        // into real tags (see the big comment above escapeHtml()).
        bubble.innerHTML = renderMarkdown(text);
    }
    else {
        // The user's OWN typed text never needs Markdown rendering -
        // textContent keeps it as plain, always-safe text, exactly as
        // before.
        bubble.textContent = text;
    }
    messagesContainer.appendChild(bubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return bubble;
}
/**
 * Shows a temporary "..." bubble on the agent's side while we wait for
 * Claude's actual reply - the same idea as the typing indicator in any
 * real chat app (iMessage, WhatsApp, ...). Returns the bubble element so
 * the caller can remove it once the real reply arrives.
 */
function showTypingIndicator() {
    const bubble = document.createElement("div");
    bubble.className =
        "self-start flex items-center gap-1 rounded-2xl rounded-bl-md border border-border bg-surface px-4 py-3";
    // Three small dots, each with the .typing-dot class (defined in
    // input.css) - the nth-child(2)/(3) rules there give the 2nd and 3rd
    // dots a staggered animation-delay, producing the bouncing-wave
    // effect instead of all three dots moving in perfect unison.
    for (let i = 0; i < 3; i++) {
        const dot = document.createElement("span");
        dot.className = "typing-dot inline-block h-2 w-2 rounded-full bg-ink-muted";
        bubble.appendChild(dot);
    }
    messagesContainer.appendChild(bubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return bubble;
}
/**
 * Loads this session's past messages from the backend and renders them,
 * so a page reload shows the same conversation instead of an empty chat
 * log - even though the AI's MEMORY of it lives entirely in the
 * backend's SQLite database, not in this file.
 *
 * @returns true if at least one past message was rendered (a returning
 *          conversation), false for a brand-new session.
 */
async function loadConversationHistory() {
    const response = await fetch(`/api/history/${sessionId}`);
    if (!response.ok) {
        console.error("Failed to load conversation history:", response.status);
        return false;
    }
    // `as HistoryResponseBody` here is a TYPE ASSERTION - it tells the
    // compiler "trust me, this JSON matches this shape," because
    // response.json()'s real return type is just `any` (TypeScript can't
    // verify what's actually in a network response at compile time). The
    // assertion doesn't check anything at runtime - if the backend sent
    // something different, this would still compile fine and only fail
    // later when we try to use a field that isn't really there. Stage 5+
    // could add a runtime validation library (e.g. Zod) if that risk
    // starts to matter more than it does for a learning project.
    const data = (await response.json());
    for (const message of data.messages) {
        const sender = message.role === "assistant" ? "agent" : "user";
        addMessageToUI(message.content, sender);
    }
    // The visitor got a quote earlier but never signed up - bring the
    // prompt back under the conversation.
    if (data.unclaimed_quote_id !== null && !currentUser) {
        addSignupPrompt();
    }
    return data.messages.length > 0;
}
/**
 * Sends the user's message to our backend and returns Claude's reply
 * text.
 */
async function sendMessage(message) {
    const requestBody = { message, session_id: sessionId };
    const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
    });
    if (!response.ok) {
        throw new Error(`Backend returned an error: ${response.status}`);
    }
    return (await response.json());
}
/**
 * Shared "send this text as a chat message" flow - shows the user's
 * bubble immediately, shows a typing indicator while we wait, then swaps
 * it for the real reply (or an error bubble). Both the typed-message form
 * AND the quick-action buttons funnel through this one function.
 */
async function submitUserMessage(text) {
    addMessageToUI(text, "user");
    const typingBubble = showTypingIndicator();
    try {
        const reply = await sendMessage(text);
        typingBubble.remove();
        addMessageToUI(reply.reply, "agent");
        if (reply.project_id !== null) {
            addDashboardLink();
        }
        else if (reply.quote_id !== null) {
            addSignupPrompt();
        }
    }
    catch (error) {
        console.error("Chat request failed:", error);
        typingBubble.remove();
        addMessageToUI("(error talking to the backend - see console)", "agent");
    }
}
// --- Accounts: sign-up prompt, auth modal, header link ---------------------
// The quote summary ends with a call to action. Anonymous visitors get a
// card that opens the sign up / sign in modal; the chat's session_id is sent
// with the request so the server can attach this chat's quote to the new
// account and turn it into a dashboard project (app/projects.py).
let currentUser = null;
const authModal = requireElement("auth-modal");
const authForm = requireElement("auth-form");
const authTitle = requireElement("auth-title");
const authSubtitle = requireElement("auth-subtitle");
const authName = requireElement("auth-name");
const authEmail = requireElement("auth-email");
const authPassword = requireElement("auth-password");
const authError = requireElement("auth-error");
const authSubmit = requireElement("auth-submit");
const authSwitch = requireElement("auth-switch");
const authSwitchText = requireElement("auth-switch-text");
const googleWrap = requireElement("google-wrap");
const googleButton = requireElement("google-btn");
const authLink = requireElement("auth-link");
let authMode = "signup";
const otpForm = requireElement("otp-form");
const otpInfo = requireElement("otp-info");
const otpCode = requireElement("otp-code");
const otpError = requireElement("otp-error");
const otpSubmit = requireElement("otp-submit");
const authSwitchRow = requireElement("auth-switch-row");
let pendingEmail = "";
let pendingFlow = "signup";
let googleReady = false;
/** Swap the signup form for the "enter your emailed code" step. */
function showOtpStep() {
    authForm.hidden = true;
    googleWrap.hidden = true;
    authSwitchRow.hidden = true;
    otpForm.hidden = false;
    otpError.hidden = true;
    otpCode.value = "";
    otpSubmit.textContent = pendingFlow === "login" ? "Verify & sign in" : "Verify & create account";
    authTitle.textContent = "Verify your email";
    authSubtitle.textContent = "";
    otpInfo.textContent = `We sent a 5-digit code to ${pendingEmail}. It expires in 10 minutes.`;
    otpCode.focus();
}
function showOtpError(message) {
    otpError.textContent = message;
    otpError.hidden = false;
}
otpForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    otpError.hidden = true;
    otpSubmit.disabled = true;
    try {
        await api(`/api/auth/${pendingFlow}/verify`, {
            method: "POST",
            body: { email: pendingEmail, code: otpCode.value.trim(), session_id: sessionId },
        });
        onAuthenticated();
    }
    catch (error) {
        showOtpError(error.message);
        otpSubmit.disabled = false;
    }
});
requireElement("otp-resend").addEventListener("click", async () => {
    otpError.hidden = true;
    try {
        await api(`/api/auth/${pendingFlow}/resend`, { method: "POST", body: { email: pendingEmail } });
        otpInfo.textContent = `A new code was sent to ${pendingEmail}.`;
    }
    catch (error) {
        showOtpError(error.message);
    }
});
requireElement("otp-back").addEventListener("click", () => setAuthMode(pendingFlow));
function setAuthMode(mode) {
    authMode = mode;
    authForm.hidden = false;
    authSwitchRow.hidden = false;
    otpForm.hidden = true;
    if (googleReady) {
        googleWrap.hidden = false;
    }
    const signup = mode === "signup";
    authTitle.textContent = signup ? "Create your account" : "Welcome back";
    authSubtitle.textContent = signup
        ? "Track your quote, engineer discussion, site visit and documents in one dashboard."
        : "Sign in to see your project dashboard.";
    authName.hidden = !signup;
    authName.required = signup;
    authPassword.autocomplete = signup ? "new-password" : "current-password";
    authSubmit.textContent = signup ? "Sign up" : "Sign in";
    authSwitchText.textContent = signup ? "Already have an account?" : "New here?";
    authSwitch.textContent = signup ? "Sign in" : "Sign up";
    authError.hidden = true;
}
function openAuthModal(mode) {
    setAuthMode(mode);
    authModal.hidden = false;
    (mode === "signup" ? authName : authEmail).focus();
}
function closeAuthModal() {
    authModal.hidden = true;
}
function onAuthenticated() {
    // The dashboard shows the project created from this chat's quote.
    window.location.href = "/dashboard";
}
authSwitch.addEventListener("click", () => setAuthMode(authMode === "signup" ? "login" : "signup"));
requireElement("auth-close").addEventListener("click", closeAuthModal);
authModal.addEventListener("click", (event) => {
    if (event.target === authModal) {
        closeAuthModal();
    }
});
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !authModal.hidden) {
        closeAuthModal();
    }
});
authForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    authError.hidden = true;
    authSubmit.disabled = true;
    try {
        if (authMode === "signup") {
            // Step 1 of 2: the server emails a code; the account is only
            // created once it's verified (see showOtpStep below).
            const started = await api("/api/auth/signup/start", {
                method: "POST",
                body: { name: authName.value, email: authEmail.value, password: authPassword.value },
            });
            pendingEmail = started.email;
            pendingFlow = "signup";
            showOtpStep();
            authSubmit.disabled = false;
            return;
        }
        // Step 1 of 2: password checked, the server emails a code.
        const started = await api("/api/auth/login/start", {
            method: "POST",
            body: { email: authEmail.value, password: authPassword.value },
        });
        pendingEmail = started.email;
        pendingFlow = "login";
        showOtpStep();
        authSubmit.disabled = false;
    }
    catch (error) {
        authError.textContent = error.message;
        authError.hidden = false;
        authSubmit.disabled = false;
    }
});
document.querySelectorAll("[data-open-auth]").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    if (currentUser) {
        window.location.href = "/dashboard";
    }
    else {
        openAuthModal("login");
    }
}));
/** Google Sign-In. Only enabled if the server has GOOGLE_CLIENT_ID configured. */
async function setupGoogleSignIn() {
    const { google_client_id } = await api("/api/auth/config");
    if (!google_client_id) {
        return;
    }
    await new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = "https://accounts.google.com/gsi/client";
        script.async = true;
        script.onload = () => resolve();
        script.onerror = () => reject(new Error("Google script failed to load"));
        document.head.appendChild(script);
    });
    const google = window.google;
    google.accounts.id.initialize({
        client_id: google_client_id,
        callback: async ({ credential }) => {
            try {
                await api("/api/auth/google", { method: "POST", body: { credential, session_id: sessionId } });
                onAuthenticated();
            }
            catch (error) {
                authError.textContent = error.message;
                authError.hidden = false;
            }
        },
    });
    google.accounts.id.renderButton(googleButton, { theme: "outline", size: "large", width: 280, text: "continue_with" });
    googleReady = true;
    googleWrap.hidden = false;
}
/** The call-to-action card shown under a quote summary for anonymous visitors. */
function addSignupPrompt() {
    if (messagesContainer.querySelector("[data-signup-prompt]")) {
        return;
    }
    const card = document.createElement("div");
    card.dataset.signupPrompt = "true";
    card.className = "self-start max-w-[85%] rounded-2xl border border-accent bg-accent-light p-3.5 text-sm";
    card.innerHTML = `
        <strong class="block">Track your project</strong>
        <p class="mb-3 mt-1 text-ink-muted">Sign up or sign in with email or Google to follow your quote, engineer discussion, site visit, documents and start date.</p>
        <div class="flex flex-wrap gap-2">
            <button type="button" data-auth-mode="signup" class="rounded-lg bg-accent px-3.5 py-2 font-semibold text-white hover:bg-accent-dark">Sign up</button>
            <button type="button" data-auth-mode="login" class="rounded-lg border border-border bg-surface px-3.5 py-2 font-semibold text-ink hover:border-accent">Sign in</button>
        </div>`;
    card.querySelectorAll("[data-auth-mode]").forEach((button) => button.addEventListener("click", () => openAuthModal(button.dataset.authMode)));
    messagesContainer.appendChild(card);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}
/** Shown instead of the prompt when the visitor is already signed in. */
function addDashboardLink() {
    const card = document.createElement("a");
    card.href = "/dashboard";
    card.className =
        "self-start rounded-2xl border border-accent bg-accent-light px-3.5 py-2.5 text-sm font-semibold text-accent-dark no-underline hover:bg-white";
    card.textContent = "View this project on your dashboard →";
    messagesContainer.appendChild(card);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}
setupGoogleSignIn().catch((error) => console.warn("Google sign-in unavailable:", error));
// --- Wire up the form submission ---------------------------------------
chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const userText = chatInput.value.trim();
    if (!userText) {
        return;
    }
    chatInput.value = "";
    quickActionsContainer.hidden = true;
    await submitUserMessage(userText);
});
// --- Quick action buttons ------------------------------------------------
// querySelectorAll's generic parameter tells TypeScript what kind of
// element to expect back - here, real <button> elements, so `.dataset`
// (and eventually anything else HTMLButtonElement-specific) is available
// without an extra cast.
quickActionsContainer
    .querySelectorAll("[data-quick-message]")
    .forEach((button) => {
    button.addEventListener("click", async () => {
        const message = button.dataset.quickMessage;
        if (!message) {
            return;
        }
        quickActionsContainer.hidden = true;
        await submitUserMessage(message);
    });
});
// --- Chat widget open/close ----------------------------------------------
function openChatPanel() {
    chatPanel.hidden = false;
    chatLauncher.hidden = true;
    chatLauncher.setAttribute("aria-expanded", "true");
    chatInput.focus();
}
function closeChatPanel() {
    chatPanel.hidden = true;
    chatLauncher.hidden = false;
    chatLauncher.setAttribute("aria-expanded", "false");
}
chatLauncher.addEventListener("click", openChatPanel);
chatCloseButton.addEventListener("click", closeChatPanel);
document
    .querySelectorAll("[data-open-chat]")
    .forEach((button) => button.addEventListener("click", openChatPanel));
// --- Scroll-reveal animations ---------------------------------------------
// IntersectionObserver is a built-in browser API that watches a set of
// elements and tells you when each one enters (or leaves) the viewport -
// far cheaper than the old approach of manually checking every element's
// position on every scroll event. We use it purely for a visual effect:
// every element with class="reveal" (see input.css) starts invisible and
// shifted down; the moment it scrolls into view, we add "is-visible",
// which triggers the CSS transition back to its normal position.
const revealObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
        if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            // Once revealed, we don't need to keep watching this
            // element - unobserving keeps the browser from doing
            // pointless work for elements that already animated in.
            revealObserver.unobserve(entry.target);
        }
    }
}, {
    // Trigger a little before the element is fully on-screen (100px
    // "early"), so the animation feels responsive rather than
    // lagging behind the user's scroll.
    rootMargin: "0px 0px -100px 0px",
});
document.querySelectorAll(".reveal").forEach((element) => {
    revealObserver.observe(element);
});
// --- Safety net: never let content be PERMANENTLY invisible --------------
// Purely visual effects should degrade gracefully, not catastrophically.
// If IntersectionObserver is unsupported, blocked, or simply never fires
// for some reason we didn't anticipate (an unusual browser, a restrictive
// environment, a future browser bug), every ".reveal" element would stay
// at opacity: 0 forever - real content, permanently invisible, because of
// a decorative animation. That's a much worse failure than "the fade-in
// didn't play." So: after a generous delay, force-reveal anything that
// somehow never got marked visible on its own. In normal operation this
// timeout fires long after everything has already animated in naturally
// and finds nothing left to do.
window.setTimeout(() => {
    document
        .querySelectorAll(".reveal:not(.is-visible)")
        .forEach((element) => element.classList.add("is-visible"));
}, 4000);
// --- New chat ------------------------------------------------------------
function showGreeting() {
    addMessageToUI("Hi! I'm the Sri Kowshi Builders assistant. Ask me about pricing, " +
        "timelines, or our services - or pick one below to get started.", "agent");
    quickActionsContainer.hidden = false;
}
/** Throw away the visible conversation and start a fresh one server-side. */
function startNewChat() {
    sessionId = crypto.randomUUID();
    if (currentUser) {
        localStorage.setItem(sessionStorageKey(currentUser.id), sessionId);
    }
    messagesContainer.replaceChildren();
    chatInput.value = "";
    showGreeting();
    chatInput.focus();
}
requireElement("chat-new").addEventListener("click", startNewChat);
// --- Start up: signed-in users get their history back, guests start clean --
fetchCurrentUser()
    .then((user) => {
    currentUser = user;
    if (user) {
        authLink.textContent = "Dashboard";
        authLink.href = "/dashboard";
        usePersistentSessionId(user.id);
        return loadConversationHistory();
    }
    return false;
})
    .catch(() => false)
    .then((hasHistory) => {
    if (!hasHistory) {
        showGreeting();
    }
});
//# sourceMappingURL=main.js.map