(() => {
  const gallery = document.querySelector('.gallery');
  if (gallery) {
    gallery.querySelectorAll('.gallery-thumbnail').forEach(link => {
      const activate = event => {
        event.preventDefault();
        let image = gallery.querySelector('.product-image img');
        if (!image) {
          image = document.createElement('img');
          gallery.querySelector('.product-image').replaceChildren(image);
        }
        image.src = link.href;
        image.alt = link.querySelector('img').alt;
        image.classList.remove('image-changing');
        requestAnimationFrame(() => image.classList.add('image-changing'));
        gallery.querySelectorAll('.gallery-thumbnail').forEach(item => {
          item.setAttribute('aria-pressed', String(item === link));
        });
      };
      link.addEventListener('click', activate);
      link.addEventListener('keydown', event => {
        if (event.key === ' ') activate(event);
      });
    });
  }

  const form = document.querySelector('.variant-selector');
  if (!form) return;
  const select = form.querySelector('select[name=variant]');
  const visual = form.querySelector('.visual-variants');
  if (!select || !visual) return;

  // Only Django's existing available options can be submitted.
  const availableIds = new Set([...select.options].map(option => option.value));
  const variants = [...form.querySelectorAll('.variant-data [data-id]')].map(node => ({
    id: node.dataset.id,
    color: node.dataset.color,
    size: node.dataset.size,
    stock: Number(node.dataset.stock),
    available: availableIds.has(node.dataset.id)
  }));
  if (!variants.length) return;

  const swatches = {
    black: '#222', white: '#fafafa', grey: '#999', gray: '#999',
    beige: '#cdbb9e', cream: '#ece4d4', navy: '#26364d', brown: '#795b45',
    red: '#943e38', blue: '#5a7394', green: '#536752'
  };
  let color = '', size = '';
  const colors = [...new Set(variants.map(variant => variant.color))];
  const sizes = [...new Set(variants.map(variant => variant.size))];

  function draw() {
    [['color', colors], ['size', sizes]].forEach(([kind, values]) => {
      const area = visual.querySelector('.' + kind + '-options .selector-options');
      area.replaceChildren();
      values.forEach(value => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'selector-button';
        button.dataset.value = value;
        button.textContent = value;
        button.setAttribute('aria-pressed', String((kind === 'color' ? color : size) === value));
        button.disabled = !variants.some(variant => variant.available && (
          kind === 'color' ? variant.color === value :
          variant.size === value && (!color || variant.color === color)
        ));
        if (kind === 'color' && swatches[value.toLowerCase()]) {
          const dot = document.createElement('span');
          dot.className = 'color-dot';
          dot.style.background = swatches[value.toLowerCase()];
          dot.setAttribute('aria-hidden', 'true');
          button.prepend(dot);
        }
        button.addEventListener('click', () => {
          if (kind === 'color') {
            color = value;
            if (!variants.some(variant => variant.available && variant.color === color && variant.size === size)) size = '';
          } else {
            size = value;
          }
          const variant = variants.find(item => item.available && item.color === color && item.size === size);
          select.value = variant ? variant.id : '';
          select.dispatchEvent(new Event('change', { bubbles: true }));
          // Rebuilding the buttons must preserve keyboard focus.
          const nextButton = [...area.querySelectorAll('button')].find(item => item.dataset.value === value);
          if (nextButton) nextButton.focus({ preventScroll: true });
        });
        area.append(button);
      });
    });
    const selected = variants.find(variant => variant.id === select.value);
    visual.querySelector('.selection-stock').textContent = selected ?
      selected.stock + ' available' : 'Choose a color and size.';
  }
  select.addEventListener('change', () => {
    const selected = variants.find(variant => variant.id === select.value);
    if (selected) {
      color = selected.color;
      size = selected.size;
    }
    draw();
  });
  const initial = variants.find(variant => variant.id === select.value);
  if (initial) { color = initial.color; size = initial.size; }
  visual.hidden = false;
  draw();
  form.classList.add('variants-enhanced');
  select.addEventListener('invalid', event => {
    event.preventDefault();
    visual.querySelector('.selection-stock').textContent = 'Please choose an available color and size.';
    const first = visual.querySelector('button:not(:disabled)');
    if (first) first.focus();
  });
})();
