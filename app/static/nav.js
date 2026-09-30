const menuButton = document.querySelector('.menu-toggle');
const nav = document.getElementById('primary-nav');
menuButton?.addEventListener('click', () => {
  const expanded = menuButton.getAttribute('aria-expanded') === 'true';
  menuButton.setAttribute('aria-expanded', String(!expanded));
  nav?.classList.toggle('menu-open', !expanded);
});
document.addEventListener('keydown', (event) => {
  if (event.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
    event.preventDefault();
    if (window.location.pathname === '/models') {
      document.getElementById('model-search')?.focus();
    } else {
      window.location.href = '/models#model-search';
    }
  }
});
