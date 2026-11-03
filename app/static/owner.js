// The owner dashboard: /owner/{slug}?key=... (spec section 7).
// The key comes from the page's URL and goes to the API in the X-Owner-Key header.

const SLUG = decodeURIComponent(location.pathname.split("/")[2] || "");
const KEY = new URLSearchParams(location.search).get("key") || "";
const API = `/api/owner/${encodeURIComponent(SLUG)}`;
// ?frame=1: inside the /try page, which has its own Jawab bar and shows the customer chat itself.
if (new URLSearchParams(location.search).get("frame") === "1") {
  document.querySelector(".brandbar")?.remove();
  document.body.classList.add("framed");
}
const POLL_MS = 5000;
const MAX_TEXT = 1000;
const ARABIC = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]/;

const ACTION_LABELS = { answer: "Answer", ask_owner: "Ask owner", handoff: "Hand off" };
const KIND_LABELS = { ask_owner: "Question for you", handoff: "Handed off to you" };

const cards = new Map(); // escalation id -> {node, status, decision, signature, busy}
let business = { name: "" };
let pollTimer = null;
let refreshing = false;
let stopped = false;
let inboxLoaded = false; // cards on the first load don't animate in; later arrivals do
const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)");

const $ = (id) => document.getElementById(id);
const pendingEl = $("pending");
const recentEl = $("recent");

// --- Small DOM helpers (the same as the chat page) -------------------------------------------------

// el("p", {className: "x"}, "text", child): strings become text nodes, so nothing runs as HTML.
function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

// Arabic text gets the Arabic font; dir="auto" handles the direction.
function textNode(text, className = "text") {
  const span = el("span", { className, textContent: text, dir: "auto" });
  if (ARABIC.test(text)) span.classList.add("ar");
  return span;
}

function badge(kind, label) {
  return el("span", { className: `badge badge-${kind}`, textContent: label });
}

// Entries use a little markdown: paragraphs, "- " lists, tables and **bold**. Still only text nodes.
function lineKind(line) {
  line = line.trim();
  if (!line) return "blank";
  if (line.startsWith("|")) return "table";
  return /^[-*] /.test(line) ? "list" : "text";
}

function renderEntry(text) {
  const box = el("div", { className: "entry" });
  const lines = text.split("\n");
  for (let i = 0; i < lines.length;) {
    const kind = lineKind(lines[i]);
    const group = [];
    while (i < lines.length && lineKind(lines[i]) === kind) group.push(lines[i++].trim());
    if (kind === "table") box.append(renderTable(group));
    else if (kind === "list") box.append(el("ul", {}, ...group.map((l) => el("li", {}, ...inline(l.slice(2))))));
    else if (kind === "text") box.append(el("p", {}, ...inline(group.join(" "))));
  }
  return box;
}

function renderTable(lines) {
  const rows = lines
    .filter((l) => !/^\|[\s:|-]+\|?$/.test(l))
    .map((l) => l.replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
  const [head, ...body] = rows;
  return el("div", { className: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ...head.map((cell) => el("th", { textContent: cell })))),
    el("tbody", {}, ...body.map((row) => el("tr", {}, ...row.map((cell) => el("td", { textContent: cell })))))));
}

function inline(text) {
  return text.replaceAll("`", "").split(/\*\*(.+?)\*\*/).map((part, i) => (i % 2 ? el("strong", { textContent: part }) : part));
}

function formatTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return date.toDateString() === new Date().toDateString()
    ? time : `${date.toLocaleDateString([], { day: "numeric", month: "short" })}, ${time}`;
}

// --- Talking to the server ------------------------------------------------------------------------

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function api(path, { method = "GET", body } = {}) {
  const headers = { "X-Owner-Key": KEY };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (response.status === 403) {
    stop("This owner link isn't valid. Open the dashboard with the full owner link, including its key.");
    throw new ApiError(403, "Wrong owner key.");
  }
  if (!response.ok) {
    let message = "Something went wrong. Please try again.";
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (response.status === 422) message = `Write between 1 and ${MAX_TEXT} characters.`;
    } catch { /* not JSON */ }
    throw new ApiError(response.status, message);
  }
  return response.json();
}

function stop(message) {
  stopped = true;
  clearInterval(pollTimer);
  $("app").hidden = true;
  const notice = $("notice");
  notice.textContent = message;
  notice.hidden = false;
}

// --- Inbox ----------------------------------------------------------------------------------------

function renderTranscript(messages) {
  const list = el("ol", { className: "transcript" });
  list.setAttribute("aria-label", "Conversation");
  for (const m of messages) {
    if (!m.text.trim()) continue;
    const bubble = el("li", { className: `message ${m.role}` });
    if (m.role === "staff") bubble.append(el("span", { className: "sender", textContent: "Team" }));
    if (m.role === "bot" && m.action && m.action !== "answer") {
      bubble.append(el("span", { className: "bubble-meta" }, badge(m.action, ACTION_LABELS[m.action] || m.action)));
    }
    bubble.append(textNode(m.text));
    list.append(bubble);
  }
  return list;
}

function signature(e) {
  const last = e.messages[e.messages.length - 1];
  return `${e.status}|${e.learn_decision}|${e.question}|${e.conversation_state}|${last ? last.id : 0}`;
}

function cardHeader(e) {
  const status = e.status === "pending" ? null
    : el("span", { className: `status-chip${e.learn_decision === "saved" || e.learn_decision === "edited" ? " chip-learned" : ""}`,
      textContent: e.status === "closed" ? "Given back to the bot"
        : e.learn_decision === "saved" || e.learn_decision === "edited" ? "Learned"
          : e.learn_decision === "once" ? "Answered" : "Answered · decide below" });
  return el("header", { className: "card-header" },
    badge(e.kind, e.kind === "ask_owner" ? "Ask owner" : "Hand off"),
    el("span", { className: "card-title", textContent: KIND_LABELS[e.kind] || e.kind }),
    status,
    el("time", { className: "card-time", dateTime: e.created_at || "", textContent: formatTime(e.created_at) }));
}

function questionBlock(e) {
  return el("div", { className: "question" },
    el("h3", { textContent: "The assistant asked you" }),
    el("blockquote", { className: "owner-question", dir: "auto", textContent: e.question }));
}

// A textarea + buttons. `onSubmit(text, form)` returns a promise; errors show under the box.
function composer({ label, placeholder, submitLabel, onSubmit, extraButton = null }) {
  const id = `box-${Math.random().toString(36).slice(2)}`;
  const box = el("textarea", { id, rows: 3, maxLength: MAX_TEXT, dir: "auto", placeholder });
  const submit = el("button", { type: "submit", className: "primary", textContent: submitLabel });
  const status = el("p", { className: "form-status", role: "status" });
  const form = el("form", { className: "reply-form" },
    el("label", { htmlFor: id, textContent: label }),
    box,
    el("div", { className: "form-actions" }, submit, extraButton),
    status);
  box.addEventListener("input", () => box.classList.toggle("ar", ARABIC.test(box.value)));
  box.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) form.requestSubmit();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = box.value.trim();
    if (!text) {
      status.textContent = "Write a message first.";
      box.focus();
      return;
    }
    status.textContent = "";
    status.classList.remove("error");
    await onSubmit(text, { box, submit, status, form });
  });
  return form;
}

function setFormBusy(parts, busy, message = "") {
  parts.form.querySelectorAll("button, textarea").forEach((node) => (node.disabled = busy));
  parts.status.textContent = message;
  parts.status.classList.toggle("working", busy && !!message);
}

function showFormError(parts, error) {
  setFormBusy(parts, false);
  parts.status.textContent = error.message;
  parts.status.classList.add("error");
}

function askOwnerPending(e) {
  return composer({
    label: "Your answer",
    placeholder: "Type it the way you'd say it. The customer gets it in their own language.",
    submitLabel: "Send",
    onSubmit: async (text, parts) => {
      const entry = cards.get(e.id);
      entry.busy = true;
      setFormBusy(parts, true, "Sending… writing the reply in the customer's language and drafting a knowledge entry.");
      try {
        const data = await api(`/escalations/${e.id}/answer`, { method: "POST", body: { text } });
        entry.busy = false;
        upsertCard(data.escalation, { force: true });
        refresh();
      } catch (error) {
        entry.busy = false;
        if (error.status === 409) refresh();
        showFormError(parts, error);
      }
    },
  });
}

function relayBlock(e) {
  const relay = e.relay;
  const parts = [el("h3", { textContent: "Your answer" }),
    el("blockquote", { className: "owner-answer", dir: "auto" }, textNode(e.owner_answer || ""))];
  if (!relay) return el("div", { className: "relay" }, ...parts);

  if (relay.sent_text) {
    parts.push(el("p", { className: "sent", textContent: relay.fallback
      ? "Sent to the customer as a Team message ✓" : "Sent to the customer ✓" }));
    const bubble = el("div", { className: `message ${relay.sent_as === "staff" ? "staff" : "bot"} sent-bubble` });
    if (relay.sent_as === "staff") bubble.append(el("span", { className: "sender", textContent: "Team" }));
    bubble.append(textNode(relay.sent_text));
    parts.push(bubble);
  } else {
    parts.push(el("p", { className: "muted", textContent: "Nothing was sent to the customer: this didn't look like a message for them." }));
  }
  return el("div", { className: "relay" }, ...parts);
}

// --- Learning card -------------------------------------------------------------------------------

const ENTRY_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function learningBlock(e) {
  const relay = e.relay;
  if (!relay) return null;
  const proposal = relay.proposal;
  const entry = proposal && proposal.learn_action !== "none" ? proposal.proposed_entry : null;
  const box = el("section", { className: "learning" }, el("h3", { className: "teach-title", textContent: "✦ Teach your assistant" }));
  const status = el("p", { className: "form-status", role: "status" });
  const editor = entryEditor(e, entry, status);

  if (relay.fallback || !proposal) {
    box.append(el("p", { className: "learn-summary", textContent: "Couldn't draft a knowledge entry." }),
      el("p", { className: "muted small", textContent: "Write it yourself below, or skip it." }));
  } else if (!entry) {
    box.append(el("p", { className: "learn-summary", dir: "auto", textContent: proposal.owner_summary }),
      el("p", { className: "muted", textContent: "Looks like a one-off answer, so nothing to save." }),
      el("p", { className: "muted small", dir: "auto", textContent: proposal.reasoning }));
  } else {
    const head = el("div", { className: "proposal-head" },
      el("span", { className: "proposal-kind", textContent: proposal.learn_action === "update" ? "Update" : "New entry" }),
      el("code", { textContent: entry.id }),
      visibilityBadge(entry.visibility));
    const body = el("div", { className: "proposal" }, head);
    if (relay.old_text) body.append(el("del", { className: "old-text" }, renderEntry(relay.old_text)));
    body.append(renderEntry(entry.text));
    box.append(el("p", { className: "learn-summary", dir: "auto", textContent: proposal.owner_summary }),
      body, el("p", { className: "muted small", dir: "auto", textContent: proposal.reasoning }));
  }

  const once = el("button", { type: "button", className: entry ? "secondary" : "primary", textContent: "Just this once" });
  once.addEventListener("click", () => decide(e, { decision: "once" }, { status, buttons: box }));
  const actions = el("div", { className: "learn-actions" });
  if (entry) {
    const save = el("button", { type: "button", className: "primary save-learn", textContent: "Save ✦" });
    const edit = el("button", { type: "button", className: "secondary", textContent: "Edit" });
    save.addEventListener("click", () => decide(e, { decision: "saved" }, { status, buttons: box, editor }));
    edit.addEventListener("click", () => editor.open());
    actions.append(save, edit, once);
  } else if (relay.fallback || !proposal) {
    actions.append(once);
  } else {
    const anyway = el("button", { type: "button", className: "link-button", textContent: "Save anyway" });
    anyway.addEventListener("click", () => editor.open({ blank: true }));
    actions.append(once, anyway);
  }
  box.append(actions, editor.node, status);
  if (relay.fallback || !proposal) editor.open({ blank: true, cancellable: false, focus: false });
  return box;
}

function visibilityBadge(visibility) {
  return badge(visibility === "internal" ? "internal" : "public", visibility === "internal" ? "Internal" : "Public");
}

// The Edit form: ID, visibility and text. Polling never rebuilds an undecided card (see upsertCard),
// so a half-written entry stays put.
function entryEditor(e, entry, status) {
  const uid = Math.random().toString(36).slice(2);
  const idInput = el("input", { id: `id-${uid}`, type: "text", maxLength: 80, spellcheck: false, autocomplete: "off",
    placeholder: "e.g. holiday-christmas", dir: "ltr" });
  const visibility = el("select", { id: `vis-${uid}` },
    el("option", { value: "public", textContent: "Public: the assistant can tell customers" }),
    el("option", { value: "internal", textContent: "Internal: guides the assistant, never shown" }));
  const text = el("textarea", { id: `text-${uid}`, rows: 5, maxLength: 4000, dir: "auto",
    placeholder: "The fact, in English, the way the assistant should know it." });
  const save = el("button", { type: "submit", className: "primary", textContent: "Save" });
  const cancel = el("button", { type: "button", className: "secondary", textContent: "Cancel" });
  const form = el("form", { className: "entry-form", hidden: true },
    el("div", { className: "field-row" },
      el("div", { className: "field" }, el("label", { htmlFor: idInput.id, textContent: "ID" }), idInput),
      el("div", { className: "field" }, el("label", { htmlFor: visibility.id, textContent: "Visibility" }), visibility)),
    el("div", { className: "field" }, el("label", { htmlFor: text.id, textContent: "Entry text" }), text),
    el("p", { className: "muted small", textContent: "Plain text. Lines starting with “- ” become a list. No lines starting with # and no lines that are only ---." }),
    el("div", { className: "form-actions" }, save, cancel));

  const fill = (source) => {
    idInput.value = source ? source.id : "";
    visibility.value = source && source.visibility === "internal" ? "internal" : "public";
    text.value = source ? source.text : "";
  };
  const editor = {
    node: form,
    isOpen: () => !form.hidden,
    open({ blank = false, cancellable = true, draft = null, focus = true } = {}) {
      if (form.hidden || draft) fill(draft || (blank ? null : entry));
      cancel.hidden = !cancellable;
      form.hidden = false;
      if (focus) (idInput.value ? text : idInput).focus();
    },
    close() {
      form.hidden = true;
    },
  };
  text.addEventListener("input", () => text.classList.toggle("ar", ARABIC.test(text.value)));
  cancel.addEventListener("click", () => editor.close());
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const draft = { id: idInput.value.trim(), visibility: visibility.value, text: text.value.trim() };
    const problem = !ENTRY_ID.test(draft.id) ? "The ID must be lowercase words joined by hyphens, like holiday-christmas."
      : !draft.text ? "Write the entry text first." : "";
    if (problem) {
      status.textContent = problem;
      status.classList.add("error");
      return;
    }
    decide(e, { decision: "edited", entry: draft }, { status, buttons: form.closest(".learning"), editor });
  });
  return editor;
}

// Save / Edit+Save / Just this once. On success the card collapses (redrawn from the server).
async function decide(e, body, { status, buttons, editor = null }) {
  const card = cards.get(e.id);
  if (card) card.busy = true;
  const controls = buttons.querySelectorAll("button, input, select, textarea");
  controls.forEach((node) => (node.disabled = true));
  status.classList.remove("error");
  status.classList.add("working");
  status.textContent = body.decision === "once" ? "Saving your choice…" : "Saving to the knowledge base…";
  const fail = (message) => {
    controls.forEach((node) => (node.disabled = false));
    status.classList.remove("working");
    status.classList.add("error");
    status.textContent = message;
  };
  try {
    const data = await api(`/escalations/${e.id}/learn`, { method: "POST", body });
    if (!data.ok) {
      if (card) card.busy = false;
      fail(data.error || "Nothing was saved.");
      // The spec: show the error and open Edit, keeping what the owner wrote.
      if (editor) editor.open({ draft: body.entry || null });
      return;
    }
    if (body.decision !== "once") {
      toast("Learned ✓, your assistant now knows this");
      // A short violet glow on the learning card before it collapses.
      const learning = buttons.closest(".learning") || buttons;
      learning.classList.add("learned-glow");
      if (!REDUCED_MOTION.matches) await new Promise((resolve) => setTimeout(resolve, 900));
    }
    if (card) card.busy = false;
    await refresh();
  } catch (error) {
    if (card) card.busy = false;
    fail(error.status === 409 ? `${error.message} Refreshing…` : error.message);
    if (error.status === 409) setTimeout(refresh, 1200);
  }
}

let toastTimer = null;
function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.hidden = false;
  node.classList.remove("show");
  void node.offsetWidth; // restart the animation
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), 4000);
}

// After a decision: one line saying what happened; the details fold away.
function decidedBlock(e) {
  const learned = e.learn_decision === "saved" || e.learn_decision === "edited";
  const line = learned
    ? el("p", { className: "decided learned-line" }, el("span", { textContent: "✦ Learned " }),
      el("code", { textContent: e.learned_entry_id || "" }), el("span", { className: "muted", textContent: " · your assistant now knows this" }))
    : el("p", { className: "decided" }, el("span", { textContent: "Answered just this once" }),
      el("span", { className: "muted", textContent: " · nothing saved" }));
  return line;
}

function handoffPending(e) {
  const giveBack = el("button", { type: "button", className: "secondary", textContent: "Give back to the bot" });
  const form = composer({
    label: "Reply to the customer",
    placeholder: "Sent as-is, with a “Team” label.",
    submitLabel: "Send reply",
    extraButton: giveBack,
    onSubmit: async (text, parts) => {
      setFormBusy(parts, true, "Sending…");
      try {
        const data = await api(`/escalations/${e.id}/reply`, { method: "POST", body: { text } });
        parts.box.value = "";
        setFormBusy(parts, false, "Sent ✓");
        upsertCard(data.escalation);
      } catch (error) {
        if (error.status === 409) refresh();
        showFormError(parts, error);
      }
    },
  });
  giveBack.addEventListener("click", async () => {
    const parts = { form, status: form.querySelector(".form-status") };
    setFormBusy(parts, true, "Giving the chat back to the bot…");
    try {
      const data = await api(`/escalations/${e.id}/give-back`, { method: "POST" });
      upsertCard(data.escalation, { force: true });
      refresh();
    } catch (error) {
      if (error.status === 409) refresh();
      showFormError(parts, error);
    }
  });
  return form;
}

function buildCard(e) {
  const node = el("article", { className: `card kind-${e.kind} status-${e.status}` });
  node.dataset.id = e.id;
  const transcript = el("div", { className: "transcript-wrap" }, renderTranscript(e.messages));

  if (e.kind === "ask_owner" && e.learn_decision) {
    node.classList.add("collapsed");
    const details = el("details", { className: "card-details" },
      el("summary", { textContent: "Conversation and your answer" }), transcript, questionBlock(e), relayBlock(e));
    details.addEventListener("toggle", () => details.open && scrollTranscript(details));
    node.append(cardHeader(e), decidedBlock(e), details);
    return node;
  }
  node.append(cardHeader(e), transcript);

  if (e.kind === "ask_owner") {
    node.append(questionBlock(e));
    if (e.status === "pending") node.append(askOwnerPending(e));
    else node.append(relayBlock(e), learningBlock(e));
  } else if (e.status === "pending") {
    node.append(handoffPending(e));
  } else {
    node.append(el("p", { className: "muted small", textContent: "The bot is answering this customer again." }));
  }
  return node;
}

// Update a card in place where possible, so a half-typed answer is never wiped by polling.
function upsertCard(e, { force = false } = {}) {
  const sig = signature(e);
  const existing = cards.get(e.id);
  if (existing && !force && (existing.busy || existing.signature === sig)) return existing.node;

  if (existing && !force && existing.status === e.status && existing.decision === (e.learn_decision || null)) {
    // Same stage (still waiting, or answered and not yet decided): refresh the transcript and
    // question only, and leave the reply box or a half-written entry alone.
    existing.node.querySelector(".transcript-wrap").replaceChildren(renderTranscript(e.messages));
    const question = existing.node.querySelector(".owner-question");
    if (question) question.textContent = e.question;
    existing.signature = sig;
    scrollTranscript(existing.node);
    return existing.node;
  }

  const node = buildCard(e);
  if (existing) existing.node.replaceWith(node);
  else if (inboxLoaded && e.status === "pending") node.classList.add("arrived"); // slides in, amber flash
  cards.set(e.id, { node, status: e.status, decision: e.learn_decision || null, signature: sig, busy: false });
  scrollTranscript(node);
  return node;
}

function scrollTranscript(node) {
  const wrap = node.querySelector(".transcript-wrap");
  if (wrap && wrap.closest("details:not([open])")) return;
  if (wrap) wrap.scrollTop = wrap.scrollHeight;
}

// Put the cards in order, moving only the ones out of place (moving a node would drop focus).
function arrange(container, nodes) {
  nodes.forEach((node, i) => {
    if (container.children[i] !== node) container.insertBefore(node, container.children[i] || null);
  });
  while (container.children.length > nodes.length) container.lastElementChild.remove();
}

function renderInbox(escalations) {
  const ids = new Set(escalations.map((e) => e.id));
  for (const id of [...cards.keys()]) if (!ids.has(id)) cards.delete(id);

  const pending = [];
  const recent = [];
  for (const e of escalations) (e.status === "pending" ? pending : recent).push(upsertCard(e));
  arrange(pendingEl, pending);
  arrange(recentEl, recent);
  inboxLoaded = true;
  $("pending-empty").hidden = pending.length > 0;
  $("recent-title").hidden = recent.length === 0;

  const count = $("inbox-count");
  count.textContent = String(pending.length);
  count.hidden = pending.length === 0;
  document.title = `${pending.length ? `(${pending.length}) ` : ""}${business.name || "Owner"} · Dashboard`;
}

function renderStats(stats) {
  $("stat-messages").textContent = String(stats.messages_this_week);
  $("stat-answered").textContent = stats.answered_by_bot_pct === null ? "–" : `${stats.answered_by_bot_pct}%`;
  $("stat-learned").textContent = String(stats.questions_learned);
  $("stat-pending").textContent = String(stats.pending);
}

async function refresh() {
  if (refreshing || stopped) return;
  refreshing = true;
  try {
    const [inbox, stats] = await Promise.all([api("/escalations"), api("/stats")]);
    renderInbox(inbox.escalations);
    renderStats(stats);
  } catch {
    // Offline for a moment, or the key was refused (handled in api()): try again on the next tick.
  } finally {
    refreshing = false;
  }
}

// --- Knowledge ------------------------------------------------------------------------------------

function knowledgeEntry(entry) {
  const learned = entry.status === "learned";
  const summary = el("summary", {},
    el("code", { textContent: entry.id }),
    visibilityBadge(entry.visibility),
    learned ? badge("learned", `✦ Learned${entry.learned_at ? ` ${formatDate(entry.learned_at)}` : ""}`) : null);
  const node = el("details", { className: `kb-entry ${entry.visibility}${learned ? " learned" : ""}` }, summary);
  if (learned && entry.source_question) {
    node.append(el("p", { className: "kb-origin" }, el("span", { className: "muted", textContent: "From a customer asking: " }),
      textNode(entry.source_question, "origin-question")));
  }
  node.append(renderEntry(entry.text));
  return node;
}

function formatDate(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString([], { day: "numeric", month: "short" });
}

async function loadKnowledge() {
  const container = $("knowledge");
  try {
    const data = await api("/knowledge");
    $("knowledge-intro").textContent = `${data.entry_count} entries. Public entries can be told to customers; ` +
      "internal ones guide the assistant but are never shown to them.";
    const groups = [];
    if (data.learned.length) {
      const learned = data.learned.map(knowledgeEntry);
      learned.forEach((node) => (node.open = true));
      groups.push(el("section", { className: "kb-section kb-learned" },
        el("h2", { className: "group-title", textContent: `Learned from you (${data.learned.length})` }), ...learned));
    }
    for (const section of data.sections) {
      groups.push(el("section", { className: "kb-section" },
        el("h2", { className: "group-title", textContent: section.title }), ...section.entries.map(knowledgeEntry)));
    }
    container.replaceChildren(...groups);
    $("demo-reset").hidden = !data.can_reset_demo;
  } catch (error) {
    if (error.status !== 403) container.replaceChildren(el("p", { className: "form-status error", textContent: error.message }));
  }
}

// "Reset demo" (demo business only): asks first, then clears the inbox and reloads everything.
function showResetConfirm(show) {
  $("demo-reset-confirm").hidden = !show;
  $("demo-reset-start").hidden = show;
  if (show) $("demo-reset-cancel").focus();
}

$("demo-reset-start").addEventListener("click", () => {
  $("demo-reset-status").textContent = "";
  showResetConfirm(true);
});
$("demo-reset-cancel").addEventListener("click", () => {
  showResetConfirm(false);
  $("demo-reset-start").focus();
});
$("demo-reset-yes").addEventListener("click", async () => {
  const status = $("demo-reset-status");
  const buttons = [$("demo-reset-yes"), $("demo-reset-cancel")];
  buttons.forEach((b) => (b.disabled = true));
  status.classList.remove("error");
  status.classList.add("working");
  status.textContent = "Resetting…";
  try {
    await api("/reset-demo", { method: "POST" });
    showResetConfirm(false);
    status.classList.remove("working");
    status.textContent = "Demo reset ✓ The knowledge base is back to the original and the inbox is empty.";
    await Promise.all([loadKnowledge(), refresh()]);
  } catch (error) {
    status.classList.remove("working");
    status.classList.add("error");
    status.textContent = error.message;
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
});

// --- Share ----------------------------------------------------------------------------------------

function fillShare() {
  const customer = `${location.origin}/b/${encodeURIComponent(SLUG)}`;
  $("share-customer").textContent = customer;
  $("share-owner").textContent = `${location.origin}/owner/${encodeURIComponent(SLUG)}?key=${encodeURIComponent(KEY)}`;
  $("share-bubble").textContent =
    `<script src="https://${location.host}/embed.js?b=${encodeURIComponent(SLUG)}" async></script>`;
  $("share-embed").textContent =
    `<iframe src="https://${location.host}/b/${encodeURIComponent(SLUG)}" style="width:380px;height:600px;border:0;border-radius:16px"></iframe>`;
  const link = $("customer-link");
  link.href = customer;
  link.hidden = false;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Older browsers, or no clipboard permission inside an iframe.
    const area = el("textarea", { value: text });
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

document.querySelectorAll(".copy").forEach((button) => button.addEventListener("click", async () => {
  const ok = await copyText($(button.dataset.copy).textContent);
  button.textContent = ok ? "Copied ✓" : "Select and copy";
  setTimeout(() => (button.textContent = "Copy"), 1800);
}));

// --- Tabs -----------------------------------------------------------------------------------------

const TABS = ["inbox", "knowledge", "share"];

function showTab(name) {
  for (const tab of TABS) {
    $(`tab-${tab}`).setAttribute("aria-selected", String(tab === name));
    $(`tab-${tab}`).tabIndex = tab === name ? 0 : -1;
    $(`panel-${tab}`).hidden = tab !== name;
  }
  if (name === "knowledge") loadKnowledge();
}

TABS.forEach((name, i) => {
  const tab = $(`tab-${name}`);
  tab.addEventListener("click", () => showTab(name));
  tab.addEventListener("keydown", (event) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
    if (!step) return;
    const next = TABS[(i + step + TABS.length) % TABS.length];
    showTab(next);
    $(`tab-${next}`).focus();
  });
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});

// --- Start ----------------------------------------------------------------------------------------

async function init() {
  if (!KEY) {
    stop("This page needs your owner link, which ends in ?key=… Open the dashboard with the full link you were given.");
    return;
  }
  try {
    const data = await api("/knowledge");
    business = { name: data.name };
  } catch (error) {
    if (error.status === 404) stop("No business at this address.");
    else if (error.status !== 403) stop("Couldn't load the dashboard. Check your connection and reload the page.");
    return;
  }
  $("business-name").textContent = business.name;
  $("avatar").textContent = (business.name.trim()[0] || "?").toUpperCase();
  fillShare();
  $("app").hidden = false;
  showTab("inbox");
  await refresh();
  pollTimer = setInterval(refresh, POLL_MS);
}

init();
