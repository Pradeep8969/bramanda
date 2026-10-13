(() => {
  document.querySelectorAll('[data-message]').forEach((message) => {
    const close = message.querySelector('[data-dismiss-message]');
    let dismissing = false;
    let timer;
    const dismiss = () => {
      if (dismissing) return;
      dismissing = true;
      clearTimeout(timer);
      if (document.activeElement === close) {
        document.querySelector('#main-content')?.focus({ preventScroll: true });
      }
      message.classList.add('is-dismissing');
      setTimeout(() => message.remove(), 250);
    };
    if (close) {
      close.hidden = false;
      close.addEventListener('click', dismiss);
    }
    const delay = Number(message.dataset.autoDismiss);
    if (delay > 0) timer = setTimeout(dismiss, delay);
  });
  // Browser back/forward caches can otherwise restore a consumed flash notification.
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) {
      document
        .querySelectorAll('[data-message][data-auto-dismiss]')
        .forEach((message) => message.remove());
    }
  });
})();
