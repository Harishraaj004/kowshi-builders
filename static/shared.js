/*
  frontend/src/shared.ts
  Small helpers used by both the marketing page (main.ts) and the
  dashboard (dashboard.ts). Browsers load this as a native ES module, which
  is why the other files import it as "./shared.js" (the compiled name).
*/
export function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}
/** fetch() wrapper: sends JSON, throws Error(server's `detail` message) on failure. */
export async function api(path, options = {}) {
    const init = { method: options.method ?? "GET", credentials: "same-origin" };
    if (options.form) {
        init.body = options.form;
    }
    else if (options.body !== undefined) {
        init.headers = { "Content-Type": "application/json" };
        init.body = JSON.stringify(options.body);
    }
    const response = await fetch(path, init);
    if (!response.ok) {
        let message = `Request failed (${response.status})`;
        try {
            const data = await response.json();
            if (typeof data.detail === "string") {
                message = data.detail;
            }
            else if (Array.isArray(data.detail) && data.detail[0]?.msg) {
                message = String(data.detail[0].msg);
            }
        }
        catch {
            /* non-JSON error body - keep the generic message */
        }
        const error = new Error(message);
        error.status = response.status;
        throw error;
    }
    return (await response.json());
}
export async function fetchCurrentUser() {
    try {
        return (await api("/api/auth/me")).user;
    }
    catch {
        return null;
    }
}
//# sourceMappingURL=shared.js.map