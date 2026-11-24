(function () {
  const shell = document.querySelector(".cp-theme-mgmt");
  if (!shell) return;

  const sidebar = document.getElementById("erp-sidebar");
  const toggles = document.querySelectorAll(
    ".cp-theme-mgmt .erp-menu-toggle, .cp-theme-mgmt .cp-mgmt-toggle"
  );
  const mobile = window.matchMedia("(max-width: 900px)");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const KEY = "cp-mgmt-nav-collapsed";

  let backdrop = document.querySelector(".cp-mgmt-backdrop");
  if (!backdrop) {
    backdrop = document.createElement("button");
    backdrop.type = "button";
    backdrop.className = "cp-mgmt-backdrop";
    backdrop.setAttribute("aria-label", "Yan menyunu bağla");
    backdrop.hidden = true;
    document.body.appendChild(backdrop);
  }

  const setExpanded = (open) => {
    toggles.forEach((btn) => btn.setAttribute("aria-expanded", String(open)));
  };

  const setMobileOpen = (open) => {
    if (open) {
      sidebar.hidden = false;
      sidebar.classList.add("is-drawer-open");
      backdrop.hidden = false;
      document.body.classList.add("cp-mgmt-drawer-open");
      setExpanded(true);
      const focusable = sidebar.querySelector(
        "a, button, summary, [tabindex]:not([tabindex='-1'])"
      );
      if (focusable) focusable.focus();
    } else {
      sidebar.classList.remove("is-drawer-open");
      backdrop.hidden = true;
      document.body.classList.remove("cp-mgmt-drawer-open");
      sidebar.hidden = true;
      setExpanded(false);
    }
  };

  const apply = () => {
    if (mobile.matches) {
      shell.classList.remove("cp-shell--nav-collapsed");
      const open = !sidebar.hidden && sidebar.classList.contains("is-drawer-open");
      setExpanded(open);
      return;
    }
    sidebar.hidden = false;
    sidebar.classList.remove("is-drawer-open");
    backdrop.hidden = true;
    document.body.classList.remove("cp-mgmt-drawer-open");
    const collapsed = shell.classList.contains("cp-shell--nav-collapsed");
    setExpanded(!collapsed);
  };

  const setDesktopCollapsed = (collapsed) => {
    shell.classList.toggle("cp-shell--nav-collapsed", collapsed);
    try {
      localStorage.setItem(KEY, collapsed ? "1" : "0");
    } catch (e) {}
    apply();
  };

  const toggleDesktop = () => {
    setDesktopCollapsed(!shell.classList.contains("cp-shell--nav-collapsed"));
  };

  const expandDesktop = () => {
    if (!shell.classList.contains("cp-shell--nav-collapsed")) return false;
    setDesktopCollapsed(false);
    return true;
  };

  // Collapsed (icon rail): click icon → expand to full nav + open that destination
  // (EstatePro-style). Direct links navigate; groups open and go to first child page.
  if (sidebar) {
    sidebar.addEventListener("click", (event) => {
      if (mobile.matches) return;
      if (!shell.classList.contains("cp-shell--nav-collapsed")) return;

      const direct = event.target.closest("a.cp-nav-direct");
      if (direct && sidebar.contains(direct)) {
        expandDesktop();
        return;
      }

      const summary = event.target.closest("summary.cp-nav-summary");
      if (!summary || !sidebar.contains(summary)) return;

      event.preventDefault();
      const details = summary.closest("details.cp-nav-group");
      expandDesktop();
      if (!details) return;
      details.open = true;
      sidebar.querySelectorAll("details.cp-nav-group").forEach((other) => {
        if (other !== details) other.open = false;
      });
      const first = details.querySelector(".cp-nav-group-body a[href]");
      if (first && first.getAttribute("href")) {
        window.location.assign(first.href);
      }
    });
  }

  toggles.forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      if (mobile.matches) {
        setMobileOpen(sidebar.hidden || !sidebar.classList.contains("is-drawer-open"));
        return;
      }
      toggleDesktop();
    });
  });

  backdrop.addEventListener("click", () => {
    if (mobile.matches) {
      setMobileOpen(false);
      const t = toggles[0];
      if (t) t.focus();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!mobile.matches) return;
    if (sidebar.hidden) return;
    setMobileOpen(false);
    const t = toggles[0];
    if (t) t.focus();
  });

  // Restore desktop collapse before first paint flash (class may already be on html)
  try {
    if (
      !mobile.matches &&
      (localStorage.getItem(KEY) === "1" ||
        document.documentElement.classList.contains("cp-mgmt-nav-preload-collapsed"))
    ) {
      shell.classList.add("cp-shell--nav-collapsed");
    }
  } catch (e) {}
  document.documentElement.classList.remove("cp-mgmt-nav-preload-collapsed");

  mobile.addEventListener("change", () => {
    if (mobile.matches) {
      setMobileOpen(false);
    } else {
      sidebar.hidden = false;
      apply();
    }
  });

  if (mobile.matches) {
    setMobileOpen(false);
  } else {
    apply();
  }

  // Group <details> open/close: avoid layout jump when reduced motion
  if (reduceMotion.matches) {
    shell.classList.add("cp-mgmt-reduce-motion");
  }
})();
