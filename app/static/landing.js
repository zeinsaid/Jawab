// The landing page (spec section 9): EN/AR texts, the embed snippet and the hero animation.

const LANG_KEY = "jawab:lang"; // shared with the chat and /start pages

// Every text on the page, in both languages. Keys match the data-i18n attributes.
const TEXTS = {
  en: {
    pageTitle: "Jawab · The AI receptionist that never guesses",
    eyebrow: "AI receptionist for small businesses",
    heroTitle: "Your shop's receptionist that never guesses.",
    heroSub: "Answers your customers in Arabic and English from your own price list. When it doesn't know, it asks you, and learns your answer.",
    tryDemo: "Try it: be the customer and the owner",
    setUp: "Set up your business, free",
    madeFor: "Made for shops like",
    shopPrint: "Print shops",
    shopTailors: "Tailors",
    shopSalons: "Salons",
    shopGarages: "Garages",
    shopCafes: "Cafés",
    mockAria: "Example: a customer asks in Arabic whether the shop is open on Christmas Day. The assistant asks the owner, the owner answers and saves it, and the next customer gets the answer straight away.",
    mockStatus: "AI receptionist",
    mockAsking: "Asking the owner",
    mockOwner: "Owner:",
    mockSave: "Save ✦",
    mockNewChat: "New chat",
    howTitle: "How it works",
    step1Title: "Paste your info",
    step1Text: "Your price list, menu or website text. A few short questions fill the gaps.",
    step2Title: "It answers, citing your info",
    step2Text: "Every reply comes from what you wrote, and shows which part it used.",
    step3Title: "It asks you when unsure, and learns",
    step3Text: "Your answer goes to the customer, and one tap saves it for next time.",
    whyTitle: "Why it's different",
    tagAnswer: "Answer",
    tagLearned: "✦ Learned",
    card1Title: "Never guesses",
    card1Text: "Every answer cites your info, or it asks you.",
    card2Title: "Learns from you",
    card2Text: "One tap turns your answer into knowledge.",
    card3Title: "Arabic and English",
    card3Text: "And Arabizi, from one knowledge base.",
    embedTitle: "On your website in one line",
    embedText: "Paste this into your website and a chat button appears in the corner, answering from your info.",
    copy: "Copy",
    copied: "Copied ✓",
    copyFailed: "Select and copy",
    embedDemo: "See it on a demo shop site",
    footer: "Built by Zein Said at the Founding MENA x Replit Hackathon, Dubai, 31 Oct 2026.",
    portfolio: "Portfolio",
    code: "Code",
    engine: "The engine (Shop-Assistant)",
  },
  ar: {
    pageTitle: "جواب · موظف استقبال ذكي لا يخمّن أبداً",
    eyebrow: "موظف استقبال ذكي للأعمال الصغيرة",
    heroTitle: "موظف استقبال لمتجرك لا يخمّن أبداً.",
    heroSub: "يجيب عملاءك بالعربية والإنجليزية من قائمة أسعارك أنت. وعندما لا يعرف الجواب، يسألك ويتعلّم من إجابتك.",
    tryDemo: "جرّبه: كن الزبون وصاحب المحل",
    setUp: "جهّز نشاطك التجاري مجاناً",
    madeFor: "مصمَّم لمحلات مثل",
    shopPrint: "المطابع",
    shopTailors: "الخياطون",
    shopSalons: "صالونات التجميل",
    shopGarages: "ورش السيارات",
    shopCafes: "المقاهي",
    mockAria: "مثال: عميل يسأل بالعربية إن كان المتجر مفتوحاً يوم عيد الميلاد. يسأل المساعد صاحب المتجر، فيجيب ويحفظ الإجابة، ويحصل العميل التالي على الجواب فوراً.",
    mockStatus: "موظف استقبال ذكي",
    mockAsking: "يسأل صاحب المتجر",
    mockOwner: "صاحب المتجر:",
    mockSave: "حفظ ✦",
    mockNewChat: "محادثة جديدة",
    howTitle: "كيف يعمل",
    step1Title: "الصق معلوماتك",
    step1Text: "قائمة أسعارك أو قائمة الطعام أو نص موقعك. وبضعة أسئلة قصيرة تكمل ما ينقص.",
    step2Title: "يجيب مستشهداً بمعلوماتك",
    step2Text: "كل رد يأتي مما كتبته أنت، ويُظهر الجزء الذي اعتمد عليه.",
    step3Title: "يسألك عندما لا يكون متأكداً، ويتعلّم",
    step3Text: "تصل إجابتك إلى العميل، وبلمسة واحدة تُحفظ للمرة القادمة.",
    whyTitle: "ما الذي يميّزه",
    tagAnswer: "إجابة",
    tagLearned: "✦ تعلّمه",
    card1Title: "لا يخمّن أبداً",
    card1Text: "كل إجابة تستند إلى معلوماتك، وإلا فإنه يسألك.",
    card2Title: "يتعلّم منك",
    card2Text: "لمسة واحدة تحوّل إجابتك إلى معرفة.",
    card3Title: "العربية والإنجليزية",
    card3Text: "والعربيزي أيضاً، من قاعدة معرفة واحدة.",
    embedTitle: "على موقعك بسطر واحد",
    embedText: "الصق هذا السطر في موقعك، فيظهر زر محادثة في الزاوية يجيب عملاءك من معلوماتك.",
    copy: "نسخ",
    copied: "تم النسخ ✓",
    copyFailed: "حدّده وانسخه",
    embedDemo: "شاهده على موقع متجر تجريبي",
    footer: "صنعه زين سعيد في هاكاثون Founding MENA x Replit، دبي، 31 أكتوبر 2026.",
    portfolio: "أعمالي",
    code: "الكود",
    engine: "المحرّك (Shop-Assistant)",
  },
};

function load(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function save(key, value) {
  try { localStorage.setItem(key, value); } catch { /* private mode: the choice just isn't remembered */ }
}

let lang = load(LANG_KEY) === "ar" ? "ar" : "en";

function applyLanguage() {
  const texts = TEXTS[lang];
  const root = document.documentElement;
  root.lang = lang;
  root.dir = lang === "ar" ? "rtl" : "ltr";
  document.title = texts.pageTitle;
  document.querySelectorAll("[data-i18n]").forEach((node) => (node.textContent = texts[node.dataset.i18n]));
  document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => node.setAttribute("aria-label", texts[node.dataset.i18nAriaLabel]));
  document.querySelectorAll(".lang").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
}

document.querySelectorAll(".lang").forEach((button) => button.addEventListener("click", () => {
  lang = button.dataset.lang;
  save(LANG_KEY, lang);
  applyLanguage();
}));

// "On your website in one line": the snippet for this site's own address.
const snippet = document.getElementById("embed-snippet");
snippet.textContent = `<script src="${location.origin}/embed.js?b=the-plug" async></script>`;

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Older browsers, or no clipboard permission: copy from a hidden text box instead.
    const area = Object.assign(document.createElement("textarea"), { value: text });
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

let copyTimer = null;
document.getElementById("copy-snippet").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const ok = await copyText(snippet.textContent);
  button.textContent = TEXTS[lang][ok ? "copied" : "copyFailed"];
  clearTimeout(copyTimer);
  copyTimer = setTimeout(() => (button.textContent = TEXTS[lang].copy), 1800);
});

// The hero preview plays its bubbles once, one by one, when it comes into view.
function playHeroDemo() {
  const demo = document.getElementById("hero-demo");
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return; // everything shows at once
  demo.classList.add("armed");
  if (!("IntersectionObserver" in window)) {
    demo.classList.add("play");
    return;
  }
  const observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) {
      demo.classList.add("play");
      observer.disconnect();
    }
  }, { threshold: 0.3 });
  observer.observe(demo);
}

applyLanguage();
playHeroDemo();
