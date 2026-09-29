const STORAGE_KEY = 'utm-personal-v1';
function readPersonal() {
  try { return {version: 1, harnesses: [], workflows: [], routes: [], entities: [], comparison: [], ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')}; }
  catch (_) { return {version: 1, harnesses: [], workflows: [], routes: [], entities: [], comparison: []}; }
}
function writePersonal(value) { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(value)); return true; } catch (_) { return false; } }
function escapeHtml(value) { return String(value || '').replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char])); }
function routePayload(card) { const model = card.querySelector('.route-title'); const route = card.querySelector('.route-link'); const pin = card.querySelector('[data-pin-route]'); return {key: card.dataset.routeKey, id: pin?.dataset.offeringId, label: model?.textContent.trim(), via: card.querySelector('.route-via')?.textContent.trim(), href: route?.getAttribute('href')}; }
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
  if (event.target.closest('[data-compare-shortlist]')) {
    const ids = readPersonal().routes.map((route) => route.id).filter(Boolean).slice(0, 5);
    const feedback = document.querySelector('.compare-feedback');
    if (ids.length < 2) { if (feedback) feedback.textContent = 'Pin at least two exact provider routes first.'; return; }
    window.location.href = `/compare?ids=${ids.join(',')}`;
  }
});

const setup = document.querySelector('[data-my-setup]');
if (setup) {
  const saved = readPersonal();
  if (setup.dataset.hasQuery !== 'true') setup.querySelectorAll('input[type=checkbox]').forEach((input) => { input.checked = input.name === 'harnesses' ? saved.harnesses.includes(input.value) : saved.workflows.includes(input.value); });
  setup.addEventListener('submit', () => { const state = readPersonal(); state.harnesses = [...setup.querySelectorAll('input[name=harnesses]:checked')].map((input) => input.value); state.workflows = [...setup.querySelectorAll('input[name=workflows]:checked')].map((input) => input.value); writePersonal(state); });
  const pinned = document.querySelector('[data-pinned-routes]'); if (saved.routes.length) pinned.innerHTML = saved.routes.map((r) => `<a class="data-tile" href="${escapeHtml(r.href)}"><strong>${escapeHtml(r.label)}</strong><small>${escapeHtml(r.via)}</small></a>`).join('');
  const entities = document.querySelector('[data-pinned-entities]'); if (saved.entities.length) entities.innerHTML = saved.entities.map((item) => `<a class="data-tile" href="${escapeHtml(item.href)}"><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.key.split(':')[0])}</small></a>`).join('');
  const comparison = document.querySelector('[data-saved-comparison]'); if (saved.comparison.length) comparison.innerHTML = `<a class="button secondary" href="/compare?ids=${saved.comparison.join(',')}">Open saved comparison (${saved.comparison.length})</a>`;
}
refreshPinButtons();
refreshEntityPins();
