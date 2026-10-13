(() => {
  document.querySelectorAll('.inventory-row-form').forEach((form) => {
    const row = form.closest('[data-stock-row]');
    const input = row.querySelector('[name="quantity"]');
    const button = form.querySelector('button');
    const message = form.querySelector('[role="status"]');
    let busy = false;
    let conflicted = false;
    const valid = () => /^[0-9]+$/.test(input.value) && input.checkValidity();
    const sync = () => {
      button.disabled =
        busy ||
        conflicted ||
        !valid() ||
        Number(input.value) === Number(form.elements.expected_stock.value);
    };
    input.addEventListener('input', () => {
      if (!conflicted) {
        message.textContent = '';
        input.removeAttribute('aria-invalid');
      }
      sync();
    });
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (button.disabled) return;
      busy = true;
      input.readOnly = true;
      message.textContent = 'Saving?';
      message.dataset.error = 'false';
      sync();
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
        const data = await response.json().catch(() => {
          throw new Error('Unable to save. Reload inventory and try again.');
        });
        if (!response.ok) {
          conflicted = response.status === 409;
          throw new Error(data.error || 'Unable to save stock. Reload inventory and try again.');
        }
        input.value = data.quantity;
        form.elements.expected_stock.value = data.quantity;
        form.elements.expected_updated_at.value = data.updated_at;
        const status = row.querySelector('[data-stock-status]');
        status.textContent = data.stock_level;
        status.className =
          'status-badge status-' + data.stock_level.toLowerCase().replaceAll(' ', '-');
        message.textContent = data.message;
        input.removeAttribute('aria-invalid');
      } catch (error) {
        message.textContent = error.message;
        message.dataset.error = 'true';
        input.setAttribute('aria-invalid', 'true');
      } finally {
        busy = false;
        input.readOnly = false;
        sync();
      }
    });
    sync();
  });
})();
