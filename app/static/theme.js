const root = document.documentElement;
const saved = localStorage.getItem('utm-theme');
if (saved === 'light' || saved === 'dark') root.dataset.theme = saved;
const toggle = document.getElementById('theme-toggle');
const updatePressed = () => toggle?.setAttribute('aria-pressed', String(root.dataset.theme === 'dark'));
updatePressed();
toggle?.addEventListener('click', () => {
  root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
  localStorage.setItem('utm-theme', root.dataset.theme);
  updatePressed();
});
