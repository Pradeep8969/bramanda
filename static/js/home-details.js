/* Two image layers keep the editorial copy still and memory use bounded. */
(() => {
  const banner = document.querySelector('[data-details-slideshow]');
  const source = document.getElementById('home-details-images');
  if (!banner || !source || banner.dataset.initialized) return;
  banner.dataset.initialized = 'true';
  const slides = JSON.parse(source.textContent);
  const layers = [...banner.querySelectorAll('.home-details-slide')];
  if (slides.length < 2 || layers.length < 2) return;
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  let index = 0;
  let visible = 0;
  let timer = null;
  let generation = 0;
  const ready = (img) =>
    new Promise((resolve) => {
      if (img.complete) return resolve(img.naturalWidth > 0);
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
    });
  const preload = () => {
    const next = slides[(index + 1) % slides.length];
    layers[1 - visible].dataset.fit = next.fit;
    layers[1 - visible].src = next.url;
  };
  const stop = () => {
    clearTimeout(timer);
    timer = null;
    generation += 1;
  };
  const schedule = (delay = 5000) => {
    if (timer !== null || document.hidden || motion.matches) return;
    const token = generation;
    timer = setTimeout(async () => {
      const incoming = layers[1 - visible];
      const loaded = await ready(incoming);
      if (token !== generation || document.hidden || motion.matches) return;
      timer = null;
      index = (index + 1) % slides.length;
      if (loaded) {
        incoming.classList.add('is-visible');
        layers[visible].classList.remove('is-visible');
        visible = 1 - visible;
      }
      // Wait until the outgoing layer is transparent before reusing it.
      timer = setTimeout(() => {
        timer = null;
        preload();
        schedule(4300);
      }, 700);
    }, delay);
  };
  const resume = () => {
    stop();
    if (!document.hidden && !motion.matches) {
      preload();
      schedule();
    }
  };
  document.addEventListener('visibilitychange', resume);
  motion.addEventListener('change', resume);
  window.addEventListener('pagehide', stop);
  window.addEventListener('pageshow', resume);
  resume();
})();
