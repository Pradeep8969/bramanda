const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup(urls, reduced = false) {
  let now = 0,
    serial = 0;
  const timers = new Map(),
    events = {},
    mediaEvents = {};
  const layers = [true, false].map((active) => ({
    complete: true,
    naturalWidth: 800,
    dataset: {},
    classList: {
      active,
      add() {
        this.active = true;
      },
      remove() {
        this.active = false;
      },
    },
  }));
  const banner = { dataset: {}, querySelectorAll: () => layers };
  const document = {
    hidden: false,
    querySelector: () => banner,
    getElementById: () => ({
      textContent: JSON.stringify(
        urls.map((url) => ({ url, fit: url === 'b' ? 'cover' : 'contain' })),
      ),
    }),
    addEventListener: (name, callback) => {
      events[name] = callback;
    },
  };
  const motion = {
    matches: reduced,
    addEventListener: (name, callback) => {
      mediaEvents[name] = callback;
    },
  };
  const context = vm.createContext({
    document,
    matchMedia: () => motion,
    window: { addEventListener() {} },
    setTimeout(callback, delay) {
      const id = ++serial;
      timers.set(id, { at: now + delay, callback });
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
  });
  const script = fs.readFileSync('static/js/home-details.js', 'utf8');
  vm.runInContext(script, context);
  return {
    layers,
    timers,
    document,
    motion,
    events,
    mediaEvents,
    rerun: () => vm.runInContext(script, context),
    async tick(amount) {
      const end = now + amount;
      while (true) {
        const next = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
        if (!next || next[1].at > end) break;
        now = next[1].at;
        timers.delete(next[0]);
        await next[1].callback();
      }
      now = end;
    },
  };
}

test('zero/one image and reduced motion stay static', () => {
  for (const urls of [[], ['a']]) assert.equal(setup(urls).timers.size, 0);
  assert.equal(setup(['a', 'b'], true).timers.size, 0);
});

test('preloads, rotates every 5000ms, and reuses layers after 700ms', async () => {
  const s = setup(['a', 'b', 'c']);
  assert.equal(s.layers[1].src, 'b');
  assert.equal(s.layers[1].dataset.fit, 'cover');
  await s.tick(4999);
  assert.equal(s.layers[0].classList.active, true);
  await s.tick(1);
  assert.equal(s.layers[1].classList.active, true);
  await s.tick(700);
  assert.equal(s.layers[0].src, 'c');
  assert.equal(s.layers[0].dataset.fit, 'contain');
  await s.tick(4299);
  assert.equal(s.layers[1].classList.active, true);
  await s.tick(1);
  assert.equal(s.layers[0].classList.active, true);
  s.rerun();
  assert.equal(s.timers.size, 1);
});

test('hidden tabs and live reduced-motion changes pause and resume one timer', async () => {
  const s = setup(['a', 'b']);
  s.document.hidden = true;
  s.events.visibilitychange();
  assert.equal(s.timers.size, 0);
  await s.tick(20000);
  assert.equal(s.layers[0].classList.active, true);
  s.document.hidden = false;
  s.events.visibilitychange();
  assert.equal(s.timers.size, 1);
  s.motion.matches = true;
  s.mediaEvents.change();
  assert.equal(s.timers.size, 0);
  s.motion.matches = false;
  s.mediaEvents.change();
  assert.equal(s.timers.size, 1);
});

test('failed next image keeps current photograph visible', async () => {
  const s = setup(['a', 'broken', 'c']);
  s.layers[1].naturalWidth = 0;
  await s.tick(5000);
  assert.equal(s.layers[0].classList.active, true);
  await s.tick(700);
  assert.equal(s.layers[1].src, 'c');
});
