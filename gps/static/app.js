'use strict';
// Ajuda visual. Toda regra é validada novamente pelo servidor.
const form = document.querySelector('#movement-form');
if (form) {
  const balances = JSON.parse(document.querySelector('#balance-data').textContent);
  const sku = document.querySelector('#sku');
  const locationSelect = document.querySelector('#location');
  const destination = document.querySelector('#destination');
  const quantity = document.querySelector('#quantity');
  const kind = form.dataset.kind;
  const productOptions = [...document.querySelector('#products').options];
  function update() {
    const code = sku.value.trim().toUpperCase();
    const matches = productOptions.filter(option => option.dataset.code.toUpperCase() === code);
    const product = productOptions.find(option => option.value === code) || (matches.length === 1 ? matches[0] : null);
    for (const select of [locationSelect, destination].filter(Boolean)) {
      for (const option of select.options) {
        if (!option.value) continue;
        const compatible = product && option.dataset.brand === product.dataset.brand && option.dataset.type === product.dataset.type;
        option.hidden = !compatible;
        option.disabled = !compatible;
      }
      if (select.selectedOptions[0]?.disabled) select.value = '';
    }
    document.querySelector('#product-description').textContent = product ? product.textContent : matches.length > 1 ? 'Código compartilhado. Use o SKU interno.' : 'Selecione um SKU do catálogo.';
    const ready = product && locationSelect.value;
    const current = balances.find(b => b.sku === product?.value && b.location === locationSelect.value)?.quantity || 0;
    document.querySelector('#expected').value = ready ? current : '';
    const amount = Number(quantity.value);
    const valid = quantity.value !== '' && Number.isSafeInteger(amount) && amount >= (kind === 'count' ? 0 : 1);
    const after = kind === 'count' ? amount : current + (kind === 'in' ? amount : -amount);
    document.querySelector('#current-balance').textContent = ready ? `${current} ${product.dataset.unit}` : '—';
    document.querySelector('#next-balance').textContent = ready && valid ? `${after} ${product.dataset.unit}` : '—';
    document.querySelector('#preview-warning').textContent = !ready ? 'Escolha o produto e a locação.' :
      valid && after < 0 ? 'Saldo insuficiente. Esta operação será recusada.' :
      kind === 'transfer' && destination.value === locationSelect.value ? 'Origem e destino precisam ser diferentes.' :
      'Confira quantidade, unidade comercial e motivo antes de salvar.';
  }
  [sku,locationSelect,destination,quantity].filter(Boolean).forEach(input => input.addEventListener('input', update));
  sku.addEventListener('change', () => {sku.value=sku.value.trim().toUpperCase(); update();});
  if (form.classList.contains('collector-form')) {
    const originScan = document.querySelector('#scan-location');
    const destinationScan = document.querySelector('#scan-destination');
    sku.addEventListener('keydown', event => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      originScan.focus();
    });
    for (const [field, select, next] of [
      [originScan, locationSelect, destinationScan || quantity],
      [destinationScan, destination, quantity],
    ]) {
      if (!field) continue;
      field.addEventListener('input', () => field.setCustomValidity(''));
      field.addEventListener('keydown', event => {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        const code = field.value.trim().toUpperCase();
        const option = [...select.options].find(item => item.value && item.value === code && !item.disabled);
        field.setCustomValidity(option ? '' : 'Locação inexistente ou incompatível com o produto.');
        if (!field.reportValidity()) return;
        select.value = option.value;
        update();
        next.focus();
      });
    }
  }
  update();
}
