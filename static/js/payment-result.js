(() => {
  const root = document.querySelector('[data-payment-result]');
  if (!root) return;
  const form = root.querySelector('[data-verify-form]');
  const button = root.querySelector('[data-verify]');
  const feedback = root.querySelector('[data-feedback]');
  let running = false;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (running) return;
    running = true;
    button.disabled = true;
    form.setAttribute('aria-busy', 'true');
    root.querySelector('.payment-spinner').hidden = false;
    root.querySelector('[data-button-text]').textContent = 'Checking payment\u2026';
    feedback.textContent = 'Checking payment directly with eSewa\u2026';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        credentials: 'same-origin',
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
          'X-CSRFToken': form.elements.csrfmiddlewaretoken.value,
        },
      });
      if (!(response.headers.get('content-type') || '').includes('application/json')) {
        throw new Error(
          'Payment check unavailable. Refresh this page to sign in again, then retry.',
        );
      }
      const data = await response.json();
      if (data.status) {
        for (const [selector, value] of Object.entries({
          title: data.title,
          description: data.description,
          status: data.status,
          reference: data.reference,
          'order-status': data.order_status,
          provider: data.provider_status || 'Not available yet',
          checked: data.last_checked_at
            ? new Date(data.last_checked_at).toLocaleString()
            : 'Not checked yet',
          verified: data.last_verified_at
            ? new Date(data.last_verified_at).toLocaleString()
            : 'Not checked successfully yet',
        }))
          root.querySelector(`[data-${selector}]`).textContent = value;
        root.querySelector('[data-symbol]').textContent = data.symbol;
        root.dataset.state = data.state;
        root.querySelector('[data-retry]').hidden = !data.retry_url;
        root.querySelector('[data-continue]').hidden = !data.can_continue;
      }
      feedback.textContent = data.message || 'Unable to check payment. Please retry.';
      if (data.ok && data.status === 'PAID' && data.confirmation_url) {
        window.location.assign(data.confirmation_url);
      }
    } catch (error) {
      feedback.textContent =
        error.name === 'AbortError'
          ? 'The check took too long. Your payment remains unresolved; try checking again shortly.'
          : error.message || 'Connection failed. Please try checking again.';
    } finally {
      clearTimeout(timer);
      running = false;
      button.disabled = false;
      form.removeAttribute('aria-busy');
      root.querySelector('.payment-spinner').hidden = true;
      root.querySelector('[data-button-text]').textContent = 'Verify Payment';
    }
  });
})();
