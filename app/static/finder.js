document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-compare]');
  if (!button) return;
  const ids = [...document.querySelectorAll('.compare-check input:checked')].map((input) => input.value);
  if (ids.length < 2 || ids.length > 5) { window.alert('Select between 2 and 5 provider routes to compare.'); return; }
  window.location.href = `/compare?ids=${ids.join(',')}`;
});
