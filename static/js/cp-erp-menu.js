const erpMenuToggle = document.querySelector('.erp-menu-toggle');
const erpSidebar = document.getElementById('erp-sidebar');

// Management shell uses cp-mgmt.js (desktop collapse + phone drawer).
if (erpMenuToggle && erpSidebar && !document.querySelector('.cp-theme-mgmt')) {
  const mobileViewport = window.matchMedia('(max-width: 900px)');
  let lastFocus = null;

  const firstFocusable = () =>
    erpSidebar.querySelector(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );

  const showMenu = (open) => {
    erpMenuToggle.setAttribute('aria-expanded', String(open));
    erpSidebar.hidden = !open;
    document.body.classList.toggle('cp-erp-nav-open', open && mobileViewport.matches);
    if (open && mobileViewport.matches) {
      lastFocus = document.activeElement;
      const target = firstFocusable();
      if (target) {
        window.requestAnimationFrame(() => target.focus());
      }
    } else if (!open && mobileViewport.matches) {
      const restore = lastFocus && document.contains(lastFocus) ? lastFocus : erpMenuToggle;
      window.requestAnimationFrame(() => restore.focus());
      lastFocus = null;
    }
  };

  const syncViewport = () => {
    erpMenuToggle.hidden = !mobileViewport.matches;
    // Mobile/tablet: start with drawer closed so page content is visible.
    showMenu(!mobileViewport.matches);
  };

  erpMenuToggle.addEventListener('click', () => showMenu(erpSidebar.hidden));
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (!mobileViewport.matches) return;
    if (erpSidebar.hidden) return;
    event.preventDefault();
    showMenu(false);
    erpMenuToggle.focus();
  });
  // Close drawer after choosing a destination (before navigation paints next page).
  erpSidebar.addEventListener('click', (event) => {
    if (!mobileViewport.matches) return;
    const link = event.target.closest('a[href]');
    if (link && erpSidebar.contains(link)) {
      showMenu(false);
    }
  });
  mobileViewport.addEventListener('change', syncViewport);
  syncViewport();
}
