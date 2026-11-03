/* Jawab chat bubble for any website. Served by GET /embed.js?b=<slug>, which fills in the two values below.
 *
 *   <script src="https://<host>/embed.js?b=<slug>" async></script>
 *
 * Everything lives inside one function and a shadow root: no globals, and the host page's CSS can't
 * reach the button or the panel (nor theirs the page). No dependencies.
 */
(function () {
  "use strict";

  var SLUG = "__JAWAB_SLUG__";
  var BASE = "__JAWAB_BASE__";
  // Prefer the address the script was actually loaded from (survives proxies and custom domains).
  try {
    var me = document.currentScript;
    if (me && me.src) BASE = new URL(me.src).origin;
  } catch (e) { /* keep the server's value */ }

  var HOST_ID = "jawab-chat-" + SLUG;
  var ACCENT = "#0F766E";
  var PHONE = "(max-width: 479.98px)";

  var CSS = [
    ":host{all:initial}",
    ".jw-btn{position:fixed;right:20px;bottom:calc(20px + env(safe-area-inset-bottom,0px));z-index:2;",
    "width:60px;height:60px;margin:0;padding:0;border:0;border-radius:50%;background:" + ACCENT + ";color:#fff;",
    "display:flex;align-items:center;justify-content:center;cursor:pointer;",
    "box-shadow:0 6px 20px rgba(0,0,0,.22),0 2px 6px rgba(0,0,0,.12);",
    "transition:transform .15s ease,background-color .15s ease;-webkit-tap-highlight-color:transparent}",
    ".jw-btn:hover{background:#0B5C56;transform:scale(1.05)}",
    ".jw-btn:focus-visible{outline:3px solid #5EEAD4;outline-offset:3px}",
    ".jw-btn svg{display:block;width:28px;height:28px;pointer-events:none}",
    ".jw-btn .jw-close{display:none}",
    ".jw-open .jw-btn .jw-bubble{display:none}",
    ".jw-open .jw-btn .jw-close{display:block}",
    ".jw-panel{position:fixed;right:20px;bottom:calc(92px + env(safe-area-inset-bottom,0px));z-index:1;",
    "width:380px;height:600px;max-width:calc(100vw - 40px);max-height:calc(100vh - 112px);",
    "border-radius:16px;overflow:hidden;background:#fff;box-shadow:0 16px 48px rgba(0,0,0,.25),0 2px 8px rgba(0,0,0,.08);",
    "opacity:0;visibility:hidden;pointer-events:none;transform:translateY(12px) scale(.98);transform-origin:bottom right;",
    "transition:opacity .18s ease,transform .18s ease,visibility 0s linear .18s}",
    ".jw-open .jw-panel{opacity:1;visibility:visible;pointer-events:auto;transform:none;",
    "transition:opacity .18s ease,transform .18s ease}",
    ".jw-panel iframe{display:block;width:100%;height:100%;border:0}",
    // Phones: the chat takes the whole screen and the floating button steps aside; the chat's own
    // header has a close button (it posts "jawab:close" to this page).
    "@media " + PHONE + "{",
    ".jw-panel{top:0;right:0;bottom:0;left:0;width:100%;height:100%;max-width:none;max-height:none;border-radius:0;transform:translateY(16px)}",
    ".jw-open .jw-btn{display:none}",
    "}",
    "@media (prefers-reduced-motion:reduce){.jw-btn,.jw-panel,.jw-open .jw-panel{transition:none}}",
  ].join("");

  var BUBBLE_ICON =
    '<svg class="jw-bubble" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
    '<path fill="currentColor" d="M12 3C6.98 3 3 6.58 3 11c0 2.2 1 4.2 2.62 5.64-.13 1.3-.6 2.6-1.5 3.66a.5.5 0 0 0 ' +
    '.46.82c2.03-.25 3.66-1 4.86-1.86.83.2 1.69.3 2.56.3 5.02 0 9-3.58 9-8s-3.98-8.56-9-8.56z"/></svg>';
  var CLOSE_ICON =
    '<svg class="jw-close" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
    '<path fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" d="M6 6l12 12M18 6L6 18"/></svg>';

  function mount() {
    if (document.getElementById(HOST_ID)) return; // the snippet was pasted twice

    var host = document.createElement("div");
    host.id = HOST_ID;
    host.style.cssText = "all:initial;position:static";
    var root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;

    var style = document.createElement("style");
    style.textContent = CSS;
    var wrap = document.createElement("div");
    var panel = document.createElement("div");
    panel.className = "jw-panel";
    panel.id = "jw-panel";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "jw-btn";
    button.setAttribute("aria-controls", "jw-panel");
    button.innerHTML = BUBBLE_ICON + CLOSE_ICON;
    wrap.appendChild(panel);
    wrap.appendChild(button);
    root.appendChild(style);
    root.appendChild(wrap);
    document.body.appendChild(host);

    var open = false;
    var frame = null;
    var savedOverflow = null;
    var phone = window.matchMedia ? window.matchMedia(PHONE) : { matches: false };

    function lockPage(lock) {
      // Full-screen on phones: stop the page behind from scrolling while the chat is open.
      var page = document.documentElement;
      if (lock && savedOverflow === null) {
        savedOverflow = page.style.overflow;
        page.style.overflow = "hidden";
      } else if (!lock && savedOverflow !== null) {
        page.style.overflow = savedOverflow;
        savedOverflow = null;
      }
    }

    function render() {
      wrap.className = open ? "jw-open" : "";
      button.setAttribute("aria-expanded", open ? "true" : "false");
      button.setAttribute("aria-label", open ? "Close chat" : "Open chat");
      button.title = open ? "Close chat" : "Chat with us";
      panel.setAttribute("aria-hidden", open ? "false" : "true");
      lockPage(open && phone.matches);
    }

    function setOpen(next) {
      open = next;
      if (open && !frame) {
        // Load the chat on first open only, then keep it so the conversation survives closing.
        frame = document.createElement("iframe");
        frame.src = BASE + "/b/" + encodeURIComponent(SLUG) + "?embed=1";
        frame.title = "Chat";
        frame.setAttribute("allow", "clipboard-write");
        panel.appendChild(frame);
      }
      render();
      if (open) frame.focus();
    }

    button.addEventListener("click", function () { setOpen(!open); });
    document.addEventListener("keydown", function (event) {
      if (open && event.key === "Escape") {
        setOpen(false);
        button.focus();
      }
    });
    // The chat's own × button. Only messages from our iframe count.
    window.addEventListener("message", function (event) {
      if (!open || !frame || event.source !== frame.contentWindow) return;
      if (event.data && event.data.type === "jawab:close") {
        setOpen(false);
        button.focus();
      }
    });
    var onResize = function () { render(); };
    if (phone.addEventListener) phone.addEventListener("change", onResize);
    else if (phone.addListener) phone.addListener(onResize);
    render();
  }

  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
