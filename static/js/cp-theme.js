(function () {
  const KEY = "cp-theme";
  const root = document.documentElement;

  function preferred() {
    try {
      const saved = localStorage.getItem(KEY);
      if (saved === "light" || saved === "dark") return saved;
    } catch (_) { /* LAN private mode */ }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-cp-theme-toggle]").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(theme === "dark"));
      const label = theme === "dark" ? btn.dataset.labelLight : btn.dataset.labelDark;
      if (label) btn.setAttribute("title", label);
      const icon = btn.querySelector("[data-lucide]");
      if (icon) icon.setAttribute("data-lucide", theme === "dark" ? "sun" : "moon");
    });
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons();
    }
  }

  apply(preferred());

  document.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-cp-theme-toggle]");
    if (!btn) return;
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    try { localStorage.setItem(KEY, next); } catch (_) { /* ignore */ }
    apply(next);
  });
})();
