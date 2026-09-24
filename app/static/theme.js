const root = document.documentElement;
const saved = localStorage.getItem('utm-theme');
if (saved) root.dataset.theme = saved;
document.getElementById('theme-toggle')?.addEventListener('click', () => {
  root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
  localStorage.setItem('utm-theme', root.dataset.theme);
});
