// Glue between Telegram's WebApp runtime and htmx: every request carries the signed
// init data, the native back button follows the current screen, toasts get haptics.
(function () {
  const tg = window.Telegram && window.Telegram.WebApp;
  const initData = tg ? tg.initData : "";

  if (tg) {
    tg.ready();
    tg.expand();
    tg.BackButton.onClick(() => {
      const back = document.querySelector("#view [data-back]");
      if (back) htmx.ajax("GET", back.dataset.back, "#view");
    });
  }

  // hx-confirm through Telegram's own dialog: a plain window.confirm may not show up
  // inside the Mini App webview.
  document.body.addEventListener("htmx:confirm", (event) => {
    if (!event.detail.question || !tg || !tg.showConfirm) return;
    event.preventDefault();
    tg.showConfirm(event.detail.question, (ok) => ok && event.detail.issueRequest(true));
  });

  document.body.addEventListener("htmx:configRequest", (event) => {
    event.detail.headers["X-Telegram-Init-Data"] = initData;
  });

  document.body.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target.id !== "view") return;
    window.scrollTo({ top: 0 });
    const back = document.querySelector("#view [data-back]");
    if (tg) back ? tg.BackButton.show() : tg.BackButton.hide();
    if (window.showCarSplash) window.showCarSplash();
  });

  document.body.addEventListener("htmx:responseError", (event) => {
    let text = "Не получилось, попробуйте ещё раз";
    try {
      text = JSON.parse(event.detail.xhr.responseText).detail || text;
    } catch (_) { /* not a JSON error body */ }
    showToast(text, "error");
  });

  document.body.addEventListener("toast", (event) => showToast(event.detail.value, "success"));
  document.body.addEventListener("toastError", (event) => showToast(event.detail.value, "error"));

  let timer;
  function showToast(text, kind) {
    const el = document.getElementById("toast");
    el.textContent = text;
    el.classList.toggle("error", kind === "error");
    el.classList.add("show");
    clearTimeout(timer);
    timer = setTimeout(() => el.classList.remove("show"), kind === "error" ? 6000 : 2600);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(kind);
  }

  document.addEventListener("click", (event) => {
    if (tg && tg.HapticFeedback && event.target.closest("a, button, label")) {
      tg.HapticFeedback.selectionChanged();
    }
  });

  htmx.ajax("GET", "/app/home", "#view");
})();
