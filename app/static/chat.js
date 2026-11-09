// The customer chat page: /b/{slug}, with the "Behind the reply" panel only when ?panel=1.
// The server keeps the conversation; the page only remembers its ID (spec section 6).

const SLUG = decodeURIComponent(location.pathname.split("/")[2] || "");
const API = `/api/b/${encodeURIComponent(SLUG)}`;
const PARAMS = new URLSearchParams(location.search);
const SHOW_PANEL = PARAMS.get("panel") === "1";
// ?embed=1: inside the website bubble (jawab.js), where the Jawab header bar isn't wanted.
// The bubble also passes ?lang= (the website's language, which wins over the one stored here) and
// ?c= (the conversation, which the bubble keeps in the website's own storage: a chat iframe's
// storage is partitioned or cleared by some browsers, the website's isn't).
const EMBEDDED = PARAMS.get("embed") === "1";
// ?frame=1: inside the /try page, which has its own Jawab bar.
const FRAMED = PARAMS.get("frame") === "1";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE = /^\+?[0-9][0-9 ()./-]{5,23}$/; // with 7 to 15 digits, as the server checks

// Tell the bubble around us (jawab.js) what's happening: ready, failed, the conversation, close.
function tellBubble(message) {
  if (EMBEDDED && window.parent !== window) window.parent.postMessage(message, "*");
}
if (FRAMED) document.querySelector(".brandbar")?.remove();
if (EMBEDDED) {
  document.querySelector(".brandbar")?.remove();
  document.querySelector(".layout")?.classList.add("embedded");
  compactHeader();
}

// Phones: "New chat" becomes an icon, so the header keeps room for the name and three languages.
if (!EMBEDDED && window.matchMedia("(max-width: 480px)").matches) iconNewChat();

function svgIcon(path) {
  return `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">` +
    `<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="${path}"/></svg>`;
}

function iconNewChat() {
  const newChat = document.getElementById("new-chat");
  newChat.removeAttribute("data-i18n");
  newChat.dataset.i18nAriaLabel = newChat.dataset.i18nTitle = "newChat";
  newChat.classList.add("icon-button");
  newChat.innerHTML = svgIcon("M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z");
}

// The bubble's small header: "New chat" becomes an icon, and a × asks the bubble (jawab.js) to close the panel.
function compactHeader() {
  const svg = svgIcon;
  iconNewChat();
  const close = document.createElement("button");
  close.type = "button";
  close.id = "embed-close";
  close.className = "ghost-button icon-button";
  close.dataset.i18nAriaLabel = close.dataset.i18nTitle = "closeChat";
  close.innerHTML = svg("M6 6l12 12M18 6L6 18");
  close.addEventListener("click", () => tellBubble({ type: "jawab:close" }));
  document.querySelector(".header-actions").append(close);
}
const CONVERSATION_KEY = `jawab:${SLUG}:conversation`;
const LANG_KEY = "jawab:lang";
const POLL_MS = 3000;
const WAITING_STATES = ["waiting_on_owner", "human_handoff"];
const ARABIC = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]/;

// --- The page's own labels (not the bot's replies) ---------------------------------------------

const LABELS = {
  en: {
    subtitle: "AI receptionist",
    newChat: "New chat",
    closeChat: "Close chat",
    placeholder: "Type a message…",
    inputAria: "Your message",
    send: "Send",
    suggestionsAria: "Suggested questions",
    welcome: "Hi! I'm the assistant for {name}. Ask me about prices, opening hours or services, in your own language.",
    typing: "The assistant is typing",
    sentToOwner: "Sent to the owner",
    ownerReplied: "✓ The owner replied",
    relayedLabel: "From the owner, via Jawab",
    handedOff: "A team member will take it from here.",
    sentToTeam: "Sent to the team. A team member will reply here.",
    team: "Team",
    why: "Why this reply?",
    errorGeneric: "Something went wrong. Please try again.",
    errorNetwork: "Couldn't reach the assistant. Check your connection and try again.",
    emailPrompt: "Leave your email and we'll send you the answer",
    emailAria: "Your email",
    emailSave: "Save",
    emailInvalid: "That doesn't look like an email address.",
    emailSaved: "Thanks! We'll email you the answer too.",
    contactPrompt: "Leave your email or WhatsApp number so the team can contact you about this",
    contactAria: "Your email or WhatsApp number",
    contactInvalid: "Please enter an email address or a phone number.",
    contactSaved: "Thanks! The team will contact you.",
    notFound: "This chat isn't available.",
    footer: "Answers come only from {name}'s own information. When it isn't sure, it asks the team.",
    close: "Close",
    panelTitle: "Behind the reply",
    panelIntro: "Every message gets exactly one action:",
    legend: {
      answer: "from the business's information, citing what it used.",
      ask_owner: "when the information doesn't cover it. It asks instead of guessing.",
      handoff: "to a person for complaints, refunds and big orders.",
    },
    panelHint: "Send a message, then see here why the assistant replied the way it did.",
    knowledgeUsed: "Knowledge used",
    noSources: "No public entries.",
    questionForOwner: "Question sent to the owner (in English)",
    internalRules: (n) => `Also followed ${n} internal rule${n > 1 ? "s" : ""}: the business's private policies, ` +
      "which guide the assistant but never appear in replies. They stay hidden.",
    learned: "✦ Learned",
    actions: {
      answer: { label: "Answer", explain: "Answered from the business's information. Every answer must cite at " +
        "least one public entry; if it can't, the code turns it into a question for the owner instead." },
      ask_owner: { label: "Ask owner", explain: "The information doesn't cover this, or a rule says to check " +
        "first. Instead of guessing, the assistant asks the owner and tells the customer it will get back to them." },
      handoff: { label: "Hand off", explain: "This needs a person (a complaint, a refund, a negotiation or a " +
        "large order), so the assistant hands the chat to the team." },
    },
  },
  el: {
    subtitle: "AI ρεσεψιονίστ",
    newChat: "Νέα συνομιλία",
    closeChat: "Κλείσιμο συνομιλίας",
    placeholder: "Γράψε ένα μήνυμα…",
    inputAria: "Το μήνυμά σου",
    send: "Αποστολή",
    suggestionsAria: "Προτεινόμενες ερωτήσεις",
    welcome: "Γεια σου! Είμαι ο βοηθός του {name}. Ρώτα με για τιμές, ωράριο ή υπηρεσίες, σε όποια γλώσσα θέλεις.",
    typing: "Ο βοηθός γράφει",
    sentToOwner: "Στάλθηκε στον ιδιοκτήτη",
    ownerReplied: "✓ Ο ιδιοκτήτης απάντησε",
    relayedLabel: "Από τον ιδιοκτήτη, μέσω Jawab",
    handedOff: "Ένα μέλος της ομάδας θα συνεχίσει από εδώ.",
    sentToTeam: "Στάλθηκε στην ομάδα. Ένα μέλος της ομάδας θα απαντήσει εδώ.",
    team: "Ομάδα",
    why: "Γιατί αυτή η απάντηση;",
    errorGeneric: "Κάτι πήγε στραβά. Δοκίμασε ξανά.",
    errorNetwork: "Δεν ήταν δυνατή η σύνδεση με τον βοηθό. Έλεγξε τη σύνδεσή σου και δοκίμασε ξανά.",
    emailPrompt: "Άφησε το email σου και θα σου στείλουμε την απάντηση",
    emailAria: "Το email σου",
    emailSave: "Αποθήκευση",
    emailInvalid: "Αυτό δεν μοιάζει με διεύθυνση email.",
    emailSaved: "Ευχαριστούμε! Θα σου στείλουμε την απάντηση και με email.",
    contactPrompt: "Άφησε το email ή το WhatsApp σου για να επικοινωνήσει μαζί σου η ομάδα για αυτό",
    contactAria: "Το email ή το WhatsApp σου",
    contactInvalid: "Γράψε ένα email ή έναν αριθμό τηλεφώνου.",
    contactSaved: "Ευχαριστούμε! Η ομάδα θα επικοινωνήσει μαζί σου.",
    notFound: "Αυτή η συνομιλία δεν είναι διαθέσιμη.",
    footer: "Οι απαντήσεις βγαίνουν μόνο από τις πληροφορίες του {name}. Όταν δεν είναι σίγουρος, ρωτάει την ομάδα.",
    close: "Κλείσιμο",
    panelTitle: "Πίσω από την απάντηση",
    panelIntro: "Κάθε μήνυμα παίρνει ακριβώς μία ενέργεια:",
    legend: {
      answer: "από τις πληροφορίες της επιχείρησης, με αναφορά σε όσα χρησιμοποίησε.",
      ask_owner: "όταν οι πληροφορίες δεν το καλύπτουν. Ρωτάει αντί να μαντεύει.",
      handoff: "σε άνθρωπο, για παράπονα, επιστροφές χρημάτων και μεγάλες παραγγελίες.",
    },
    panelHint: "Στείλε ένα μήνυμα και δες εδώ γιατί ο βοηθός απάντησε έτσι.",
    knowledgeUsed: "Γνώση που χρησιμοποιήθηκε",
    noSources: "Καμία δημόσια καταχώριση.",
    questionForOwner: "Ερώτηση προς τον ιδιοκτήτη (στα αγγλικά)",
    internalRules: (n) => `Ακολούθησε επίσης ${n} ${n > 1 ? "εσωτερικούς κανόνες" : "εσωτερικό κανόνα"}: ` +
      "τις ιδιωτικές πολιτικές της επιχείρησης, που καθοδηγούν τον βοηθό αλλά δεν εμφανίζονται ποτέ στις απαντήσεις. Μένουν κρυφές.",
    learned: "✦ Το έμαθε",
    actions: {
      answer: { label: "Απάντηση", explain: "Απάντηση από τις πληροφορίες της επιχείρησης. Κάθε απάντηση πρέπει να " +
        "στηρίζεται σε τουλάχιστον μία δημόσια καταχώριση· αλλιώς ο κώδικας τη μετατρέπει σε ερώτηση προς τον ιδιοκτήτη." },
      ask_owner: { label: "Ρωτά τον ιδιοκτήτη", explain: "Οι πληροφορίες δεν το καλύπτουν, ή κάποιος κανόνας λέει να " +
        "γίνει πρώτα έλεγχος. Αντί να μαντέψει, ο βοηθός ρωτά τον ιδιοκτήτη και λέει στον πελάτη ότι θα επανέλθει." },
      handoff: { label: "Σε άνθρωπο", explain: "Αυτό χρειάζεται άνθρωπο (παράπονο, επιστροφή χρημάτων, διαπραγμάτευση ή " +
        "μεγάλη παραγγελία), οπότε ο βοηθός δίνει τη συνομιλία στην ομάδα." },
    },
  },
  ar: {
    subtitle: "موظف استقبال ذكي",
    newChat: "محادثة جديدة",
    closeChat: "إغلاق",
    placeholder: "اكتب رسالتك…",
    inputAria: "رسالتك",
    send: "إرسال",
    suggestionsAria: "أسئلة مقترحة",
    welcome: "مرحباً! أنا مساعد {name}. اسألني عن الأسعار أو مواعيد العمل أو الخدمات، بأي لغة تريدها.",
    typing: "المساعد يكتب",
    sentToOwner: "أُرسل السؤال إلى المالك",
    ownerReplied: "✓ ردّ صاحب المتجر",
    relayedLabel: "من صاحب المتجر، عبر جواب",
    handedOff: "سيتابع معك أحد أعضاء الفريق من هنا.",
    sentToTeam: "وصلت رسالتك إلى الفريق، وسيرد عليك أحدهم هنا.",
    team: "الفريق",
    why: "لماذا هذا الرد؟",
    errorGeneric: "حدث خطأ ما. يرجى المحاولة مرة أخرى.",
    errorNetwork: "تعذّر الوصول إلى المساعد. تحقّق من اتصالك وحاول مرة أخرى.",
    emailPrompt: "اترك بريدك الإلكتروني وسنرسل لك الإجابة",
    emailAria: "بريدك الإلكتروني",
    emailSave: "حفظ",
    emailInvalid: "هذا لا يبدو عنوان بريد إلكتروني صحيحاً.",
    emailSaved: "شكراً! سنرسل لك الإجابة عبر البريد الإلكتروني أيضاً.",
    contactPrompt: "اترك بريدك الإلكتروني أو رقم واتساب ليتواصل معك الفريق بخصوص هذا الأمر",
    contactAria: "بريدك الإلكتروني أو رقم واتساب",
    contactInvalid: "يرجى إدخال بريد إلكتروني أو رقم هاتف.",
    contactSaved: "شكراً! سيتواصل معك الفريق.",
    notFound: "هذه المحادثة غير متاحة.",
    footer: "الإجابات مأخوذة فقط من معلومات {name}. وعندما لا يكون متأكداً، يسأل الفريق.",
    close: "إغلاق",
    panelTitle: "خلف الرد",
    panelIntro: "كل رسالة تحصل على إجراء واحد فقط:",
    legend: {
      answer: "من معلومات النشاط التجاري، مع ذكر ما استند إليه.",
      ask_owner: "عندما لا تغطي المعلومات السؤال. يسأل بدلاً من التخمين.",
      handoff: "إلى شخص من الفريق للشكاوى والاسترداد والطلبات الكبيرة.",
    },
    panelHint: "أرسل رسالة، ثم شاهد هنا لماذا ردّ المساعد بهذه الطريقة.",
    knowledgeUsed: "المعلومات المستخدمة",
    noSources: "لا توجد معلومات عامة.",
    questionForOwner: "السؤال المرسل إلى المالك (بالإنجليزية)",
    internalRules: (n) => `اتّبع أيضاً ${n} من القواعد الداخلية: سياسات خاصة توجّه المساعد ولا تظهر أبداً في الردود، وتبقى مخفية.`,
    learned: "✦ مُتعلَّمة",
    actions: {
      answer: { label: "إجابة", explain: "إجابة من معلومات النشاط التجاري. يجب أن تستند كل إجابة إلى معلومة عامة " +
        "واحدة على الأقل؛ وإلا يحوّلها النظام إلى سؤال للمالك." },
      ask_owner: { label: "سؤال المالك", explain: "المعلومات لا تغطي هذا السؤال، أو هناك قاعدة تطلب التحقق أولاً. " +
        "بدلاً من التخمين، يسأل المساعد المالك ويخبر العميل بأنه سيعود إليه." },
      handoff: { label: "تحويل لشخص", explain: "هذا يحتاج إلى شخص (شكوى أو استرداد أو تفاوض أو طلب كبير)، " +
        "لذلك يحوّل المساعد المحادثة إلى الفريق." },
    },
  },
};

// --- Storage that never breaks the page (private mode, blocked cookies) -------------------------

const memory = {};
function load(key) {
  try { return localStorage.getItem(key); } catch { return memory[key] ?? null; }
}
function save(key, value) {
  try {
    if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
  } catch {
    if (value === null) delete memory[key]; else memory[key] = value;
  }
}

// --- State ----------------------------------------------------------------------------------------

const UI_LANGS = ["en", "el", "ar"]; // the page labels exist in these
const URL_LANG = PARAMS.get("lang");
let lang = UI_LANGS.includes(URL_LANG) ? URL_LANG : UI_LANGS.includes(load(LANG_KEY)) ? load(LANG_KEY) : "en";
let business = { name: "", suggestions: [] };
let conversationId = EMBEDDED && UUID.test(PARAMS.get("c") || "") ? PARAMS.get("c") : load(CONVERSATION_KEY);
if (conversationId) save(CONVERSATION_KEY, conversationId);
let conversationState = "bot_active";
let lastId = 0; // highest message ID shown, for polling
const seen = new Set(); // message IDs already on the page
const decisions = []; // bot replies that have panel data: {data, bubble}
let selected = null;
let busy = false;
let pollTimer = null;
let polling = false;
let teamNoteShown = false;

const messagesEl = document.getElementById("messages");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const suggestionsEl = document.getElementById("suggestions");
const panel = document.getElementById("panel");
const panelBody = document.getElementById("panel-body");

const t = (key) => LABELS[lang][key];
const fill = (text) => text.replaceAll("{name}", business.name || "");

// --- Small DOM helpers ----------------------------------------------------------------------------

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

function scrollToEnd() {
  messagesEl.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "end" });
}

// --- Labels ---------------------------------------------------------------------------------------

function applyLabels() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((node) => (node.textContent = fill(t(node.dataset.i18n))));
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => (node.placeholder = t(node.dataset.i18nPlaceholder)));
  document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel)));
  document.querySelectorAll("[data-i18n-title]").forEach((node) => (node.title = t(node.dataset.i18nTitle)));
  document.querySelectorAll(".lang").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
  document.getElementById("footer").textContent = business.name ? fill(t("footer")) : "";
  document.querySelectorAll("[data-label]").forEach((node) => (node.textContent = fill(t(node.dataset.label))));
  if (SHOW_PANEL) selected ? renderPanel(selected) : renderLegend();
}

// --- Messages -------------------------------------------------------------------------------------

function addWelcome() {
  const li = el("li", { className: "message bot welcome-message" });
  const span = el("span", { className: "text", dir: "auto" });
  span.dataset.label = "welcome";
  span.textContent = fill(t("welcome"));
  li.append(span);
  messagesEl.append(li);
}

function addCustomer(text) {
  messagesEl.append(el("li", { className: "message customer" }, textNode(text)));
  scrollToEnd();
}

function addNote(labelOrText, { error = false, label = false, className = "" } = {}) {
  const li = el("li", { className: `message note${error ? " error" : ""} ${className}`.trim(), dir: "auto" });
  if (label) {
    li.dataset.label = labelOrText;
    li.textContent = t(labelOrText);
  } else {
    li.textContent = labelOrText;
  }
  messagesEl.append(li);
  scrollToEnd();
  return li;
}

function addTyping() {
  const li = el("li", { className: "message bot typing" }, el("span"), el("span"), el("span"));
  li.setAttribute("aria-label", t("typing"));
  messagesEl.append(li);
  scrollToEnd();
  return li;
}

// A bot reply. `panelData` is only there for replies to this page's own messages.
function addBot(message, panelData = null) {
  if (seen.has(message.id)) return;
  seen.add(message.id);
  lastId = Math.max(lastId, message.id);
  const bubble = el("li", { className: "message bot" });
  if (message.relayed) {
    // The owner's answer, passed on by the bot: say whose answer it is.
    bubble.classList.add("relayed");
    const label = el("span", { className: "relay-label", dir: "auto" });
    label.dataset.label = "relayedLabel";
    label.textContent = t("relayedLabel");
    bubble.append(label);
    markOwnerReplied();
  }
  bubble.append(textNode(message.text));
  if (message.contacts) {
    // The business's contact line ("For anything urgent, call..."), under replies that need a person.
    bubble.append(el("span", { className: "contacts", textContent: message.contacts, dir: "auto" }));
  }
  if (SHOW_PANEL && panelData) {
    const entry = { data: panelData, bubble };
    const why = el("button", { type: "button", className: "why", dir: "auto" });
    why.dataset.label = "why";
    why.textContent = t("why");
    why.addEventListener("click", () => select(entry, { open: true }));
    bubble.append(why);
    decisions.push(entry);
    messagesEl.append(bubble);
    select(entry);
  } else {
    messagesEl.append(bubble);
  }
  scrollToEnd();
}

function addStaff(message) {
  if (seen.has(message.id)) return;
  seen.add(message.id);
  lastId = Math.max(lastId, message.id);
  const sender = el("span", { className: "sender", dir: "auto" });
  sender.dataset.label = "team";
  sender.textContent = t("team");
  messagesEl.append(el("li", { className: "message staff" }, sender, textNode(message.text)));
  markOwnerReplied(); // the owner's answer can also arrive as a Team message
  scrollToEnd();
}

// "Sent to the owner" (an amber pill with a pulsing dot) becomes "✓ The owner replied".
function addWaitingNote() {
  addNote("sentToOwner", { label: true, className: "status-note waiting" });
}

function markOwnerReplied() {
  messagesEl.querySelectorAll(".status-note.waiting, .status-note.asked").forEach((note) => {
    note.classList.remove("waiting", "asked");
    note.classList.add("replied");
    note.dataset.label = "ownerReplied";
    note.textContent = t("ownerReplied");
  });
}

function addFromServer(message, { includeCustomer = false } = {}) {
  if (message.role === "bot") addBot(message);
  else if (message.role === "staff") addStaff(message);
  else if (includeCustomer && !seen.has(message.id)) {
    seen.add(message.id);
    lastId = Math.max(lastId, message.id);
    addCustomer(message.text);
  } else {
    lastId = Math.max(lastId, message.id); // our own message: already on the page
  }
}

// The business's own offline message ("Chat is offline right now. Call us on..."), in the page's
// language: when the model can't be reached, or the server can't.
function offlineText() {
  const texts = business.offline_message || {};
  return texts[lang] || texts.en || t("errorNetwork");
}

function addOffline(text) {
  messagesEl.append(el("li", { className: "message bot offline" }, textNode(text || offlineText())));
  scrollToEnd();
}

// "Leave your email and we'll send you the answer": under a question for the owner, once.
function addEmailForm() {
  if (!business.email_capture) return;
  addCaptureForm({
    className: "email-capture", prompt: "emailPrompt", aria: "emailAria", invalid: "emailInvalid", saved: "emailSaved",
    input: { type: "email", autocomplete: "email", placeholder: "name@example.com" },
    valid: (value) => EMAIL.test(value) && value.length <= 254,
    path: "email", body: (value) => ({ email: value }),
  });
}

// "Leave your email or WhatsApp number": under a complaint or lead, when the business asks (D-013).
// The server says when (`ask_contact`) and works out which of the two it is.
function addContactForm() {
  addCaptureForm({
    className: "contact-capture", prompt: "contactPrompt", aria: "contactAria", invalid: "contactInvalid",
    saved: "contactSaved", input: { type: "text", autocomplete: "on", placeholder: "name@example.com / +357 99 123456" },
    valid: (value) => (EMAIL.test(value) && value.length <= 254) || (PHONE.test(value)
      && (value.match(/[0-9]/g) || []).length >= 7 && (value.match(/[0-9]/g) || []).length <= 15),
    path: "contact", body: (value) => ({ contact: value }),
  });
}

// One small form in the chat, once per kind: a label, a field, Save, and a status line.
function addCaptureForm(kind) {
  if (messagesEl.querySelector(`.${kind.className}`)) return;
  const li = el("li", { className: `message note email-capture ${kind.className}` });
  const inputId = `${kind.className}-input`;
  const label = el("label", { htmlFor: inputId, dir: "auto" });
  label.dataset.label = kind.prompt;
  label.textContent = t(kind.prompt);
  // noValidate: our own message, in the page's language, instead of the browser's tooltip.
  const row = el("form", { className: "email-row", noValidate: true });
  const field = el("input", { ...kind.input, id: inputId, maxLength: 254, dir: "ltr" });
  field.dataset.i18nAriaLabel = kind.aria;
  field.setAttribute("aria-label", t(kind.aria));
  const saveButton = el("button", { type: "submit", className: "ghost-button" });
  saveButton.dataset.label = "emailSave";
  saveButton.textContent = t("emailSave");
  const status = el("p", { className: "email-status", dir: "auto" });
  status.setAttribute("role", "status");
  row.append(field, saveButton);
  li.append(label, row, status);
  row.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = field.value.trim();
    status.classList.remove("error");
    if (!kind.valid(value)) {
      status.dataset.label = kind.invalid;
      status.textContent = t(kind.invalid);
      status.classList.add("error");
      return;
    }
    saveButton.disabled = true;
    try {
      const response = await fetch(`${API}/conversations/${conversationId}/${kind.path}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(kind.body(value)),
      });
      if (!response.ok) throw new Error(String(response.status));
      const done = el("span", { dir: "auto", textContent: t(kind.saved) });
      done.dataset.label = kind.saved;
      li.classList.add("saved");
      li.replaceChildren(done);
    } catch {
      status.dataset.label = "errorGeneric";
      status.textContent = t("errorGeneric");
      status.classList.add("error");
    } finally {
      saveButton.disabled = false;
    }
  });
  messagesEl.append(li);
  scrollToEnd();
}

// --- The decision panel ---------------------------------------------------------------------------

function select(entry, { open = false } = {}) {
  selected = entry;
  decisions.forEach((d) => d.bubble.classList.toggle("selected", d === entry));
  renderPanel(entry);
  if (open) panel.classList.add("open"); // only matters on phones, where the panel is a sheet
}

function renderLegend() {
  const legend = t("legend");
  const actions = t("actions");
  panelBody.replaceChildren(
    el("p", { textContent: t("panelIntro"), dir: "auto" }),
    el("ul", { className: "actions-legend" },
      ...["answer", "ask_owner", "handoff"].map((a) => el("li", { dir: "auto" },
        el("span", { className: `badge badge-${a}`, textContent: actions[a].label }), " ", legend[a]))),
    el("p", { className: "muted", textContent: t("panelHint"), dir: "auto" }));
}

function renderPanel(entry) {
  const { data } = entry;
  const action = t("actions")[data.action];
  const parts = [
    el("p", { className: "action-head" }, el("span", { className: `badge badge-lg badge-${data.action}`, textContent: action.label })),
    el("p", { textContent: action.explain, dir: "auto" }),
  ];
  if (data.question_for_owner) {
    parts.push(el("h3", { textContent: t("questionForOwner"), dir: "auto" }),
      el("blockquote", { className: "owner-question", textContent: data.question_for_owner, dir: "auto" }));
  }
  parts.push(el("h3", { textContent: t("knowledgeUsed"), dir: "auto" }));
  if (data.sources.length) {
    for (const source of data.sources) {
      const summary = el("summary", {}, el("code", { textContent: source.id }));
      if (source.learned) summary.append(" ", el("span", { className: "badge badge-learned badge-md", textContent: t("learned") }));
      // A learned source glows once, the first time this reply's panel shows it.
      const glow = source.learned && !entry.glowShown ? " glow" : "";
      parts.push(el("details", { className: `source${source.learned ? " learned" : ""}${glow}` }, summary, renderEntry(source.text)));
    }
  } else {
    parts.push(el("p", { className: "muted", textContent: t("noSources"), dir: "auto" }));
  }
  if (data.internal_rules_used) {
    parts.push(el("p", { className: "muted", textContent: t("internalRules")(data.internal_rules_used), dir: "auto" }));
  }
  panelBody.replaceChildren(...parts);
  if (data.sources.some((s) => s.learned)) entry.glowShown = true;
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
  let rows = lines
    .filter((l) => !/^\|[\s:|-]+\|?$/.test(l))
    .map((l) => l.replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
  // Price ladders are one or two long rows; turned on their side they fit the narrow panel.
  if (rows.length <= 3 && rows[0].length > 4) rows = rows[0].map((_, c) => rows.map((row) => row[c] ?? ""));
  const [head, ...body] = rows;
  return el("div", { className: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ...head.map((cell) => el("th", { textContent: cell })))),
    el("tbody", {}, ...body.map((row) => el("tr", {}, ...row.map((cell) => el("td", { textContent: cell })))))));
}

function inline(text) {
  return text.replaceAll("`", "").split(/\*\*(.+?)\*\*/).map((part, i) => (i % 2 ? el("strong", { textContent: part }) : part));
}

// --- Talking to the server ------------------------------------------------------------------------

function setBusy(value) {
  busy = value;
  input.disabled = busy;
  sendButton.disabled = busy;
  suggestionsEl.querySelectorAll(".chip").forEach((chip) => (chip.disabled = busy));
  if (!busy) input.focus({ preventScroll: true });
}

function setConversation(id) {
  conversationId = id;
  save(CONVERSATION_KEY, id);
  tellBubble({ type: "jawab:conversation", id });
}

function setState(state) {
  if (state !== "human_handoff") teamNoteShown = false;
  if (state !== "waiting_on_owner") {
    // No longer waiting (e.g. the owner sent nothing to the customer): the dot stops pulsing.
    messagesEl.querySelectorAll(".status-note.waiting").forEach((note) => {
      note.classList.remove("waiting");
      note.classList.add("asked");
    });
  }
  conversationState = state;
  if (WAITING_STATES.includes(state)) startPolling(); else stopPolling();
}

async function readError(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
  } catch { /* not JSON */ }
  return t("errorGeneric");
}

async function send(text) {
  text = text.trim();
  if (!text || busy) return;
  addCustomer(text);
  input.value = "";
  input.classList.remove("ar");
  setBusy(true);
  const typing = addTyping();

  try {
    const response = await fetch(`${API}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, message: text, lang }),
    });
    if (!response.ok) {
      typing.remove();
      if (response.status >= 500) {
        // The model or the server is down: the business's offline message, never an error.
        let detail = null;
        try { const data = await response.json(); if (data.offline) detail = data.detail; } catch { /* not JSON */ }
        addOffline(detail);
      } else {
        addNote(await readError(response), { error: true });
      }
      return;
    }
    const data = await response.json();
    typing.remove();
    setConversation(data.conversation_id);

    if (data.message) {
      addBot({ ...data.message, contacts: data.contacts }, data.panel);
      if (data.message.action === "ask_owner") {
        addWaitingNote();
        if (data.ask_email) addEmailForm();
      } else if (data.message.action === "handoff" && data.state === "human_handoff") {
        addNote("handedOff", { label: true, className: "status-note" });
        teamNoteShown = true;
      }
      if (data.ask_contact) addContactForm();
    } else if (data.state === "human_handoff" && !teamNoteShown) {
      // A person has taken over: the message went to the team, and the bot stays quiet.
      addNote("sentToTeam", { label: true, className: "status-note" });
      teamNoteShown = true;
    }
    setState(data.state);
  } catch {
    typing.remove();
    addOffline();
  } finally {
    setBusy(false);
  }
}

async function poll() {
  if (polling || busy || !conversationId) return;
  polling = true;
  try {
    const response = await fetch(`${API}/conversations/${conversationId}/messages?after=${lastId}`);
    if (!response.ok) return;
    const data = await response.json();
    data.messages.forEach((m) => addFromServer(m));
    setState(data.state);
  } catch {
    // Offline for a moment: try again on the next tick.
  } finally {
    polling = false;
  }
}

function startPolling() {
  if (!pollTimer) pollTimer = setInterval(poll, POLL_MS);
}

function stopPolling() {
  clearInterval(pollTimer);
  pollTimer = null;
}

// Reloading the page shows the same conversation, fetched from the server.
async function restore() {
  if (!conversationId) return;
  try {
    const response = await fetch(`${API}/conversations/${conversationId}/messages?after=0`);
    if (response.status === 404 || response.status === 422) {
      setConversation(null);
      return;
    }
    if (!response.ok) return;
    const data = await response.json();
    data.messages.forEach((m) => addFromServer(m, { includeCustomer: true }));
    // Still waiting on someone: say so again, since the notes aren't stored.
    if (data.state === "waiting_on_owner") {
      addWaitingNote();
      if (data.email_capture && !data.email_saved) addEmailForm();
    }
    if (data.state === "human_handoff") {
      addNote("handedOff", { label: true, className: "status-note" });
      teamNoteShown = true;
    }
    if (data.ask_contact) addContactForm();
    setState(data.state);
  } catch { /* keep the ID; the next message continues the conversation */ }
}

function resetChat() {
  stopPolling();
  setConversation(null);
  conversationState = "bot_active";
  lastId = 0;
  seen.clear();
  decisions.length = 0;
  selected = null;
  teamNoteShown = false;
  messagesEl.replaceChildren();
  addWelcome();
  if (SHOW_PANEL) renderLegend();
  panel.classList.remove("open");
  input.value = "";
  setBusy(false);
}

// A list, or {lang: [...]} for chips in the page's language.
function suggestionList() {
  const all = business.suggestions || [];
  return Array.isArray(all) ? all : (all[lang] || all.en || []);
}

function renderSuggestions() {
  const list = suggestionList();
  suggestionsEl.replaceChildren(...list.map((text) => {
    const chip = el("button", { type: "button", className: "chip", textContent: text, dir: "auto" });
    if (ARABIC.test(text)) chip.classList.add("ar");
    chip.title = text; // long chips end in "…" on phones
    chip.addEventListener("click", () => send(text));
    return chip;
  }));
  suggestionsEl.hidden = list.length === 0;
  fitChips();
}

// Phones and the bubble: chips wrap onto at most two rows; whole chips that don't fit are hidden
// (never cut in half, and not reachable by Tab while invisible).
const COMPACT_CHIPS = window.matchMedia("(max-width: 600px)");
function fitChips() {
  const chips = [...suggestionsEl.querySelectorAll(".chip")];
  const compact = (EMBEDDED || COMPACT_CHIPS.matches) && !suggestionsEl.hidden;
  chips.forEach((chip) => (chip.hidden = compact)); // then shown one by one below
  if (!compact) return;
  // In order, keep each chip that lands on the first two rows; a later, shorter chip can still
  // fill a gap left by a long one that didn't fit.
  const rows = [];
  for (const chip of chips) {
    chip.hidden = false;
    // Relative to the row box: the box itself moves up as it grows (it sits above the input).
    const top = Math.round(chip.getBoundingClientRect().top - suggestionsEl.getBoundingClientRect().top);
    if (!rows.includes(top)) {
      if (rows.length >= 2) { chip.hidden = true; continue; }
      rows.push(top);
    }
  }
}
window.addEventListener("resize", fitChips);
document.fonts?.ready.then(fitChips); // widths change once the web fonts arrive

async function loadBusiness() {
  const response = await fetch(`${API}/public`);
  if (!response.ok) throw new Error("not found");
  business = await response.json();
  document.title = business.name;
  document.getElementById("business-name").textContent = business.name;
  document.getElementById("avatar").textContent = (business.name.trim()[0] || "?").toUpperCase();
  applyBusinessLanguages();
  renderSuggestions();
}

// A business shows the page in its own page languages (its knowledge base's `ui_languages:` line,
// else `languages:`), as far as the page has labels for them. The bot itself still replies in
// whatever language a customer writes, Arabic included.
function applyBusinessLanguages() {
  const offered = (business.ui_languages || business.languages || []).filter((code) => UI_LANGS.includes(code));
  const languages = offered.length ? offered : ["en"];
  document.querySelectorAll(".lang").forEach((button) => { button.hidden = !languages.includes(button.dataset.lang); });
  const toggle = document.querySelector(".lang-toggle");
  if (toggle) toggle.hidden = languages.length < 2;
  if (!languages.includes(lang)) lang = languages.includes("en") ? "en" : languages[0];
}

// --- Wiring ---------------------------------------------------------------------------------------

form.addEventListener("submit", (event) => {
  event.preventDefault();
  send(input.value);
});
input.addEventListener("input", () => input.classList.toggle("ar", ARABIC.test(input.value)));
document.getElementById("new-chat").addEventListener("click", resetChat);
document.getElementById("panel-close").addEventListener("click", () => panel.classList.remove("open"));
document.querySelectorAll(".lang").forEach((button) => button.addEventListener("click", () => {
  lang = button.dataset.lang;
  save(LANG_KEY, lang);
  applyLabels();
  if (!Array.isArray(business.suggestions)) renderSuggestions();
}));
// The bubble hands over a message the customer typed before this chat was ready.
if (EMBEDDED) {
  window.addEventListener("message", (event) => {
    if (event.source !== window.parent || !event.data || event.data.type !== "jawab:send") return;
    if (typeof event.data.text === "string" && event.data.text.trim()) send(event.data.text.slice(0, 500));
  });
}
// Catch up straight away when the customer comes back to the tab.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && WAITING_STATES.includes(conversationState)) poll();
});

// Phones: when the keyboard opens, shrink the page to the visible area so the input stays above
// the keyboard (iOS Safari doesn't resize the page itself), and keep the latest message in view.
function fitToVisibleArea() {
  const viewport = window.visualViewport;
  if (!viewport) return;
  if (viewport.scale > 1.01) { // pinch-zoomed, not a keyboard: leave the page its normal height
    document.documentElement.style.removeProperty("--app-height");
    return;
  }
  document.documentElement.style.setProperty("--app-height", `${Math.round(viewport.height)}px`);
  if (window.scrollY !== 0) window.scrollTo(0, 0);
  if (document.activeElement?.id === "input") scrollToEnd();
}
window.visualViewport?.addEventListener("resize", fitToVisibleArea);
fitToVisibleArea();

async function init() {
  if (SHOW_PANEL) {
    panel.hidden = false;
    document.getElementById("layout").classList.add("with-panel");
  }
  applyLabels();
  setBusy(true);
  try {
    await loadBusiness();
  } catch {
    addNote("notFound", { error: true, label: true });
    tellBubble({ type: "jawab:failed" });
    return;
  }
  addWelcome();
  applyLabels();
  await restore();
  setBusy(false);
  tellBubble({ type: "jawab:ready" });
}

init();
