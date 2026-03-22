// ── Бургер-меню ───────────────────────────────────────────────────────────────
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


// ── Удаление карточки ─────────────────────────────────────────────────────────
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('.btn-delete');
  if (!btn) return;

  const card = btn.closest('.url-card');
  const urlId = card?.dataset.id;
  if (!urlId) return;

  if (!confirm('Удалить эту ссылку из базы? Действие необратимо.')) return;

  btn.disabled = true;
  btn.classList.add('opacity-50');

  try {
    const res = await fetch(`/api/urls/${urlId}`, { method: 'DELETE' });
    if (res.ok) {
      card.style.transition = 'opacity 0.2s, transform 0.2s';
      card.style.opacity = '0';
      card.style.transform = 'scale(0.97)';
      setTimeout(() => card.remove(), 200);
    } else {
      alert('Не удалось удалить. Попробуй снова.');
      btn.disabled = false;
      btn.classList.remove('opacity-50');
    }
  } catch {
    alert('Ошибка соединения.');
    btn.disabled = false;
    btn.classList.remove('opacity-50');
  }
});
