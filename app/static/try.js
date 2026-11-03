// /try: the visitor's own sandbox (a private copy of The Plug), customer and owner side by side.
// The sandbox's slug and owner key stay in this browser, so a refresh keeps the same demo.

const SANDBOX_KEY = "jawab:sandbox";
const LANG_KEY = "jawab:lang"; // shared with the landing and chat pages
const BADGE_POLL_MS = 5000;
const PHONE = window.matchMedia("(max-width: 900px)");

const TEXTS = {
  en: {
    startOver: "Start over",
    title: "You're both sides of the counter: the customer and the shop owner.",
    step1Title: "Ask as the customer.",
    step1Text: "Prices work straight away. Then ask something the shop never told it, like",
    example: "Are you open on Christmas Day?",
    step2Title: "Answer as the owner.",
    step2Text: "The question lands in the owner inbox. Your answer goes to the customer, in their language.",
    step3Title: "Tap Save, then ask again.",
    step3Text: "Start a new chat (in any language) and it answers on its own, citing what you taught it.",
    privateNote: "This demo shop is yours alone: nobody else sees your chats or what you teach it. It resets after a day.",
    customer: "Customer",
    owner: "Owner",
    customerLabel: "Customer · the shop's website chat",
    ownerLabel: "Owner · your inbox",
    loading: "Opening your demo shop…",
    failed: "Your demo couldn't open right now.",
    confirmStartOver: "Start over with a fresh demo shop? Your chats and what you taught it will be gone.",
  },
  el: {
    startOver: "Από την αρχή",
    title: "Είσαι και στις δύο πλευρές του πάγκου: ο πελάτης και ο ιδιοκτήτης.",
    step1Title: "Ρώτα ως πελάτης.",
    step1Text: "Οι τιμές απαντώνται αμέσως. Μετά ρώτα κάτι που το μαγαζί δεν του έχει πει ποτέ, όπως",
    example: "Είστε ανοιχτά ανήμερα των Χριστουγέννων;",
    step2Title: "Απάντησε ως ιδιοκτήτης.",
    step2Text: "Η ερώτηση φτάνει στα εισερχόμενα του ιδιοκτήτη. Η απάντησή σου πάει στον πελάτη, στη γλώσσα του.",
    step3Title: "Πάτα Αποθήκευση και ρώτα ξανά.",
    step3Text: "Ξεκίνα νέα συνομιλία (σε όποια γλώσσα θέλεις) και θα απαντήσει μόνο του, με βάση όσα του έμαθες.",
    privateNote: "Αυτό το δοκιμαστικό μαγαζί είναι μόνο δικό σου: κανείς άλλος δεν βλέπει τις συνομιλίες σου ή όσα του μαθαίνεις. Μηδενίζεται μετά από μία μέρα.",
    customer: "Πελάτης",
    owner: "Ιδιοκτήτης",
    customerLabel: "Πελάτης · η συνομιλία στην ιστοσελίδα του μαγαζιού",
    ownerLabel: "Ιδιοκτήτης · τα εισερχόμενά σου",
    loading: "Ανοίγει το δοκιμαστικό σου μαγαζί…",
    failed: "Δεν ήταν δυνατό να ανοίξει το demo αυτή τη στιγμή.",
    confirmStartOver: "Να ξεκινήσεις από την αρχή με νέο δοκιμαστικό μαγαζί; Οι συνομιλίες σου και όσα του έμαθες θα χαθούν.",
  },
  ar: {
    startOver: "ابدأ من جديد",
    title: "أنت على جانبي الطاولة: الزبون وصاحب المحل.",
    step1Title: "اسأل كزبون.",
    step1Text: "الأسعار تعمل فوراً. ثم اسأل عن شيء لم يخبره به المحل، مثل",
    example: "هل أنتم مفتوحون يوم عيد الميلاد؟",
    step2Title: "أجب كصاحب المحل.",
    step2Text: "يصل السؤال إلى صندوق صاحب المحل. وجوابك يصل إلى الزبون بلغته.",
    step3Title: "اضغط حفظ، ثم اسأل مجدداً.",
    step3Text: "ابدأ محادثة جديدة (بأي لغة) وسيجيب وحده، مستشهداً بما علّمته.",
    privateNote: "هذا المحل التجريبي لك وحدك: لا أحد غيرك يرى محادثاتك أو ما علّمته. يُعاد ضبطه بعد يوم.",
    customer: "الزبون",
    owner: "صاحب المحل",
    customerLabel: "الزبون · دردشة موقع المحل",
    ownerLabel: "صاحب المحل · صندوقك",
    loading: "جارٍ فتح محلك التجريبي…",
    failed: "تعذّر فتح العرض التجريبي الآن.",
    confirmStartOver: "هل تريد البدء من جديد بمحل تجريبي جديد؟ ستُحذف محادثاتك وما علّمته.",
  },
};

const $ = (id) => document.getElementById(id);
const memory = {};
function load(key) { try { return localStorage.getItem(key); } catch { return memory[key] ?? null; } }
function save(key, value) {
  try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); }
  catch { memory[key] = value; }
}

const UI_LANGS = ["en", "el", "ar"]; // the page labels exist in these
let lang = UI_LANGS.includes(load(LANG_KEY)) ? load(LANG_KEY) : "en";
let box = null; // {slug, owner_key, chat_url, owner_url}
let badgeTimer = null;
const t = (key) => TEXTS[lang][key] ?? TEXTS.en[key];

function applyLabels() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
  $("example").textContent = `“${t("example")}”`;
  document.querySelectorAll(".lang").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
}

function showStatus(key, error = false) {
  const status = $("status");
  status.hidden = !key;
  status.textContent = key ? t(key) : "";
  status.classList.toggle("error", error);
}

async function exists(slug) {
  try {
    const response = await fetch(`/api/b/${encodeURIComponent(slug)}/public`);
    return response.ok;
  } catch {
    return true; // offline for a moment: keep the sandbox rather than make a new one
  }
}

async function createSandbox() {
  const response = await fetch("/api/sandbox", { method: "POST" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "failed");
  save(SANDBOX_KEY, JSON.stringify(data));
  return data;
}

async function openSandbox(fresh = false) {
  showStatus("loading");
  try {
    const stored = fresh ? null : JSON.parse(load(SANDBOX_KEY) || "null");
    box = stored && stored.slug && (await exists(stored.slug)) ? stored : await createSandbox();
  } catch (error) {
    showStatus("failed", true);
    if (error.message && error.message !== "failed") $("status").textContent += ` ${error.message}`;
    return;
  }
  showStatus(null);
  // ?frame=1: inside this page, so the pages drop their own Jawab bar.
  $("frame-customer").src = `${box.chat_url}?panel=1&frame=1`;
  $("frame-owner").src = `${box.owner_url}&frame=1`;
  pollBadge();
}

// Phones show one side at a time; a badge on the Owner tab says when a question is waiting.
function selectSide(side) {
  const owner = side === "owner";
  $("tab-customer").setAttribute("aria-selected", String(!owner));
  $("tab-owner").setAttribute("aria-selected", String(owner));
  $("pane-customer").hidden = PHONE.matches && owner;
  $("pane-owner").hidden = PHONE.matches && !owner;
}

async function pollBadge() {
  clearTimeout(badgeTimer);
  if (box && PHONE.matches && !document.hidden) {
    try {
      const response = await fetch(`/api/owner/${encodeURIComponent(box.slug)}/escalations`,
        { headers: { "X-Owner-Key": box.owner_key } });
      if (response.ok) {
        const pending = (await response.json()).escalations.filter((e) => e.status === "pending").length;
        $("owner-badge").hidden = pending === 0;
        $("owner-badge").textContent = String(pending);
      }
    } catch { /* try again next time */ }
  }
  badgeTimer = setTimeout(pollBadge, BADGE_POLL_MS);
}

// The example question goes into the customer's message box (both pages are on this site).
$("example").addEventListener("click", () => {
  selectSide("customer");
  const input = $("frame-customer").contentDocument?.getElementById("input");
  if (!input) return;
  input.value = t("example");
  input.focus();
});

$("start-over").addEventListener("click", () => {
  if (window.confirm(t("confirmStartOver"))) openSandbox(true);
});
$("tab-customer").addEventListener("click", () => selectSide("customer"));
$("tab-owner").addEventListener("click", () => selectSide("owner"));
PHONE.addEventListener("change", () => selectSide($("tab-owner").getAttribute("aria-selected") === "true" ? "owner" : "customer"));
document.addEventListener("visibilitychange", () => { if (!document.hidden) pollBadge(); });
document.querySelectorAll(".lang").forEach((button) => button.addEventListener("click", () => {
  lang = button.dataset.lang;
  save(LANG_KEY, lang);
  applyLabels();
  $("frame-customer").contentWindow?.location.reload(); // the chat reads the language when it loads
}));

applyLabels();
selectSide("customer");
openSandbox();
