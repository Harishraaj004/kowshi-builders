/*
  static/script.js
  =================
  This file controls BEHAVIOUR: what happens when the user does something
  (types, clicks Send), and how we talk to our backend and update the page
  in response. It runs entirely in the browser, on the user's machine -
  which is exactly why we never put secrets or trusted business logic here.
*/

// --- Grab references to the HTML elements we'll need ------------------
// document.getElementById() looks up an element by its `id` attribute
// from index.html. Because our <script> tag has `defer`, we know the
// whole HTML document has already been parsed by the time this file
// runs, so these are guaranteed to exist (not null).
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const messagesContainer = document.getElementById("messages");


/**
 * Appends one new message bubble to the #messages section.
 *
 * @param {string} text - the message text to display
 * @param {"user" | "agent"} sender - whose message this is, used to pick
 *        which CSS class (and therefore alignment/colour) to apply
 */
function addMessageToUI(text, sender) {
    // document.createElement builds a new, detached <div> in memory - it
    // doesn't appear on the page until we explicitly attach it below.
    const bubble = document.createElement("div");

    // className sets the CSS classes on this element. Both "message" (the
    // shared base style) and either "user" or "agent" (the side-specific
    // style) are defined in style.css.
    bubble.className = `message ${sender}`;

    // textContent (not innerHTML!) inserts the text as plain text. Using
    // textContent means if a user types something like "<script>", it's
    // displayed literally as text, not executed as HTML/JS. This matters
    // even in a toy project - it's the basic defence against a class of
    // bug/attack called Cross-Site Scripting (XSS).
    bubble.textContent = text;

    // Attach the new bubble as the last child inside #messages - this is
    // the moment it actually becomes visible on the page.
    messagesContainer.appendChild(bubble);

    // Auto-scroll to the bottom so the newest message is always in view,
    // the same way every chat app behaves.
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}


/**
 * Sends the user's message to our backend and displays the reply.
 *
 * This function is `async` because it needs to `await` a network request
 * - and network requests take real time (milliseconds to seconds), during
 * which the browser must stay responsive to everything else (scrolling,
 * other clicks, etc). `async`/`await` is JavaScript's way of writing
 * "pause here until this finishes, but don't freeze the whole page while
 * waiting."
 */
async function sendMessage(message) {
    // `fetch` is the browser's built-in function for making HTTP requests
    // from JavaScript - this is the actual mechanism connecting our
    // frontend to our FastAPI backend.
    const response = await fetch("/api/chat", {
        method: "POST",                 // matches @app.post("/api/chat") in main.py
        headers: {
            // Tells the server "the body of this request is JSON text" -
            // FastAPI/Pydantic uses this to know how to parse it.
            "Content-Type": "application/json",
        },
        // JSON.stringify converts a JS object into a JSON text string.
        // The shape here - { message: "..." } - must match what our
        // ChatRequest Pydantic model in main.py expects, or FastAPI will
        // reject the request with a validation error.
        body: JSON.stringify({ message: message }),
    });

    // `response.ok` is true for any HTTP status in the 200-299 "success"
    // range. If the backend returned an error (4xx/5xx), we want to know
    // rather than silently pretending everything worked.
    if (!response.ok) {
        throw new Error(`Backend returned an error: ${response.status}`);
    }

    // response.json() reads the response body and parses it from JSON
    // text back into a JS object - the mirror image of JSON.stringify
    // above. This is also `await`ed because reading the body is itself
    // an asynchronous operation.
    const data = await response.json();

    // `data` now looks like { reply: "You said: hello" } - matching the
    // ChatResponse shape returned by our /api/chat route.
    return data.reply;
}


// --- Wire up the form submission ---------------------------------------
// addEventListener registers a function to run whenever a particular
// event happens on this element. "submit" fires when the form is
// submitted - either by clicking the button, or by pressing Enter while
// the input is focused (both trigger the same event, which is exactly why
// we wrapped everything in a <form> in index.html).
chatForm.addEventListener("submit", async (event) => {
    // Forms normally submit by reloading the page (the browser's default,
    // decades-old behaviour, from before JavaScript existed). We don't
    // want that - we want to handle the submission ourselves with fetch()
    // and stay on the same page. preventDefault() stops that default
    // reload from happening.
    event.preventDefault();

    const userText = chatInput.value.trim();
    if (!userText) {
        return; // ignore empty submissions (the `required` attribute on
                 // the input already blocks most of these, but we guard
                 // here too in case that's ever removed)
    }

    // Show the user's own message immediately - we don't need to wait for
    // the backend to know what the user typed.
    addMessageToUI(userText, "user");

    // Clear the input box right away so it's ready for the next message.
    chatInput.value = "";

    try {
        const reply = await sendMessage(userText);
        addMessageToUI(reply, "agent");
    } catch (error) {
        // If the network request fails (server down, network error,
        // non-2xx response), show something visible rather than failing
        // silently - a beginner-friendly but real error-handling habit.
        console.error("Chat request failed:", error);
        addMessageToUI("(error talking to the backend - see console)", "agent");
    }
});
