/* Jawab chat bubble loader. A website hosts this file itself, so the bubble appears at once even while
 * the Jawab server is asleep (a free host takes about a minute to wake):
 *
 *   <script src="/jawab.js" defer
 *           data-base="https://<your-jawab-server>" data-business="<slug>"
 *           data-accent="#F920EB" data-name="The Plug"></script>
 *
 * Optional: data-languages="en,el" (the chat's page languages), data-offline-en / data-offline-el /
 * data-offline-ar (what to show if the chat can't be reached), data-theme="light" (no dark mode, for a
 * website that is light-only). The page's <html lang> picks the language.
 * The Jawab server also serves this file as /embed.js?b=<slug>, with that business's values filled in.
 *
 * How it works: the bubble and a local greeting render straight away, and the page pings /health to
 * wake the server. The real chat (an iframe) loads hidden on first open and takes over once it says
 * it's ready; a message typed before that is handed to it. If the server is still asleep after
 * about a minute, the offline message shows instead. Everything lives in one function and a shadow
 * root: no globals, the page's CSS can't reach in, and no dependencies.
 */
(function () {
  "use strict";

  var DEFAULTS = /*__JAWAB_DEFAULTS__*/{};
  var script = document.currentScript;
  function attr(name) { return (script && script.getAttribute("data-" + name)) || ""; }

  // Where the Jawab server is: data-base, else (for /embed.js) the address the script came from.
  var BASE = attr("base");
  if (!BASE && DEFAULTS.base) {
    try { BASE = script && script.src ? new URL(script.src).origin : DEFAULTS.base; } catch (e) { BASE = DEFAULTS.base; }
  }
  BASE = String(BASE || "").replace(/\/+$/, "");
  var SLUG = attr("business") || DEFAULTS.business || "";
  if (!BASE || !SLUG) {
    if (window.console) console.warn("Jawab: set data-base and data-business on the script tag.");
    return;
  }

  var HEX = /^#[0-9a-fA-F]{6}$/;
  var ACCENT = HEX.test(attr("accent")) ? attr("accent") : (HEX.test(DEFAULTS.accent || "") ? DEFAULTS.accent : "#0F766E");
  var NAME = attr("name") || DEFAULTS.name || "";
  // "light": the bubble and the chat stay light even when the visitor's device is in dark mode.
  var THEME = attr("theme") === "light" ? "light" : "auto";
  var WAKE_MS = 60000; // how long a first message waits for a sleeping server
  var STORE_KEY = "jawab:" + SLUG + ":conversation";
  var HOST_ID = "jawab-chat-" + SLUG;
  // Phones: narrow, or short (a phone held sideways is wide but only ~390 px tall, where the
  // side panel was squashed to ~280 px). Both get the full-screen chat.
  var PHONE = "(max-width: 479.98px), (max-height: 499.98px)";

  // The chat page's own wording, so the hand-over to the real chat is seamless.
  var TEXT = {
    en: {
      welcome: "Hi! I'm the assistant for {name}. Ask me about prices, opening hours or services, in your own language.",
      welcomeNoName: "Hi! Ask me about prices, opening hours or services, in your own language.",
      subtitle: "AI receptionist", placeholder: "Type a message…", send: "Send", input: "Your message",
      open: "Open chat", close: "Close chat", title: "Chat with us", typing: "The assistant is typing",
      offline: "Chat is offline right now. Please try again later.",
    },
    el: {
      welcome: "Γεια σου! Είμαι ο βοηθός του {name}. Ρώτα με για τιμές, ωράριο ή υπηρεσίες, σε όποια γλώσσα θέλεις.",
      welcomeNoName: "Γεια σου! Ρώτα με για τιμές, ωράριο ή υπηρεσίες, σε όποια γλώσσα θέλεις.",
      subtitle: "AI ρεσεψιονίστ", placeholder: "Γράψε ένα μήνυμα…", send: "Αποστολή", input: "Το μήνυμά σου",
      open: "Άνοιγμα συνομιλίας", close: "Κλείσιμο συνομιλίας", title: "Μίλησε μαζί μας", typing: "Ο βοηθός γράφει",
      offline: "Η συνομιλία δεν είναι διαθέσιμη αυτή τη στιγμή. Δοκίμασε ξανά αργότερα.",
    },
    ar: {
      welcome: "مرحباً! أنا مساعد {name}. اسألني عن الأسعار أو مواعيد العمل أو الخدمات، بأي لغة تريدها.",
      welcomeNoName: "مرحباً! اسألني عن الأسعار أو مواعيد العمل أو الخدمات، بأي لغة تريدها.",
      subtitle: "موظف استقبال ذكي", placeholder: "اكتب رسالتك…", send: "إرسال", input: "رسالتك",
      open: "فتح المحادثة", close: "إغلاق", title: "تحدث معنا", typing: "المساعد يكتب",
      offline: "الدردشة غير متاحة الآن. يرجى المحاولة لاحقاً.",
    },
  };

  var LANGS = (attr("languages") || (DEFAULTS.languages || []).join(",") || "en,el,ar")
    .split(",").map(function (s) { return s.trim(); }).filter(function (s) { return TEXT[s]; });
  if (!LANGS.length) LANGS = ["en"];

  // The host page's language (<html lang="el-CY"> -> el), if the chat offers it.
  var pageLang = String(document.documentElement.getAttribute("lang") || "").toLowerCase().split("-")[0];
  var LANG = LANGS.indexOf(pageLang) >= 0 ? pageLang : (LANGS.indexOf("en") >= 0 ? "en" : LANGS[0]);
  var T = TEXT[LANG];
  var OFFLINE = attr("offline-" + LANG) || (DEFAULTS.offline && (DEFAULTS.offline[LANG] || DEFAULTS.offline.en)) || T.offline;
  var WELCOME = NAME ? T.welcome.replace("{name}", NAME) : T.welcomeNoName;

  // --- Colours: the accent as given for the button, darkened or lightened where text sits on it --

  function rgb(hex) { return [1, 3, 5].map(function (i) { return parseInt(hex.substr(i, 2), 16); }); }
  function lum(c) {
    var v = c.map(function (x) { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  }
  function contrast(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function mix(c, to, t) { return c.map(function (x, i) { return Math.round(x + (to[i] - x) * t); }); }
  function until(c, to, text) {
    for (var s = 0; s <= 20; s++) { var m = mix(c, to, s * 0.05); if (contrast(m, text) >= 4.5) return m; }
    return to;
  }
  function css(c) { return "rgb(" + c.join(",") + ")"; }
  var base = rgb(ACCENT);
  var TEXT_LIGHT = css(until(base, [0, 0, 0], [255, 255, 255])); // fills with white text, light mode
  var TEXT_DARK = css(until(base, [255, 255, 255], [13, 13, 13])); // fills with dark text, dark mode

  var STYLE = [
    ":host{all:initial}",
    ".jw{--ac:" + ACCENT + ";--fill:" + TEXT_LIGHT + ";--on-fill:#fff;--bg:#fffdf9;--bubble:#f0ece3;--fg:#1c1b18;",
    "--muted:#6d6a62;--line:#e6e1d6;font-family:\"IBM Plex Sans\",system-ui,-apple-system,\"Segoe UI\",Roboto,sans-serif}",
    THEME === "light" ? "" : "@media (prefers-color-scheme:dark){.jw{--fill:" + TEXT_DARK +
      ";--on-fill:#0d0d0d;--bg:#1c1c19;--bubble:#27261f;--fg:#edebe4;--muted:#a19d92;--line:#302e29}}",
    ".jw-btn{position:fixed;right:20px;bottom:calc(20px + env(safe-area-inset-bottom,0px));z-index:2147483001;",
    "width:60px;height:60px;margin:0;padding:0;border:0;border-radius:50%;background:var(--ac);color:#fff;",
    "display:flex;align-items:center;justify-content:center;cursor:pointer;",
    "box-shadow:0 6px 20px rgba(0,0,0,.22),0 2px 6px rgba(0,0,0,.12);",
    "transition:transform .15s ease;-webkit-tap-highlight-color:transparent}",
    ".jw-btn:hover{transform:scale(1.05)}",
    ".jw-btn:focus-visible{outline:3px solid var(--ac);outline-offset:3px}",
    ".jw-btn svg{display:block;width:28px;height:28px;pointer-events:none}",
    ".jw-btn .jw-i-close{display:none}.jw-open .jw-btn .jw-i-chat{display:none}.jw-open .jw-btn .jw-i-close{display:block}",
    ".jw-panel{position:fixed;right:20px;bottom:calc(92px + env(safe-area-inset-bottom,0px));z-index:2147483000;",
    "width:380px;height:600px;max-width:calc(100vw - 40px);max-height:calc(100vh - 112px);max-height:calc(100dvh - 112px);",
    "border-radius:16px;overflow:hidden;background:var(--bg);color:var(--fg);",
    "box-shadow:0 16px 48px rgba(0,0,0,.25),0 2px 8px rgba(0,0,0,.08);",
    "opacity:0;visibility:hidden;pointer-events:none;transform:translateY(12px) scale(.98);transform-origin:bottom right;",
    "transition:opacity .18s ease,transform .18s ease,visibility 0s linear .18s}",
    ".jw-open .jw-panel{opacity:1;visibility:visible;pointer-events:auto;transform:none;transition:opacity .18s ease,transform .18s ease}",
    ".jw-panel iframe{position:absolute;inset:0;display:block;width:100%;height:100%;border:0;background:var(--bg);visibility:hidden}",
    ".jw-live iframe{visibility:visible}.jw-live .jw-shell{visibility:hidden}",
    // The local stand-in for the chat, shown until the real one is ready.
    ".jw-shell{position:absolute;inset:0;display:flex;flex-direction:column}",
    ".jw-head{display:flex;align-items:center;gap:10px;padding:12px 12px 12px 16px;border-bottom:1px solid var(--line)}",
    ".jw-avatar{flex:none;width:36px;height:36px;border-radius:50%;background:var(--fill);color:var(--on-fill);",
    "display:flex;align-items:center;justify-content:center;font-weight:700;font-size:16px}",
    ".jw-who{flex:1;min-width:0}.jw-name{font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    ".jw-sub{font-size:12.5px;color:var(--muted)}",
    ".jw-x{flex:none;width:36px;height:36px;border:1px solid var(--line);border-radius:10px;background:transparent;color:var(--fg);cursor:pointer;font-size:20px;line-height:1}",
    ".jw-x:focus-visible,.jw-form button:focus-visible{outline:2px solid var(--fill);outline-offset:2px}",
    ".jw-msgs{flex:1;overflow-y:auto;margin:0;padding:16px;list-style:none;display:flex;flex-direction:column;gap:10px}",
    ".jw-m{max-width:85%;padding:10px 14px;border-radius:16px;font-size:15px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere}",
    ".jw-bot{align-self:flex-start;background:var(--bubble);border-bottom-left-radius:4px}",
    ".jw-me{align-self:flex-end;background:var(--fill);color:var(--on-fill);border-bottom-right-radius:4px}",
    ".jw-typing{display:flex;gap:4px;align-items:center;padding:14px 16px}",
    ".jw-typing span{width:7px;height:7px;border-radius:50%;background:var(--muted);animation:jw-blink 1.2s infinite ease-in-out}",
    ".jw-typing span:nth-child(2){animation-delay:.15s}.jw-typing span:nth-child(3){animation-delay:.3s}",
    "@keyframes jw-blink{0%,80%,100%{opacity:.25}40%{opacity:1}}",
    ".jw-form{display:flex;gap:8px;padding:12px;border-top:1px solid var(--line)}",
    ".jw-form input{flex:1;min-width:0;font:inherit;font-size:16px;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--bg);color:var(--fg)}",
    ".jw-form input:focus{outline:2px solid var(--fill);outline-offset:-1px}",
    ".jw-form button{font:inherit;font-weight:600;padding:0 16px;border:0;border-radius:12px;background:var(--fill);color:var(--on-fill);cursor:pointer}",
    ".jw-form button:disabled{opacity:.6;cursor:default}",
    "[dir=rtl] .jw-bot{border-bottom-left-radius:16px;border-bottom-right-radius:4px}",
    "[dir=rtl] .jw-me{border-bottom-right-radius:16px;border-bottom-left-radius:4px}",
    // Phones: the chat takes the whole screen and the floating button steps aside.
    "@media " + PHONE + "{",
    ".jw-panel{top:0;right:0;bottom:0;left:0;width:100%;height:100%;max-width:none;max-height:none;border-radius:0;transform:translateY(16px)}",
    ".jw-open .jw-btn{display:none}",
    "}",
    "@media (prefers-reduced-motion:reduce){.jw-btn,.jw-panel,.jw-open .jw-panel{transition:none}.jw-typing span{animation:none;opacity:.6}}",
  ].join("");

  var CHAT_ICON =
    '<svg class="jw-i-chat" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
    '<path fill="currentColor" d="M12 3C6.98 3 3 6.58 3 11c0 2.2 1 4.2 2.62 5.64-.13 1.3-.6 2.6-1.5 3.66a.5.5 0 0 0 ' +
    '.46.82c2.03-.25 3.66-1 4.86-1.86.83.2 1.69.3 2.56.3 5.02 0 9-3.58 9-8s-3.98-8.56-9-8.56z"/></svg>';
  var CLOSE_ICON =
    '<svg class="jw-i-close" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
    '<path fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" d="M6 6l12 12M18 6L6 18"/></svg>';

  function load(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } }
  function save(key, value) {
    try { if (value) window.localStorage.setItem(key, value); else window.localStorage.removeItem(key); } catch (e) { /* private mode */ }
  }

  function health(timeoutMs) {
    return new Promise(function (resolve) {
      var ctrl = window.AbortController ? new AbortController() : null;
      var timer = setTimeout(function () { if (ctrl) ctrl.abort(); resolve(false); }, timeoutMs);
      try {
        fetch(BASE + "/health", { cache: "no-store", credentials: "omit", signal: ctrl ? ctrl.signal : undefined })
          .then(function (r) { clearTimeout(timer); resolve(r.ok); }, function () { clearTimeout(timer); resolve(false); });
      } catch (e) { clearTimeout(timer); resolve(false); }
    });
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function mount() {
    if (document.getElementById(HOST_ID)) return; // the snippet was pasted twice

    var host = document.createElement("div");
    host.id = HOST_ID;
    host.style.cssText = "all:initial;position:static";
    var root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;
    var style = el("style");
    style.textContent = STYLE;

    var wrap = el("div", "jw");
    wrap.setAttribute("lang", LANG);
    var panel = el("div", "jw-panel");
    panel.id = "jw-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", NAME || T.title);

    // The local shell: header, greeting, input. Ready before the server answers anything.
    var shell = el("div", "jw-shell");
    shell.setAttribute("dir", LANG === "ar" ? "rtl" : "ltr");
    var head = el("div", "jw-head");
    var avatar = el("span", "jw-avatar", (NAME.trim()[0] || "•").toUpperCase());
    avatar.setAttribute("aria-hidden", "true");
    var who = el("div", "jw-who");
    who.appendChild(el("div", "jw-name", NAME || T.title));
    who.appendChild(el("div", "jw-sub", T.subtitle));
    var x = el("button", "jw-x", "×");
    x.type = "button";
    x.setAttribute("aria-label", T.close);
    head.appendChild(avatar); head.appendChild(who); head.appendChild(x);
    var list = el("ol", "jw-msgs");
    list.setAttribute("aria-live", "polite");
    list.appendChild(el("li", "jw-m jw-bot", WELCOME));
    var form = el("form", "jw-form");
    var input = el("input");
    input.type = "text"; input.maxLength = 500; input.autocomplete = "off"; input.dir = "auto";
    input.placeholder = T.placeholder;
    input.setAttribute("aria-label", T.input);
    var sendButton = el("button", "", T.send);
    sendButton.type = "submit";
    form.appendChild(input); form.appendChild(sendButton);
    shell.appendChild(head); shell.appendChild(list); shell.appendChild(form);
    panel.appendChild(shell);

    var button = el("button", "jw-btn");
    button.type = "button";
    button.setAttribute("aria-controls", "jw-panel");
    button.innerHTML = CHAT_ICON + CLOSE_ICON;
    wrap.appendChild(panel);
    wrap.appendChild(button);
    root.appendChild(style);
    root.appendChild(wrap);
    document.body.appendChild(host);

    var open = false;
    var awake = false;
    var frame = null;
    var frameReady = false;
    var frameLoadedAsleep = false; // the frame finished loading before the server said it was awake
    var pending = null; // a message waiting for the real chat
    var typing = null;
    var savedOverflow = null;
    var phone = window.matchMedia ? window.matchMedia(PHONE) : { matches: false };

    function lockPage(lock) {
      // Full-screen on phones: stop the page behind from scrolling while the chat is open.
      var page = document.documentElement;
      if (lock && savedOverflow === null) { savedOverflow = page.style.overflow; page.style.overflow = "hidden"; }
      else if (!lock && savedOverflow !== null) { page.style.overflow = savedOverflow; savedOverflow = null; }
    }

    function render() {
      wrap.className = "jw" + (open ? " jw-open" : "") + (frameReady ? " jw-live" : "");
      button.setAttribute("aria-expanded", open ? "true" : "false");
      button.setAttribute("aria-label", open ? T.close : T.open);
      button.title = open ? T.close : T.title;
      panel.setAttribute("aria-hidden", open ? "false" : "true");
      lockPage(open && phone.matches);
    }

    function frameUrl() {
      var url = BASE + "/b/" + encodeURIComponent(SLUG) + "?embed=1&lang=" + encodeURIComponent(LANG);
      var conversation = load(STORE_KEY);
      if (conversation) url += "&c=" + encodeURIComponent(conversation);
      if (THEME === "light") url += "&theme=light";
      return url;
    }

    function loadFrame() {
      if (frame) return;
      frame = el("iframe");
      frame.title = NAME || T.title;
      frame.setAttribute("allow", "clipboard-write");
      frame.addEventListener("load", function () { if (!frameReady && !awake) frameLoadedAsleep = true; });
      frame.src = frameUrl();
      panel.appendChild(frame);
    }

    function dropFrame() {
      if (frame) frame.remove();
      frame = null;
      frameReady = false;
      frameLoadedAsleep = false;
    }

    function showTyping(on) {
      if (on && !typing) {
        typing = el("li", "jw-m jw-bot jw-typing");
        typing.setAttribute("aria-label", T.typing);
        typing.appendChild(el("span")); typing.appendChild(el("span")); typing.appendChild(el("span"));
        list.appendChild(typing);
        list.scrollTop = list.scrollHeight;
      } else if (!on && typing) {
        typing.remove();
        typing = null;
      }
    }

    function setBusy(busy) {
      input.disabled = busy;
      sendButton.disabled = busy;
    }

    function handOver() {
      // The real chat said it's ready: show it, and give it the message typed meanwhile.
      frameReady = true;
      awake = true;
      showTyping(false);
      if (pending !== null) {
        frame.contentWindow.postMessage({ type: "jawab:send", text: pending }, BASE);
        pending = null;
      }
      setBusy(false);
      render();
      if (open) frame.focus();
    }

    function goOffline() {
      showTyping(false);
      pending = null;
      dropFrame(); // the next message starts again from scratch
      list.appendChild(el("li", "jw-m jw-bot", OFFLINE));
      list.scrollTop = list.scrollHeight;
      setBusy(false);
      input.focus({ preventScroll: true });
    }

    // A message before the real chat is ready: wait up to WAKE_MS for the server, watching two
    // signals, so a missing CORS setting can't make a healthy server look dead: the frame saying
    // it's ready, and /health answering (then the frame reloads, in case it caught the host's
    // "waking up" page instead of the chat).
    function connect() {
      var deadline = Date.now() + WAKE_MS;
      loadFrame();
      (function tick() {
        if (frameReady || pending === null) return;
        if (Date.now() >= deadline) { goOffline(); return; }
        health(Math.min(10000, Math.max(1000, deadline - Date.now()))).then(function (ok) {
          if (frameReady || pending === null) return;
          if (ok) {
            awake = true;
            if (frameLoadedAsleep && frame) { frameLoadedAsleep = false; frame.src = frameUrl(); }
          }
          setTimeout(tick, 2500);
        });
      })();
    }

    function setOpen(next) {
      open = next;
      // Load the real chat on open even if /health hasn't answered: some ad and privacy blockers
      // block any address containing "health". The chat's own "ready" message is the signal
      // that counts; until then the local greeting shows.
      if (open && !frame) loadFrame();
      render();
      if (open) {
        if (frameReady) frame.focus();
        else input.focus({ preventScroll: true });
      }
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var text = input.value.trim();
      if (!text || pending !== null) return;
      input.value = "";
      list.appendChild(el("li", "jw-m jw-me", text));
      pending = text;
      setBusy(true);
      showTyping(true);
      if (frameReady) handOver(); else connect();
    });

    button.addEventListener("click", function () { setOpen(!open); });
    x.addEventListener("click", function () { setOpen(false); button.focus(); });
    document.addEventListener("keydown", function (event) {
      if (open && event.key === "Escape") { setOpen(false); button.focus(); }
    });
    // Messages from the real chat; only our own iframe counts.
    window.addEventListener("message", function (event) {
      if (!frame || event.source !== frame.contentWindow || !event.data) return;
      var data = event.data;
      if (data.type === "jawab:ready") handOver();
      else if (data.type === "jawab:failed") { if (pending !== null) goOffline(); else dropFrame(); }
      else if (data.type === "jawab:conversation") save(STORE_KEY, typeof data.id === "string" ? data.id : null);
      else if (data.type === "jawab:close" && open) { setOpen(false); button.focus(); }
    });
    var onResize = function () { render(); };
    if (phone.addEventListener) phone.addEventListener("change", onResize);
    else if (phone.addListener) phone.addListener(onResize);
    render();

    // Wake the server now, so it's usually up by the time someone opens the chat. A sleeping free
    // server holds this request while it starts, so allow it a good minute.
    health(70000).then(function (ok) {
      if (!ok) return;
      awake = true;
      if (!open) return;
      if (!frame) loadFrame();
      // Opened while asleep: the frame may hold the host's "waking up" page; reload it once.
      else if (frameLoadedAsleep && !frameReady) { frameLoadedAsleep = false; frame.src = frameUrl(); }
    });
  }

  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
