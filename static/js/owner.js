(() => {
  const shell = document.querySelector('.owner-shell');
  if (!shell) return;
  const sidebar = shell.querySelector('.owner-sidebar');
  const toggle = shell.querySelector('.owner-menu-toggle');
  const closeButton = shell.querySelector('.owner-menu-close');
  const backdrop = shell.querySelector('.owner-backdrop');
  const mobile = matchMedia('(max-width:1024px)');
  shell.classList.add('owner-enhanced');

  function close(restoreFocus = false) {
    shell.classList.remove('owner-menu-open');
    document.body.classList.remove('owner-menu-open');
    toggle.setAttribute('aria-expanded', 'false');
    backdrop.hidden = true;
    sidebar.inert = mobile.matches;
    sidebar.removeAttribute('role');
    sidebar.removeAttribute('aria-modal');
    if (restoreFocus && mobile.matches) toggle.focus();
  }
  function configure() {
    toggle.hidden = !mobile.matches;
    closeButton.hidden = !mobile.matches;
    close();
  }
  toggle.addEventListener('click', () => {
    sidebar.inert = false;
    shell.classList.add('owner-menu-open');
    document.body.classList.add('owner-menu-open');
    toggle.setAttribute('aria-expanded', 'true');
    sidebar.setAttribute('role', 'dialog');
    sidebar.setAttribute('aria-modal', 'true');
    backdrop.hidden = false;
    // Apply drawer visibility and inert changes before moving keyboard focus.
    closeButton.getBoundingClientRect();
    closeButton.focus({ preventScroll: true });
  });
  closeButton.addEventListener('click', () => close(true));
  backdrop.addEventListener('click', () => close(true));
  sidebar.addEventListener('click', event => {
    if (event.target.closest('a') && mobile.matches) close();
  });
  document.addEventListener('keydown', event => {
    if (!shell.classList.contains('owner-menu-open')) return;
    if (event.key === 'Escape') { event.preventDefault(); close(true); }
    if (event.key !== 'Tab') return;
    const items = [...sidebar.querySelectorAll('a,button')].filter(item => !item.hidden && !item.disabled);
    const first = items[0], last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  mobile.addEventListener('change', configure);
  configure();
})();
