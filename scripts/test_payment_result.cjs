// Run the real payment page script with mocked DOM/fetch; never contacts eSewa.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../static/js/payment-result.js'), 'utf8');

function page(fetch) {
  const nodes = new Map();
  const node = (selector) => {
    if (selector === '[data-receipt]') return null;
    if (!nodes.has(selector))
      nodes.set(selector, {
        hidden: false,
        disabled: false,
        textContent: '',
        attrs: {},
        setAttribute(name, value) {
          this.attrs[name] = value;
        },
        removeAttribute(name) {
          delete this.attrs[name];
        },
      });
    return nodes.get(selector);
  };
  const form = node('[data-verify-form]');
  form.action = '/payments/original-uuid/recheck/';
  form.elements = { csrfmiddlewaretoken: { value: 'csrf-token' } };
  form.addEventListener = (name, handler) => {
    form.submit = handler;
  };
  const root = { querySelector: node, dataset: { state: 'pending' } };
  const navigations = [];
  let timeout;
  vm.runInNewContext(script, {
    document: { querySelector: () => root },
    window: { location: { assign: (url) => navigations.push(url) } },
    fetch,
    AbortController,
    Date,
    setTimeout: (handler) => {
      timeout = handler;
      return 1;
    },
    clearTimeout: () => {},
  });
  return {
    node,
    root,
    navigations,
    submit: () => form.submit({ preventDefault() {} }),
    timeout: () => timeout(),
  };
}

function reply(changes = {}) {
  return {
    headers: { get: () => 'application/json' },
    json: async () => ({
      status: 'PENDING',
      state: 'pending',
      symbol: '\u25f7',
      title: 'Awaiting verification',
      description: 'Payment pending.',
      message: 'Payment pending.',
      order_status: 'Pending',
      provider_status: 'PENDING',
      reference: 'Not available yet',
      last_verified_at: null,
      receipt_url: '',
      retry_url: '',
      can_continue: false,
      ...changes,
    }),
  };
}

test('real POST uses CSRF; loading disables the button and prevents overlapping requests', async () => {
  let resolve,
    calls = 0;
  const ui = page((url, options) => {
    calls++;
    assert.equal(url, '/payments/original-uuid/recheck/');
    assert.equal(options.method, 'POST');
    assert.equal(options.credentials, 'same-origin');
    assert.equal(options.headers['X-CSRFToken'], 'csrf-token');
    assert.equal(options.headers.Accept, 'application/json');
    assert.equal(options.body, undefined); // No browser amount/status/UUID supplied.
    return new Promise((done) => {
      resolve = done;
    });
  });
  const running = ui.submit();
  assert.equal(ui.node('[data-verify]').disabled, true);
  assert.equal(ui.node('.payment-spinner').hidden, false);
  assert.equal(ui.node('[data-button-text]').textContent, 'Checking payment\u2026');
  assert.equal(ui.node('[data-verify-form]').attrs['aria-busy'], 'true');
  await ui.submit();
  assert.equal(calls, 1);
  resolve(reply());
  await running;
  assert.equal(ui.node('[data-status]').textContent, 'PENDING');
  assert.equal(ui.node('[data-feedback]').textContent, 'Payment pending.');
  assert.equal(ui.node('[data-verify]').disabled, false);
  assert.equal(ui.node('.payment-spinner').hidden, true);
  assert.equal(ui.node('[data-receipt]'), null);
});

test('verified success displays reference/time without a receipt button', async () => {
  const ui = page(async () =>
    reply({
      status: 'PAID',
      state: 'success',
      symbol: '\u2713',
      title: 'Payment verified',
      reference: 'REF-123',
      last_verified_at: '2026-10-11T12:00:00Z',
      order_status: 'Confirmed',
      receipt_url: '/orders/BRM-1/receipt/',
    }),
  );
  await ui.submit();
  assert.equal(ui.node('[data-status]').textContent, 'PAID');
  assert.equal(ui.node('[data-reference]').textContent, 'REF-123');
  assert.equal(ui.node('[data-order-status]').textContent, 'Confirmed');
  assert.notEqual(ui.node('[data-verified]').textContent, 'Not checked successfully yet');
  assert.equal(ui.node('[data-receipt]'), null);
  assert.equal(ui.root.dataset.state, 'success');
});

test('canceled attempt exposes a fresh-attempt retry without a receipt button', async () => {
  const ui = page(async () =>
    reply({ status: 'CANCELLED', state: 'failed', symbol: '\u00d7', retry_url: '/retry/' }),
  );
  await ui.submit();
  assert.equal(ui.node('[data-status]').textContent, 'CANCELLED');
  assert.equal(ui.node('[data-retry]').hidden, false);
  assert.equal(ui.node('[data-receipt]'), null);
});

test('server verification error leaves the check available for retry', async () => {
  const ui = page(async () =>
    reply({
      ok: false,
      state: 'error',
      symbol: '!',
      title: 'Verification unavailable',
      message: 'eSewa unavailable. Try again.',
    }),
  );
  await ui.submit();
  assert.equal(ui.node('[data-feedback]').textContent, 'eSewa unavailable. Try again.');
  assert.equal(ui.node('[data-status]').textContent, 'PENDING');
  assert.equal(ui.node('[data-verify]').disabled, false);
});

test('network failure restores controls and a subsequent request can succeed', async () => {
  let calls = 0;
  const ui = page(async () => {
    if (++calls === 1) throw new Error('Network unavailable.');
    return reply();
  });
  await ui.submit();
  assert.match(ui.node('[data-feedback]').textContent, /Network unavailable/);
  assert.equal(ui.node('[data-verify]').disabled, false);
  await ui.submit();
  assert.equal(calls, 2);
  assert.equal(ui.node('[data-status]').textContent, 'PENDING');
});

test('expired login/HTML response explains recovery and restores controls', async () => {
  const ui = page(async () => ({ headers: { get: () => 'text/html' } }));
  await ui.submit();
  assert.match(ui.node('[data-feedback]').textContent, /sign in again/);
  assert.equal(ui.node('[data-verify]').disabled, false);
});

test('client timeout aborts the request and explains a safe recheck', async () => {
  const ui = page(
    (url, options) =>
      new Promise((resolve, reject) => {
        options.signal.addEventListener('abort', () =>
          reject(Object.assign(new Error(), { name: 'AbortError' })),
        );
      }),
  );
  const running = ui.submit();
  ui.timeout();
  await running;
  assert.match(ui.node('[data-feedback]').textContent, /try checking again shortly/);
  assert.equal(ui.node('[data-verify]').disabled, false);
  assert.equal(ui.node('.payment-spinner').hidden, true);
});

test('only verified paid results redirect to the server-selected exact order', async () => {
  const ui = page(async () =>
    reply({ ok: true, status: 'PAID', confirmation_url: '/orders/BRM-EXACT/' }),
  );
  await ui.submit();
  assert.deepEqual(ui.navigations, ['/orders/BRM-EXACT/']);
  for (const changes of [
    { ok: true, status: 'PENDING', confirmation_url: '/orders/BRM-EXACT/' },
    { ok: false, status: 'PAID', confirmation_url: '/orders/BRM-EXACT/' },
    { ok: true, status: 'PAID', confirmation_url: '' },
  ]) {
    const unresolved = page(async () => reply(changes));
    await unresolved.submit();
    assert.deepEqual(unresolved.navigations, []);
  }
});

test('failed check updates last-attempt time without inventing a verified time', async () => {
  const ui = page(async () =>
    reply({ ok: false, last_checked_at: '2026-10-11T12:00:00Z', last_verified_at: null }),
  );
  await ui.submit();
  assert.notEqual(ui.node('[data-checked]').textContent, 'Not checked yet');
  assert.equal(ui.node('[data-verified]').textContent, 'Not checked successfully yet');
  assert.equal(ui.node('[data-receipt]'), null);
});
