const erpMenuToggle = document.querySelector('.erp-menu-toggle');
const erpSidebar = document.getElementById('erp-sidebar');

// Management shell uses cp-mgmt.js (desktop collapse + phone drawer).
if (erpMenuToggle && erpSidebar && !document.querySelector('.cp-theme-mgmt')) {
  const mobileViewport = window.matchMedia('(max-width: 900px)');

  const showMenu = (open) => {
    erpMenuToggle.setAttribute('aria-expanded', String(open));
    erpSidebar.hidden = !open;
  };

  const syncViewport = () => {
    erpMenuToggle.hidden = !mobileViewport.matches;
    showMenu(!mobileViewport.matches);
  };

  erpMenuToggle.addEventListener('click', () => showMenu(erpSidebar.hidden));
  erpSidebar.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mobileViewport.matches) {
      showMenu(false);
      erpMenuToggle.focus();
    }
  });
  mobileViewport.addEventListener('change', syncViewport);
  syncViewport();
}
