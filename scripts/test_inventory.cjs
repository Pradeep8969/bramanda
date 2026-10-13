const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../static/js/inventory.js'), 'utf8');

function page(fetch) {
  const events = {};
  const input = {
    value: '12',
    attrs: {},
    checkValidity() {
      return Number(this.value) >= 0 && Number(this.value) <= 2147483647;
    },
    addEventListener: (name, callback) => {
      events[name] = callback;
    },
    setAttribute(name, value) {
      this.attrs[name] = value;
    },
    removeAttribute(name) {
      delete this.attrs[name];
    },
  };
  const button = {};
  const message = { dataset: {} };
  const status = {};
  const row = { querySelector: (selector) => (selector === '[name="quantity"]' ? input : status) };
  const form = {
    action: '/owner/inventory/update/',
    closest: () => row,
    elements: { expected_stock: { value: '12' }, expected_updated_at: { value: 'old' } },
    querySelector: (selector) => (selector === 'button' ? button : message),
    addEventListener: (name, callback) => {
      events[name] = callback;
    },
  };
  vm.runInNewContext(script, {
    document: { querySelectorAll: () => [form] },
    fetch,
    FormData: class {
      constructor(form) {
        this.form = form;
      }
    },
  });
  return {
    input,
    button,
    message,
    status,
    form,
    edit(value) {
      input.value = value;
      events.input();
    },
    save: () => events.submit({ preventDefault() {} }),
  };
}

test('unchanged and invalid totals disable Save', () => {
  const ui = page();
  assert.equal(ui.button.disabled, true);
  for (const value of ['-1', '1.5', '', '2147483648', '12']) {
    ui.edit(value);
    assert.equal(ui.button.disabled, true);
  }
  ui.edit('20');
  assert.equal(ui.button.disabled, false);
});

test('save updates total, version and availability without reload', async () => {
  let finish;
  const ui = page(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  ui.edit('0');
  const pending = ui.save();
  assert.equal(ui.button.disabled, true);
  assert.equal(ui.input.readOnly, true);
  finish({
    ok: true,
    json: async () => ({
      quantity: 0,
      updated_at: 'new',
      stock_level: 'Out of Stock',
      message: 'Stock saved.',
    }),
  });
  await pending;
  assert.equal(ui.input.value, 0);
  assert.equal(ui.form.elements.expected_updated_at.value, 'new');
  assert.equal(ui.status.className, 'status-badge status-out-of-stock');
  assert.equal(ui.message.textContent, 'Stock saved.');
  assert.equal(ui.button.disabled, true);
});

test('stale conflict stays visible and blocks further saving', async () => {
  const ui = page(async () => ({
    ok: false,
    status: 409,
    json: async () => ({ error: 'Reload inventory before saving again.' }),
  }));
  ui.edit('20');
  await ui.save();
  assert.equal(ui.message.dataset.error, 'true');
  assert.equal(ui.input.attrs['aria-invalid'], 'true');
  ui.edit('21');
  assert.equal(ui.button.disabled, true);
  assert.match(ui.message.textContent, /Reload/);
});

test('network failure displays error and permits retry', async () => {
  const ui = page(async () => {
    throw new Error('Network unavailable');
  });
  ui.edit('20');
  await ui.save();
  assert.equal(ui.message.textContent, 'Network unavailable');
  assert.equal(ui.button.disabled, false);
  assert.equal(ui.input.readOnly, false);
});
