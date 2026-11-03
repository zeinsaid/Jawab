// The onboarding page: /start (spec section 8). Name + paste (quick) or a short interview (full),
// then the draft to review, then the links. The server keeps the session; the page remembers its ID.

const SESSION_KEY = "jawab:onboarding";
const LANG_KEY = "jawab:lang";
const ARABIC = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]/;
const CHECK_DELAY_MS = 500;

const LABELS = {
  en: {
    tagline: "Create your AI receptionist",
    stepSetup: "Your info", stepInterview: "Questions", stepDraft: "Review", stepLive: "Live",
    setupTitle: "Get a working assistant in about five minutes",
    introQuick: "Paste what you already have. The assistant asks a few short questions to fill the gaps, " +
      "then writes everything up for you to check.",
    introFull: "No list? No problem. Answer a short chat interview about your business, then check what it wrote.",
    nameLabel: "Business name",
    namePlaceholder: "e.g. Noor Tailoring",
    pasteLabel: "Paste your price list, menu, website text or notes",
    pastePlaceholder: "Prices, opening hours, address, what you do and don't do…",
    create: "Create my assistant",
    startInterview: "Start the interview",
    toFull: "No list? Do a short interview instead",
    toQuick: "Have a list? Paste it instead",
    needName: "Enter your business name.",
    needPaste: "Paste your list or notes, or do the short interview instead.",
    progress: (n, total) => `Topics covered: ${n} of ${total}`,
    skip: "Skip to draft",
    replyPlaceholder: "Your answer…",
    send: "Send",
    you: "You",
    interviewDone: "All set. Writing your knowledge base now.",
    draftTitle: "Check your assistant's knowledge",
    draftIntro: (n) => `${n} entries. Public ones can be told to customers; internal ones are rules the ` +
      "assistant follows but never says. Fix anything with Edit raw.",
    openQuestions: "Open questions",
    openQuestionsHint: "Things to settle later. Until then the assistant asks you when customers ask about them.",
    errorsTitle: "Fix these before publishing",
    editRaw: "Edit raw",
    hideRaw: "Hide raw text",
    rawHint: "The cards and the checks update as you type.",
    publish: "Publish",
    public: "Public",
    internal: "Internal",
    placeholder: "To confirm",
    liveTitle: "Your assistant is live 🎉",
    liveIntro: (name) => `${name} now answers customers from what you just checked. Questions it can't answer ` +
      "come to your owner page.",
    tryIt: "Try it now",
    customerLink: "Customer link",
    customerLinkHint: "Share it anywhere: WhatsApp status, Instagram bio, a QR code at the counter.",
    ownerLink: "Your owner link",
    ownerLinkHint: "Keep this private. Anyone with this link can answer your customers and change what the assistant knows.",
    embed: "Website widget",
    embedHint: "Paste this into your website's HTML to show the chat there.",
    copy: "Copy", copied: "Copied ✓", copyFailed: "Select and copy",
    startOver: "Start over with another business",
    startOverSure: "Sure? This page forgets the current setup. Click again",
    reading: "Reading your price list…",
    gettingReady: "Getting the interview ready…",
    thinking: "Thinking of the next question…",
    writing: "Writing your knowledge base…",
    writingSub: "This usually takes about a minute.",
    publishing: "Publishing…",
    errorGeneric: "Something went wrong. Please try again.",
    errorNetwork: "Couldn't reach the server. Check your connection and try again.",
  },
  el: {
    tagline: "Φτιάξε τον AI ρεσεψιονίστ σου",
    stepSetup: "Πληροφορίες", stepInterview: "Ερωτήσεις", stepDraft: "Έλεγχος", stepLive: "Σε λειτουργία",
    setupTitle: "Ένας βοηθός που δουλεύει, σε περίπου πέντε λεπτά",
    introQuick: "Επικόλλησε ό,τι έχεις ήδη. Ο βοηθός κάνει λίγες σύντομες ερωτήσεις για να συμπληρώσει τα κενά " +
      "και μετά τα γράφει όλα για να τα ελέγξεις.",
    introFull: "Δεν έχεις λίστα; Κανένα πρόβλημα. Απάντησε σε μια σύντομη συνέντευξη για την επιχείρησή σου και μετά έλεγξε τι έγραψε.",
    nameLabel: "Όνομα επιχείρησης",
    namePlaceholder: "π.χ. Noor Tailoring",
    pasteLabel: "Επικόλλησε τον τιμοκατάλογο, το μενού, το κείμενο της ιστοσελίδας ή σημειώσεις",
    pastePlaceholder: "Τιμές, ωράριο, διεύθυνση, τι κάνεις και τι όχι…",
    create: "Φτιάξε τον βοηθό μου",
    startInterview: "Ξεκίνα τη συνέντευξη",
    toFull: "Δεν έχεις λίστα; Κάνε μια σύντομη συνέντευξη",
    toQuick: "Έχεις λίστα; Επικόλλησέ την",
    needName: "Γράψε το όνομα της επιχείρησής σου.",
    needPaste: "Επικόλλησε τη λίστα ή τις σημειώσεις σου, ή κάνε τη σύντομη συνέντευξη.",
    progress: (n, total) => `Θέματα που καλύφθηκαν: ${n} από ${total}`,
    skip: "Πήγαινε στο προσχέδιο",
    replyPlaceholder: "Η απάντησή σου…",
    send: "Αποστολή",
    you: "Εσύ",
    interviewDone: "Έτοιμο. Γράφω τώρα τη βάση γνώσεών σου.",
    draftTitle: "Έλεγξε τι ξέρει ο βοηθός σου",
    draftIntro: (n) => `${n} καταχωρίσεις. Οι δημόσιες μπορούν να ειπωθούν στους πελάτες· οι εσωτερικές είναι κανόνες ` +
      "που ο βοηθός ακολουθεί αλλά δεν λέει ποτέ. Διόρθωσε ό,τι θέλεις με την Επεξεργασία κειμένου.",
    openQuestions: "Ανοιχτές ερωτήσεις",
    openQuestionsHint: "Πράγματα που θα ξεκαθαρίσεις αργότερα. Μέχρι τότε ο βοηθός σε ρωτάει όταν τα ρωτούν οι πελάτες.",
    errorsTitle: "Διόρθωσε αυτά πριν από τη δημοσίευση",
    editRaw: "Επεξεργασία κειμένου",
    hideRaw: "Απόκρυψη κειμένου",
    rawHint: "Οι κάρτες και οι έλεγχοι ενημερώνονται καθώς γράφεις.",
    publish: "Δημοσίευση",
    public: "Δημόσια",
    internal: "Εσωτερική",
    placeholder: "Προς επιβεβαίωση",
    liveTitle: "Ο βοηθός σου είναι σε λειτουργία 🎉",
    liveIntro: (name) => `Το ${name} απαντά τώρα στους πελάτες με βάση όσα μόλις έλεγξες. Οι ερωτήσεις που δεν ` +
      "μπορεί να απαντήσει έρχονται στη σελίδα του ιδιοκτήτη.",
    tryIt: "Δοκίμασέ το τώρα",
    customerLink: "Σύνδεσμος για πελάτες",
    customerLinkHint: "Μοιράσου τον παντού: στο WhatsApp, στο Instagram, σε έναν κωδικό QR στον πάγκο.",
    ownerLink: "Ο σύνδεσμός σου ως ιδιοκτήτης",
    ownerLinkHint: "Κράτησέ τον ιδιωτικό. Όποιος έχει αυτόν τον σύνδεσμο μπορεί να απαντά στους πελάτες σου και να αλλάζει όσα ξέρει ο βοηθός.",
    embed: "Widget για την ιστοσελίδα",
    embedHint: "Επικόλλησε αυτό στον κώδικα HTML της ιστοσελίδας σου για να εμφανιστεί εκεί η συνομιλία.",
    copy: "Αντιγραφή", copied: "Αντιγράφηκε ✓", copyFailed: "Επίλεξε και αντίγραψε",
    startOver: "Ξεκίνα από την αρχή με άλλη επιχείρηση",
    startOverSure: "Σίγουρα; Η σελίδα θα ξεχάσει την τρέχουσα ρύθμιση. Πάτα ξανά",
    reading: "Διαβάζω τον τιμοκατάλογό σου…",
    gettingReady: "Ετοιμάζω τη συνέντευξη…",
    thinking: "Σκέφτομαι την επόμενη ερώτηση…",
    writing: "Γράφω τη βάση γνώσεών σου…",
    writingSub: "Συνήθως παίρνει περίπου ένα λεπτό.",
    publishing: "Δημοσίευση…",
    errorGeneric: "Κάτι πήγε στραβά. Δοκίμασε ξανά.",
    errorNetwork: "Δεν ήταν δυνατή η σύνδεση με τον διακομιστή. Έλεγξε τη σύνδεσή σου και δοκίμασε ξανά.",
  },
  ar: {
    tagline: "أنشئ موظف الاستقبال الذكي الخاص بك",
    stepSetup: "معلوماتك", stepInterview: "أسئلة", stepDraft: "مراجعة", stepLive: "جاهز",
    setupTitle: "احصل على مساعد جاهز للعمل في نحو خمس دقائق",
    introQuick: "الصق ما لديك بالفعل. سيطرح المساعد بعض الأسئلة القصيرة لإكمال الناقص، ثم يكتب كل شيء لتراجعه.",
    introFull: "ليست لديك قائمة؟ لا مشكلة. أجب عن مقابلة قصيرة عن نشاطك التجاري، ثم راجع ما كُتب.",
    nameLabel: "اسم النشاط التجاري",
    namePlaceholder: "مثال: خياطة نور",
    pasteLabel: "الصق قائمة أسعارك أو قائمة الطعام أو نص موقعك أو ملاحظاتك",
    pastePlaceholder: "الأسعار، مواعيد العمل، العنوان، ما تقدّمه وما لا تقدّمه…",
    create: "أنشئ مساعدي",
    startInterview: "ابدأ المقابلة",
    toFull: "ليست لديك قائمة؟ أجرِ مقابلة قصيرة بدلاً من ذلك",
    toQuick: "لديك قائمة؟ الصقها بدلاً من ذلك",
    needName: "أدخل اسم نشاطك التجاري.",
    needPaste: "الصق قائمتك أو ملاحظاتك، أو أجرِ المقابلة القصيرة بدلاً من ذلك.",
    progress: (n, total) => `المواضيع المكتملة: ${n} من ${total}`,
    skip: "انتقل إلى المسودة",
    replyPlaceholder: "إجابتك…",
    send: "إرسال",
    you: "أنت",
    interviewDone: "تم. جارٍ كتابة قاعدة المعرفة الآن.",
    draftTitle: "راجع ما يعرفه مساعدك",
    draftIntro: (n) => `${n} معلومة. المعلومات العامة يمكن إخبار العملاء بها، والداخلية قواعد يتّبعها ` +
      "المساعد ولا يقولها أبداً. عدّل أي شيء من «تعديل النص».",
    openQuestions: "أسئلة مفتوحة",
    openQuestionsHint: "أمور تُحسم لاحقاً. حتى ذلك الحين يسألك المساعد عندما يسأل العملاء عنها.",
    errorsTitle: "أصلح هذه قبل النشر",
    editRaw: "تعديل النص",
    hideRaw: "إخفاء النص",
    rawHint: "تتحدّث البطاقات والفحوصات أثناء الكتابة.",
    publish: "انشر",
    public: "عامة",
    internal: "داخلية",
    placeholder: "بانتظار التأكيد",
    liveTitle: "مساعدك يعمل الآن 🎉",
    liveIntro: (name) => `أصبح ${name} يجيب العملاء مما راجعته للتو. الأسئلة التي لا يستطيع الإجابة عنها ` +
      "تصل إلى صفحة المالك.",
    tryIt: "جرّبه الآن",
    customerLink: "رابط العملاء",
    customerLinkHint: "شاركه في أي مكان: حالة واتساب، نبذة إنستغرام، أو رمز QR عند المحاسبة.",
    ownerLink: "رابط المالك",
    ownerLinkHint: "احتفظ به سرّاً. أي شخص لديه هذا الرابط يستطيع الرد على عملائك وتغيير ما يعرفه المساعد.",
    embed: "أداة الموقع",
    embedHint: "الصق هذا في كود HTML لموقعك لتظهر المحادثة هناك.",
    copy: "نسخ", copied: "تم النسخ ✓", copyFailed: "حدّد وانسخ",
    startOver: "ابدأ من جديد لنشاط آخر",
    startOverSure: "متأكد؟ ستنسى الصفحة الإعداد الحالي. اضغط مرة أخرى",
    reading: "جارٍ قراءة قائمة أسعارك…",
    gettingReady: "جارٍ تجهيز المقابلة…",
    thinking: "جارٍ التفكير في السؤال التالي…",
    writing: "جارٍ كتابة قاعدة المعرفة…",
    writingSub: "يستغرق هذا عادةً نحو دقيقة.",
    publishing: "جارٍ النشر…",
    errorGeneric: "حدث خطأ ما. يرجى المحاولة مرة أخرى.",
    errorNetwork: "تعذّر الوصول إلى الخادم. تحقّق من اتصالك وحاول مرة أخرى.",
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
let lang = UI_LANGS.includes(load(LANG_KEY)) ? load(LANG_KEY) : "en";
let mode = "quick";
let step = "setup";
let sessionId = load(SESSION_KEY);
let covered = [];
let topics = [];
let done = false;
let kbText = "";
let draftErrors = [];
let draftSections = [];
let openQuestions = [];
let published = null;
let businessName = "";
let busy = false;
let checkTimer = null;
let checkSeq = 0;

const $ = (id) => document.getElementById(id);
const t = (key) => LABELS[lang][key];

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

function markArabic(input) {
  input.classList.toggle("ar", ARABIC.test(input.value));
}

// --- Labels and language --------------------------------------------------------------------------

function applyLabels() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((node) => (node.textContent = t(node.dataset.i18n)));
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => (node.placeholder = t(node.dataset.i18nPlaceholder)));
  document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel)));
  document.querySelectorAll(".lang").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
  $("setup-intro").textContent = t(mode === "quick" ? "introQuick" : "introFull");
  $("create").textContent = t(mode === "quick" ? "create" : "startInterview");
  $("switch-mode").textContent = t(mode === "quick" ? "toFull" : "toQuick");
  $("start-over").textContent = t("startOver");
  $("raw-block").hidden || ($("toggle-raw").textContent = t("hideRaw"));
  renderProgress();
  if (step === "draft") renderDraft();
  if (published) $("live-intro").textContent = t("liveIntro")(businessName);
  if (!$("working").hidden && workingKey) showWorking(workingKey, workingSubKey);
}

function setLang(value) {
  lang = value;
  save(LANG_KEY, lang);
  applyLabels();
}

// --- Steps ----------------------------------------------------------------------------------------

const STEPS = ["setup", "interview", "draft", "live"];

function showStep(name) {
  step = name;
  for (const s of STEPS) $(`step-${s}`).hidden = s !== name;
  const index = STEPS.indexOf(name);
  document.querySelectorAll("#steps li").forEach((li, i) => {
    li.classList.toggle("current", i === index);
    li.classList.toggle("past", i < index);
    if (i === index) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
  });
  $("start-over").hidden = name === "setup";
  window.scrollTo({ top: 0 });
}

// --- Talking to the server ------------------------------------------------------------------------

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, body) {
  let response;
  try {
    response = await fetch(`/api/onboarding${path}`, body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, t("errorNetwork"));
  }
  if (!response.ok) {
    let message = t("errorGeneric");
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch { /* not JSON */ }
    throw new ApiError(response.status, message);
  }
  return response.json();
}

let workingKey = null;
let workingSubKey = null;
function showWorking(key, subKey = null) {
  workingKey = key;
  workingSubKey = subKey;
  $("working-text").textContent = t(key);
  $("working-sub").textContent = subKey ? t(subKey) : "";
  $("working").hidden = false;
}
function hideWorking() {
  workingKey = workingSubKey = null;
  $("working").hidden = true;
}

function setStatus(id, message, { error = false } = {}) {
  const node = $(id);
  node.textContent = message || "";
  node.classList.toggle("error", error && !!message);
}

// --- Step 1: setup --------------------------------------------------------------------------------

function setMode(value) {
  mode = value;
  $("paste-block").hidden = mode !== "quick";
  setStatus("setup-status", "");
  applyLabels();
}

async function create(event) {
  event.preventDefault();
  if (busy) return;
  const name = $("business-name").value.trim();
  const pasted = $("paste").value.trim();
  if (!name) { setStatus("setup-status", t("needName"), { error: true }); $("business-name").focus(); return; }
  if (mode === "quick" && !pasted) { setStatus("setup-status", t("needPaste"), { error: true }); $("paste").focus(); return; }
  setStatus("setup-status", "");
  busy = true;
  showWorking(mode === "quick" ? "reading" : "gettingReady");
  try {
    const data = await api("", { business_name: name, mode, pasted_text: mode === "quick" ? pasted : null });
    sessionId = data.session_id;
    save(SESSION_KEY, sessionId);
    businessName = name;
    covered = data.covered;
    topics = data.topics;
    done = data.done;
    renderTranscript(data.transcript);
    renderProgress();
    showStep("interview");
    $("reply").focus();
  } catch (error) {
    setStatus("setup-status", error.message, { error: true });
  } finally {
    busy = false;
    hideWorking();
  }
}

// --- Step 2: the interview ------------------------------------------------------------------------

function scrollToEnd() {
  const list = $("messages");
  list.scrollTop = list.scrollHeight;
}

function addOwner(text, { clamp = false } = {}) {
  const li = el("li", { className: `message customer${clamp ? " clamp" : ""}` }, textNode(text));
  if (clamp) li.addEventListener("click", () => li.classList.toggle("clamp")); // the paste: tap to see it all
  $("messages").append(li);
  scrollToEnd();
}

function addInterviewer(text) {
  $("messages").append(el("li", { className: "message bot" }, textNode(text)));
  scrollToEnd();
}

function renderTranscript(transcript) {
  $("messages").replaceChildren();
  transcript.forEach((turn, i) => {
    if (turn.role === "interviewer") addInterviewer(turn.text);
    else addOwner(turn.text, { clamp: i === 0 && turn.text.length > 300 });
  });
}

function addThinking() {
  const li = el("li", { className: "message note thinking", id: "thinking" },
    el("span", { className: "spinner small", ariaHidden: "true" }), " ", t("thinking"));
  $("messages").append(li);
  scrollToEnd();
  return li;
}

function renderProgress() {
  const total = topics.length;
  const n = covered.filter((c) => topics.includes(c)).length;
  $("progress-label").textContent = total ? t("progress")(n, total) : "";
  $("progress-bar").style.width = total ? `${Math.round((100 * n) / total)}%` : "0";
  $("progress").setAttribute("aria-valuemax", String(total));
  $("progress").setAttribute("aria-valuenow", String(n));
}

function setInterviewBusy(value) {
  busy = value;
  $("send").disabled = value;
  $("skip").disabled = value;
  $("reply").disabled = value;
}

async function sendReply(event) {
  event.preventDefault();
  const text = $("reply").value.trim();
  if (!text || busy || done) return;
  setStatus("interview-status", "");
  setInterviewBusy(true);
  addOwner(text);
  $("reply").value = "";
  autosize();
  const thinking = addThinking();
  try {
    const data = await api(`/${sessionId}/reply`, { text });
    thinking.remove();
    addInterviewer(data.interviewer_message);
    covered = data.covered;
    done = data.done;
    renderProgress();
  } catch (error) {
    thinking.remove();
    // Nothing was saved: put the answer back so it can be sent again.
    $("messages").lastElementChild?.remove();
    $("reply").value = text;
    autosize();
    setStatus("interview-status", error.message, { error: true });
    if (error.status === 409) await resume();
  } finally {
    setInterviewBusy(false);
  }
  if (done) {
    $("messages").append(el("li", { className: "message note status-note", textContent: t("interviewDone") }));
    scrollToEnd();
    setTimeout(writeDraft, 700);
  } else {
    $("reply").focus();
  }
}

function autosize() {
  const box = $("reply");
  box.style.height = "auto";
  box.style.height = `${Math.min(box.scrollHeight, 160)}px`;
  markArabic(box);
}

// --- Step 3: the draft ----------------------------------------------------------------------------

async function writeDraft() {
  if (busy) return;
  setInterviewBusy(true);
  setStatus("interview-status", "");
  showWorking("writing", "writingSub");
  try {
    const data = await api(`/${sessionId}/draft`, {});
    useDraft(data);
    showStep("draft");
  } catch (error) {
    setStatus(step === "draft" ? "draft-status" : "interview-status", error.message, { error: true });
  } finally {
    setInterviewBusy(false);
    hideWorking();
    if (step === "draft") renderDraft(); // Publish was disabled while busy
  }
}

function useDraft(data) {
  kbText = data.kb_markdown;
  openQuestions = data.open_questions || [];
  draftErrors = data.errors || [];
  draftSections = data.sections || [];
  $("raw").value = kbText;
  renderDraft();
}

function visibilityBadge(visibility) {
  return el("span", { className: `badge badge-${visibility}`, textContent: t(visibility) });
}

function card(entry) {
  const summary = el("summary", {},
    el("code", { textContent: entry.id, dir: "ltr" }),
    entry.status === "placeholder" ? el("span", { className: "badge badge-placeholder", textContent: t("placeholder") }) : null,
    visibilityBadge(entry.visibility));
  const node = el("details", { className: `kb-entry ${entry.visibility}`, open: true, dir: "ltr" }, summary);
  node.append(renderEntry(entry.text));
  return node;
}

function renderDraft() {
  const count = draftSections.reduce((n, s) => n + s.entries.length, 0);
  $("draft-intro").textContent = t("draftIntro")(count);

  $("open-questions").hidden = !openQuestions.length;
  $("open-questions-list").replaceChildren(...openQuestions.map((q) => el("li", {}, textNode(q))));

  $("kb-errors").hidden = !draftErrors.length;
  $("kb-errors-list").replaceChildren(...draftErrors.map((e) => el("li", { textContent: e, dir: "ltr" })));

  $("cards").replaceChildren(...draftSections.map((section) => el("section", { className: "kb-section" },
    el("h3", { className: "group-title", textContent: section.title, dir: "auto" }), ...section.entries.map(card))));

  $("publish").disabled = busy || draftErrors.length > 0 || !kbText.trim();
}

function toggleRaw() {
  const block = $("raw-block");
  block.hidden = !block.hidden;
  $("toggle-raw").textContent = t(block.hidden ? "editRaw" : "hideRaw");
  $("toggle-raw").setAttribute("aria-expanded", String(!block.hidden));
  if (!block.hidden) $("raw").focus();
}

function rawChanged() {
  kbText = $("raw").value;
  $("publish").disabled = true; // until the check comes back
  clearTimeout(checkTimer);
  checkTimer = setTimeout(checkRaw, CHECK_DELAY_MS);
}

async function checkRaw() {
  const seq = ++checkSeq;
  if (!kbText.trim()) {
    draftErrors = ["The knowledge base is empty."];
    draftSections = [];
    renderDraft();
    return;
  }
  try {
    const data = await api(`/${sessionId}/check`, { kb_markdown: kbText });
    if (seq !== checkSeq) return; // a newer edit is being checked
    draftErrors = data.errors;
    draftSections = data.sections;
    setStatus("draft-status", "");
    renderDraft();
  } catch (error) {
    if (seq === checkSeq) setStatus("draft-status", error.message, { error: true });
  }
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
  const [head = [], ...body] = rows;
  return el("div", { className: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ...head.map((cell) => el("th", { textContent: cell })))),
    el("tbody", {}, ...body.map((row) => el("tr", {}, ...row.map((cell) => el("td", { textContent: cell })))))));
}

function inline(text) {
  return text.replaceAll("`", "").split(/\*\*(.+?)\*\*/).map((part, i) => (i % 2 ? el("strong", { textContent: part }) : part));
}

// --- Step 4: publish and links --------------------------------------------------------------------

async function publish() {
  if (busy || draftErrors.length) return;
  clearTimeout(checkTimer);
  busy = true;
  $("publish").disabled = true;
  setStatus("draft-status", "");
  showWorking("publishing");
  try {
    showLive(await api(`/${sessionId}/publish`, { kb_markdown: kbText }));
  } catch (error) {
    setStatus("draft-status", error.message, { error: true });
  } finally {
    busy = false;
    hideWorking();
    if (step === "draft") renderDraft();
  }
}

function showLive(links) {
  published = links;
  $("chat-url").textContent = links.chat_url;
  $("owner-url").textContent = links.owner_url;
  $("embed-html").textContent = links.embed_html;
  $("try").href = links.chat_url;
  $("live-intro").textContent = t("liveIntro")(businessName);
  showStep("live");
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

// --- Resuming after a reload ----------------------------------------------------------------------

async function resume() {
  if (!sessionId) return false;
  let data;
  try {
    data = await api(`/${sessionId}`);
  } catch (error) {
    if (error.status === 404) { sessionId = null; save(SESSION_KEY, null); }
    return false;
  }
  mode = data.mode;
  businessName = data.business_name;
  covered = data.covered;
  topics = data.topics;
  done = data.done;
  $("business-name").value = data.business_name;
  $("paste-block").hidden = mode !== "quick";
  renderTranscript(data.transcript);
  applyLabels();
  if (data.published) {
    if (data.draft) useDraft(data.draft);
    showLive(data.published);
  } else if (data.draft) {
    useDraft(data.draft);
    showStep("draft");
  } else {
    showStep("interview");
    if (done) {
      $("messages").append(el("li", { className: "message note status-note", textContent: t("interviewDone") }));
      writeDraft();
    }
  }
  return true;
}

let startOverArmed = null;
function startOver() {
  if (!startOverArmed) {
    $("start-over").textContent = t("startOverSure");
    startOverArmed = setTimeout(() => { startOverArmed = null; $("start-over").textContent = t("startOver"); }, 4000);
    return;
  }
  clearTimeout(startOverArmed);
  startOverArmed = null;
  save(SESSION_KEY, null);
  location.reload();
}

// --- Wiring ---------------------------------------------------------------------------------------

document.querySelectorAll(".lang").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));
$("setup-form").addEventListener("submit", create);
$("switch-mode").addEventListener("click", () => setMode(mode === "quick" ? "full" : "quick"));
$("business-name").addEventListener("input", () => markArabic($("business-name")));
$("paste").addEventListener("input", () => markArabic($("paste")));
$("composer").addEventListener("submit", sendReply);
$("reply").addEventListener("input", autosize);
$("reply").addEventListener("keydown", (event) => {
  // Enter sends; Shift+Enter adds a line. Not while an input method is composing (Arabic, etc.).
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("composer").requestSubmit();
  }
});
$("skip").addEventListener("click", writeDraft);
$("toggle-raw").addEventListener("click", toggleRaw);
$("raw").addEventListener("input", rawChanged);
$("publish").addEventListener("click", publish);
$("start-over").addEventListener("click", startOver);
document.querySelectorAll(".copy").forEach((button) => button.addEventListener("click", async () => {
  const ok = await copyText($(button.dataset.copy).textContent);
  button.textContent = t(ok ? "copied" : "copyFailed");
  setTimeout(() => (button.textContent = t("copy")), 1800);
}));

async function init() {
  applyLabels();
  showStep("setup");
  if (!(await resume())) setMode("quick");
}

init();
