const root = document.documentElement;
const saved = localStorage.getItem('utm-theme');
root.dataset.theme = saved === 'light' || saved === 'dark'
  ? saved
  : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
