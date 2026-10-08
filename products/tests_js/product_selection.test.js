const test = require('node:test');
const assert = require('node:assert/strict');
const { createVariantSelection } = require('../../static/js/product.js');
const variants = [
  { id: '1', color: 'Black', size: 'S', stock: 3, available: true },
  { id: '2', color: 'Black', size: 'M', stock: 0, available: true },
  { id: '3', color: 'Beige', size: 'S', stock: 0, available: true },
  { id: '4', color: 'Beige', size: 'M', stock: 4, available: true },
  { id: '5', color: 'Red', size: 'S', stock: 0, available: true },
  { id: '6', color: 'White', size: 'S', stock: 2, available: false },
];

test('zero-stock and restricted colors cannot be selected', () => {
  const selection = createVariantSelection(variants);
  assert.deepEqual(selection.colors().map(option => option.available), [true, true, false, false]);
  assert.equal(selection.chooseColor('Red'), false);
  assert.equal(selection.chooseColor('White'), false);
  assert.equal(selection.chooseSize('S'), false);
  assert.equal(selection.current().variant, undefined);
});

test('sizes use only selected color stock and changing color clears unavailable size', () => {
  const selection = createVariantSelection(variants);
  assert.deepEqual(selection.sizes(), []);
  selection.chooseColor('Black');
  assert.deepEqual(selection.sizes(), [{ value: 'S', available: true }, { value: 'M', available: false }]);
  assert.equal(selection.chooseSize('M'), false);
  selection.chooseSize('S');
  assert.equal(selection.current().variant.id, '1');
  selection.chooseColor('Beige');
  assert.equal(selection.current().size, '');
  assert.equal(selection.current().variant, undefined);
  assert.equal(selection.chooseSize('S'), false);
  selection.chooseSize('M');
  assert.equal(selection.current().variant.id, '4');
});

test('changing color retains a size only when the new variant is in stock', () => {
  const selection = createVariantSelection([...variants, { id: '7', color: 'Blue', size: 'S', stock: 1, available: true }]);
  selection.selectVariant('1');
  selection.chooseColor('Blue');
  assert.equal(selection.current().size, 'S');
  assert.equal(selection.current().variant.id, '7');
});

test('invalid or sold-out fallback values cannot select a variant; empty products are safe', () => {
  const selection = createVariantSelection(variants);
  for (const id of ['2', '6', 'unknown']) {
    selection.selectVariant('1');
    selection.selectVariant(id);
    assert.equal(selection.current().variant, undefined);
    assert.equal(selection.current().color, '');
  }
  const empty = createVariantSelection([]);
  assert.deepEqual(empty.colors(), []);
  assert.deepEqual(empty.sizes(), []);
  assert.equal(empty.chooseColor('Black'), false);
});
