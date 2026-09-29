const STORAGE_KEY = 'utm-personal-v1';
function readPersonal() {
  try { return {version: 1, harnesses: [], routes: [], entities: [], comparison: [], ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')}; }
  catch (_) { return {version: 1, harnesses: [], routes: [], entities: [], comparison: []}; }
}
function writePersonal(value) { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(value)); return true; } catch (_) { return false; } }
function escapeHtml(value) { return String(value || '').replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char])); }
function routePayload(card) { const link = card.querySelector('.route-title'); return {key: card.dataset.routeKey, label: link?.textContent.trim(), via: card.querySelector('.route-via')?.textContent.trim(), href: link?.getAttribute('href')}; }
function refreshPinButtons() { const saved = readPersonal(); document.querySelectorAll('[data-pin-route]').forEach((button) => { const active = saved.routes.some((route) => route.key === button.closest('[data-route-key]')?.dataset.routeKey); button.classList.toggle('active', active); button.textContent = active ? '★' : '☆'; button.setAttribute('aria-pressed', String(active)); }); }
function refreshEntityPins() { const saved = readPersonal(); document.querySelectorAll('[data-pin-entity]').forEach((button) => { const active = saved.entities.some((item) => item.key === button.dataset.key); button.classList.toggle('active', active); button.textContent = active ? '★' : '☆'; button.setAttribute('aria-pressed', String(active)); }); }

document.addEventListener('click', (event) => {
  const compare = event.target.closest('[data-compare]');
  if (compare) {
    const ids = [...document.querySelectorAll('.compare-check input:checked')].map((input) => input.value);
    const feedback = document.querySelector('.compare-feedback');
    if (ids.length < 2 || ids.length > 5) { if (feedback) feedback.textContent = 'Select between 2 and 5 provider routes.'; return; }
    window.location.href = `/compare?ids=${ids.join(',')}`; return;
  }
  const pin = event.target.closest('[data-pin-route]');
  if (pin) {
    const saved = readPersonal(); const route = routePayload(pin.closest('[data-route-key]'));
    const index = saved.routes.findIndex((item) => item.key === route.key);
    if (index >= 0) saved.routes.splice(index, 1); else saved.routes.push(route);
    writePersonal(saved); refreshPinButtons(); return;
  }
  const entityPin = event.target.closest('[data-pin-entity]');
  if (entityPin) {
    const saved = readPersonal(); const item = {key: entityPin.dataset.key, label: entityPin.dataset.label, href: entityPin.dataset.href};
    const index = saved.entities.findIndex((entry) => entry.key === item.key);
    if (index >= 0) saved.entities.splice(index, 1); else saved.entities.push(item);
    writePersonal(saved); refreshEntityPins(); return;
  }
  if (event.target.closest('[data-save-comparison]')) {
    const saved = readPersonal(); saved.comparison = [...new URLSearchParams(location.search).getAll('ids').flatMap((value) => value.split(','))]; writePersonal(saved);
    const status = document.querySelector('.save-status'); if (status) status.textContent = 'Comparison saved on this device.';
  }
});

const setup = document.querySelector('[data-my-setup]');
if (setup) {
  const saved = readPersonal();
  setup.querySelectorAll('input[type=checkbox]').forEach((input) => { input.checked = saved.harnesses.includes(input.value); });
  const updateLink = () => { const values = [...setup.querySelectorAll('input:checked')].map((input) => input.value); const link = setup.querySelector('[data-setup-finder]'); link.href = values.length ? `/models?harnesses=${encodeURIComponent(values.join(','))}&tools=1&sort=value` : '/models'; };
  updateLink(); setup.addEventListener('change', updateLink);
  setup.querySelector('[data-save-setup]')?.addEventListener('click', () => { const state = readPersonal(); state.harnesses = [...setup.querySelectorAll('input:checked')].map((input) => input.value); const ok = writePersonal(state); setup.querySelector('.save-status').textContent = ok ? 'Setup saved locally. No keys or account data were stored.' : 'Browser storage is unavailable.'; updateLink(); });
  const pinned = document.querySelector('[data-pinned-routes]'); if (saved.routes.length) pinned.innerHTML = saved.routes.map((r) => `<a class="data-tile" href="${escapeHtml(r.href)}"><strong>${escapeHtml(r.label)}</strong><small>${escapeHtml(r.via)}</small></a>`).join('');
  const entities = document.querySelector('[data-pinned-entities]'); if (saved.entities.length) entities.innerHTML = saved.entities.map((item) => `<a class="data-tile" href="${escapeHtml(item.href)}"><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.key.split(':')[0])}</small></a>`).join('');
  const comparison = document.querySelector('[data-saved-comparison]'); if (saved.comparison.length) comparison.innerHTML = `<a class="button secondary" href="/compare?ids=${saved.comparison.join(',')}">Open saved comparison (${saved.comparison.length})</a>`;
}
refreshPinButtons();
refreshEntityPins();
