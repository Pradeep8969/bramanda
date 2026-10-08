(() => {
  const form = document.querySelector('.checkout-page .checkout-form');
  if (!form) return;
  const radios = form.querySelectorAll('input[name="payment_method"]');
  const submit = form.querySelector('[data-checkout-submit]');
  const updatePaymentSelection = () => {
    let selectedMethod = '';
    radios.forEach((radio) => {
      radio.closest('.checkout-payment-option')?.classList.toggle('is-selected', radio.checked);
      if (radio.checked) selectedMethod = radio.value;
    });
    if (submit) {
      submit.textContent = selectedMethod === 'ESEWA' ? 'Continue to eSewa →' : 'Place Order →';
    }
  };
  form.addEventListener('change', (event) => {
    if (event.target.matches('input[name="payment_method"]')) updatePaymentSelection();
  });
  window.addEventListener('pageshow', updatePaymentSelection);
  updatePaymentSelection();
})();
