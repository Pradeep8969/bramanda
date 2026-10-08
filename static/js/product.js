(() => {
  if (typeof document === 'undefined') return;
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
    hex: node.dataset.colorHex,
    size: node.dataset.size,
    stock: Number(node.dataset.stock),
    available: availableIds.has(node.dataset.id)
  }));
  const selection = createVariantSelection(variants);
  const quantity = form.querySelector('input[name=quantity]');
  const cartButton = form.querySelector('.cart-button');
  const stockMessage = visual.querySelector('.selection-stock');

  function updateQuantity(clamp = false) {
    const selected = selection.current().variant;
    if (selected) {
      quantity.max = String(selected.stock);
      if (clamp && Number(quantity.value) > selected.stock) quantity.value = selected.stock;
    } else {
      quantity.removeAttribute('max');
    }
    quantity.disabled = !selected;
    const count = Number(quantity.value);
    const validQuantity = Number.isInteger(count) && count >= 1 && selected && count <= selected.stock;
    cartButton.disabled = !validQuantity;
    form.querySelectorAll('[data-quantity]').forEach(button => {
      button.disabled = !selected || (Number(button.dataset.quantity) < 0 ? count <= 1 : count >= selected.stock);
    });
    stockMessage.textContent = selected ? (validQuantity ? `${selected.stock} available` : `Choose a quantity from 1 to ${selected.stock}.`) :
      !variants.some(variant => variant.available && variant.stock > 0) ? 'Sold Out — no sizes are available.' :
      selection.current().color ? 'Choose an available size.' : 'Choose a color to see sizes.';
  }

  function draw() {
    const current = selection.current();
    select.value = current.variant ? current.variant.id : '';
    [['color', selection.colors()], ['size', selection.sizes()]].forEach(([kind, values]) => {
      const area = visual.querySelector('.' + kind + '-options .selector-options');
      area.replaceChildren();
      values.forEach(option => {
        const value = option.value;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'selector-button';
        button.dataset.value = value;
        button.textContent = value;
        button.setAttribute('aria-pressed', String(current[kind] === value));
        button.disabled = !option.available;
        if (!option.available) {
          button.title = `${value} — Sold Out`;
          button.setAttribute('aria-label', `${value} — Sold Out`);
        }
        if (kind === 'color' && option.hex) {
          const dot = document.createElement('span');
          dot.className = 'color-dot';
          dot.style.backgroundColor = option.hex;
          dot.setAttribute('aria-hidden', 'true');
          button.prepend(dot);
        }
        button.addEventListener('click', () => {
          if (!(kind === 'color' ? selection.chooseColor(value) : selection.chooseSize(value))) return;
          draw();
          // Rebuilding the buttons must preserve keyboard focus.
          const nextButton = [...area.querySelectorAll('button')].find(item => item.dataset.value === value);
          if (nextButton) nextButton.focus({ preventScroll: true });
        });
        area.append(button);
      });
    });
    updateQuantity(true);
  }
  select.addEventListener('change', () => {
    selection.selectVariant(select.value);
    draw();
  });
  selection.selectVariant(select.value);
  visual.hidden = false;
  draw();
  form.classList.add('variants-enhanced');
  quantity.addEventListener('input', () => updateQuantity());
  quantity.addEventListener('change', () => updateQuantity());
  window.addEventListener('pageshow', () => {
    selection.selectVariant(select.value);
    draw();
  });
  form.addEventListener('submit', event => {
    updateQuantity();
    if (cartButton.disabled) {
      event.preventDefault();
      stockMessage.textContent = 'Please choose an available color, size and quantity.';
    }
  });
  select.addEventListener('invalid', event => {
    event.preventDefault();
    visual.querySelector('.selection-stock').textContent = 'Please choose an available color and size.';
    const first = visual.querySelector('button:not(:disabled)');
    if (first) first.focus();
  });
})();

// The UI consumes only stock and variants supplied by Django, never a second inventory source.
function createVariantSelection(variants) {
  let color = '', size = '';
  const inStock = variant => variant.stock > 0 && variant.available;
  const matching = () => variants.find(variant => inStock(variant) && variant.color === color && variant.size === size);
  return {
    colors: () => [...new Set(variants.map(variant => variant.color))].map(value => ({
      value, available: variants.some(variant => inStock(variant) && variant.color === value),
      hex: variants.find(variant => variant.color === value).hex,
    })),
    sizes: () => [...new Set(variants.filter(variant => variant.color === color).map(variant => variant.size))].map(value => ({
      value, available: variants.some(variant => inStock(variant) && variant.color === color && variant.size === value),
    })),
    chooseColor(value) {
      if (!variants.some(variant => inStock(variant) && variant.color === value)) return false;
      color = value;
      if (!matching()) size = '';
      return true;
    },
    chooseSize(value) {
      if (!variants.some(variant => inStock(variant) && variant.color === color && variant.size === value)) return false;
      size = value;
      return true;
    },
    selectVariant(id) {
      const variant = variants.find(variant => inStock(variant) && variant.id === id);
      color = variant ? variant.color : '';
      size = variant ? variant.size : '';
    },
    current: () => ({ color, size, variant: matching() }),
  };
}

if (typeof module !== 'undefined' && module.exports) module.exports = { createVariantSelection };
