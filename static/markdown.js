/*
  frontend/src/markdown.ts
  =========================
  The tiny Markdown-to-HTML renderer for chat replies, shared by the home
  page chat (main.ts) and the dashboard chat (chat.ts).
*/
import { escapeHtml } from "./shared.js";
// --- A small, hand-rolled Markdown renderer -------------------------------
// Claude's replies come back as plain text that USES Markdown syntax
// (**bold**, "- " bullet lists, "| a | b |" tables, ...) - see the raw
// chat transcript that prompted this change, where a table rendered as
// literal pipe characters instead of an actual table. We didn't reach
// for an npm Markdown library (e.g. "marked") because that would need a
// bundler to work in the browser without a build step of its own -
// bigger than what a "render a handful of patterns Claude actually uses"
// problem needs. This covers: **bold**, *italic*, `code`, "- "/"* "
// bullet lists, "1. " numbered lists, and "| ... |" tables - not the
// entire Markdown spec, just what shows up in practice.
//
// SECURITY NOTE: we're about to use `innerHTML` (not `textContent`) to
// render this, specifically so real <strong>/<ul>/<table> elements show
// up instead of literal asterisks and pipes. That makes escaping HTML
// BEFORE doing any Markdown-to-HTML conversion absolutely required - if
// we skipped this and Claude's reply ever contained something that
// looked like a <tag>, `innerHTML` would try to render it as real HTML
// instead of displaying it as text. escapeHtml() runs FIRST, on the raw
// text, before any Markdown pattern is matched - so by the time
// **bold**-style patterns are converted to real <strong> tags, there is
// no longer any way for a stray < or > in the ORIGINAL text to become a
// real tag.
/**
 * Applies INLINE Markdown formatting (bold/italic/code) to a line of
 * text that has ALREADY been through escapeHtml(). Order matters here:
 * bold (**) is matched before italic (*), so "**bold**" doesn't get
 * mistaken for two separate italic markers either side of "bold".
 */
function renderInline(escapedText) {
    return escapedText
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/__(.+?)__/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/`(.+?)`/g, '<code class="rounded bg-bg px-1 py-0.5 text-[0.85em]">$1</code>');
}
/** Splits a Markdown table's row text into its individual cell strings. */
function splitTableRow(line) {
    // A row typically looks like "| Tier | Cost |" - leading/trailing
    // pipes are just visual framing, not real columns, so we trim the
    // string first and then drop one leading/trailing empty cell that
    // splitting on "|" produces from those edge pipes.
    const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return trimmed.split("|").map((cell) => cell.trim());
}
/** Renders one Markdown table (a header row + separator row + body rows) as a real HTML <table>. */
function renderTable(lines) {
    const headerCells = splitTableRow(lines[0]);
    const bodyRows = lines.slice(2); // lines[1] is the "|---|---|" separator - not real data
    const headHtml = headerCells
        .map((cell) => `<th class="border border-border bg-bg px-2 py-1 text-left font-semibold">${renderInline(cell)}</th>`)
        .join("");
    const bodyHtml = bodyRows
        .map((line) => {
        const cells = splitTableRow(line);
        const cellsHtml = cells.map((cell) => `<td class="border border-border px-2 py-1">${renderInline(cell)}</td>`).join("");
        return `<tr>${cellsHtml}</tr>`;
    })
        .join("");
    // overflow-x-auto matters a lot here specifically: our chat panel is
    // only ~330px wide, and a table with several columns will easily be
    // wider than that. Without this wrapper, a wide table would either
    // get squashed illegibly or blow out the whole panel's layout;
    // with it, the TABLE scrolls horizontally inside its own box while
    // the rest of the chat stays put.
    return `<div class="my-1.5 overflow-x-auto"><table class="w-full border-collapse text-xs"><thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`;
}
/** Renders one "block" (a group of lines with no blank line between them) as HTML. */
function renderBlock(block) {
    const lines = block.split("\n").filter((line) => line.trim().length > 0);
    if (lines.length === 0) {
        return "";
    }
    // A table: at least a header + separator row, and the separator row
    // is made up only of pipes, dashes, colons, and whitespace (e.g.
    // "|---|:---:|"). Checking the SEPARATOR row (not just "contains a
    // pipe") is what tells a real table apart from a sentence that
    // happens to mention a "|" character.
    if (lines.length >= 2 && lines[0].includes("|") && /^[\s|:-]+$/.test(lines[1])) {
        return renderTable(lines);
    }
    // A heading: the ENTIRE block is one line starting with 1-6 "#"
    // characters and a space (e.g. "## Your Construction Quote").
    // Headings are normally their own block (a blank line separates them
    // from the text below), which is why checking `lines.length === 1`
    // is enough here rather than checking every line individually.
    if (lines.length === 1) {
        const headingMatch = lines[0].match(/^#{1,6}\s+(.+)$/);
        if (headingMatch) {
            // We don't bother scaling the font size by heading LEVEL
            // (# vs ###) - inside a ~330px-wide chat bubble, one
            // consistent "this is a heading" style reads better than
            // several very-slightly-different sizes.
            return `<p class="mt-2 mb-1 text-[0.95em] font-semibold">${renderInline(headingMatch[1])}</p>`;
        }
    }
    // A bullet list: EVERY line starts with "- ", "* ", or "• ".
    if (lines.every((line) => /^[-*•]\s+/.test(line))) {
        const items = lines.map((line) => `<li>${renderInline(line.replace(/^[-*•]\s+/, ""))}</li>`).join("");
        return `<ul class="my-1.5 list-disc space-y-0.5 pl-5">${items}</ul>`;
    }
    // A numbered list: EVERY line starts with "1. ", "2. ", etc.
    if (lines.every((line) => /^\d+\.\s+/.test(line))) {
        const items = lines.map((line) => `<li>${renderInline(line.replace(/^\d+\.\s+/, ""))}</li>`).join("");
        return `<ol class="my-1.5 list-decimal space-y-0.5 pl-5">${items}</ol>`;
    }
    // Otherwise: an ordinary paragraph. Lines within it join with <br>
    // (a single Markdown newline is just a line break, not a new
    // paragraph - that's what the blank-line splitting in
    // renderMarkdown() below is for).
    return `<p class="my-1.5">${lines.map(renderInline).join("<br>")}</p>`;
}
/**
 * Converts a raw Markdown string (as Claude sends it) into safe HTML,
 * ready to assign to an element's innerHTML.
 */
export function renderMarkdown(rawText) {
    const escaped = escapeHtml(rawText);
    // Splitting on blank lines is how Markdown (and this renderer)
    // decides where one paragraph/list/table ends and the next begins.
    const blocks = escaped.split(/\n\s*\n/);
    return blocks.map(renderBlock).join("");
}
//# sourceMappingURL=markdown.js.map