const burger = document.getElementById('burger');
const drawer = document.getElementById('drawer');
const overlay = document.getElementById('overlay');

function openMenu() {
  drawer.classList.remove('hidden');
  overlay.classList.remove('hidden');
}

function closeMenu() {
  drawer.classList.add('hidden');
  overlay.classList.add('hidden');
}

burger.addEventListener('click', () => {
  drawer.classList.contains('hidden') ? openMenu() : closeMenu();
});

overlay.addEventListener('click', closeMenu);
