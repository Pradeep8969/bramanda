const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../static/js/messages.js'), 'utf8');

function page(autoDismiss = '5000') {
  let now = 0,
    nextId = 0,
    click,
    pageshow;
  const timers = new Map();
  const close = {
    hidden: true,
    addEventListener: (_event, callback) => {
      click = callback;
    },
  };
  const classes = new Set();
  const message = {
    dataset: { autoDismiss },
    classList: { add: (name) => classes.add(name) },
    querySelector: () => close,
    removed: false,
    remove() {
      this.removed = true;
    },
  };
  const main = {
    focused: false,
    focus() {
      this.focused = true;
    },
  };
  const document = {
    activeElement: null,
    querySelector: () => main,
    querySelectorAll: (selector) =>
      selector.includes('[data-auto-dismiss]') && !autoDismiss ? [] : [message],
  };
  const tick = (duration) => {
    const end = now + duration;
    while (true) {
      const due = [...timers]
        .filter(([, timer]) => timer.at <= end)
        .sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]);
      now = due[1].at;
      due[1].callback();
    }
    now = end;
  };
  vm.runInNewContext(script, {
    document,
    window: {
      addEventListener: (_event, callback) => {
        pageshow = callback;
      },
    },
    setTimeout: (callback, delay) => {
      timers.set(++nextId, { callback, at: now + delay });
      return nextId;
    },
    clearTimeout: (id) => timers.delete(id),
  });
  return {
    message,
    close,
    classes,
    main,
    document,
    tick,
    click: () => click(),
    pageshow: (persisted) => pageshow({ persisted }),
  };
}

test('success remains visible for five seconds, then fades before removal', () => {
  const ui = page();
  assert.equal(ui.close.hidden, false);
  ui.tick(4999);
  assert.equal(ui.classes.has('is-dismissing'), false);
  ui.tick(1);
  assert.equal(ui.classes.has('is-dismissing'), true);
  assert.equal(ui.message.removed, false);
  ui.tick(250);
  assert.equal(ui.message.removed, true);
});

test('manual close dismisses early and handles repeated clicks safely', () => {
  const ui = page();
  ui.tick(1000);
  ui.click();
  ui.click();
  assert.equal(ui.classes.has('is-dismissing'), true);
  ui.tick(250);
  assert.equal(ui.message.removed, true);
  ui.tick(5000);
  assert.equal(ui.message.removed, true);
});

test('other notifications remain visible until manually dismissed', () => {
  const ui = page('');
  ui.tick(10000);
  assert.equal(ui.message.removed, false);
  ui.click();
  ui.tick(250);
  assert.equal(ui.message.removed, true);
});

test('dismissal moves keyboard focus out of the removed close button', () => {
  const ui = page();
  ui.document.activeElement = ui.close;
  ui.click();
  assert.equal(ui.main.focused, true);
});

test('back-forward cache cannot restore consumed success notifications', () => {
  const ui = page();
  ui.pageshow(false);
  assert.equal(ui.message.removed, false);
  ui.pageshow(true);
  assert.equal(ui.message.removed, true);
  const error = page('');
  error.pageshow(true);
  assert.equal(error.message.removed, false);
});
