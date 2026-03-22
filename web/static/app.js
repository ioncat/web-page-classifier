// ── Бургер-меню ───────────────────────────────────────────────────────────────
const burger  = document.getElementById('burger');
const drawer  = document.getElementById('drawer');
const overlay = document.getElementById('overlay');

burger.addEventListener('click', () => {
  const open = !drawer.classList.contains('hidden');
  drawer.classList.toggle('hidden', open);
  overlay.classList.toggle('hidden', open);
});
overlay.addEventListener('click', () => {
  drawer.classList.add('hidden');
  overlay.classList.add('hidden');
});


// ── Helpers ───────────────────────────────────────────────────────────────────
function removeCard(card) {
  card.style.transition = 'opacity 0.2s, transform 0.2s';
  card.style.opacity = '0';
  card.style.transform = 'scale(0.97)';
  setTimeout(() => card.remove(), 200);
}

async function apiDelete(urlId) {
  const res = await fetch(`/api/urls/${urlId}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
}

async function apiPatchCategory(urlId, category) {
  const res = await fetch(`/api/urls/${urlId}/category`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category }),
  });
  if (!res.ok) throw new Error(`patch failed: ${res.status}`);
}

function getCardCategories(card) {
  return [...card.querySelectorAll('.card-cat-badge')].map(b => b.textContent.trim());
}

function updateCardBadges(card, category) {
  const footer = card.querySelector('.card-cat-badge')?.parentElement;
  if (!footer) return;
  card.querySelectorAll('.card-cat-badge').forEach(b => b.remove());
  const badge = document.createElement('a');
  badge.href = `/category/${encodeURIComponent(category)}`;
  badge.className = 'card-cat-badge text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 hover:bg-blue-100';
  badge.textContent = category;
  footer.appendChild(badge);
}

// Обновить счётчик категории в sidebar: delta = +1 или -1
function updateSidebarCount(category, delta) {
  document.querySelectorAll(`.sidebar-cat[data-category="${CSS.escape(category)}"]`).forEach(el => {
    const badge = el.querySelector('span:last-child');
    if (!badge) return;
    const val = parseInt(badge.textContent, 10);
    if (isNaN(val)) return;
    const next = val + delta;
    badge.textContent = next;
    if (next <= 0) el.closest('a,div')?.classList.add('opacity-40');
  });
}


// ── Удаление карточки ─────────────────────────────────────────────────────────
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('.btn-delete');
  if (!btn) return;

  const card  = btn.closest('.url-card');
  const urlId = card?.dataset.id;
  if (!urlId) return;

  if (!confirm('Удалить эту ссылку из базы? Действие необратимо.')) return;

  btn.disabled = true;
  try {
    await apiDelete(urlId);
    getCardCategories(card).forEach(cat => updateSidebarCount(cat, -1));
    removeCard(card);
  } catch (err) {
    alert('Ошибка удаления: ' + err.message);
    btn.disabled = false;
  }
});


// ── Модальное окно "Переместить" ──────────────────────────────────────────────
const moveModal        = document.getElementById('move-modal');
const moveModalOverlay = document.getElementById('move-modal-overlay');
const moveModalClose   = document.getElementById('move-modal-close');
let   activeMoveCard   = null;

function openMoveModal(card) {
  activeMoveCard = card;
  moveModal.classList.remove('hidden');
}

function closeMoveModal() {
  moveModal.classList.add('hidden');
  activeMoveCard = null;
}

moveModalOverlay?.addEventListener('click', closeMoveModal);
moveModalClose?.addEventListener('click', closeMoveModal);

document.addEventListener('click', (e) => {
  const btn = e.target.closest('.btn-move');
  if (!btn) return;
  const card = btn.closest('.url-card');
  if (card) openMoveModal(card);
});

document.getElementById('move-modal-list')?.addEventListener('click', async (e) => {
  const btn = e.target.closest('.modal-cat-btn');
  if (!btn || !activeMoveCard) return;

  const newCategory = btn.dataset.category;
  const urlId       = activeMoveCard.dataset.id;
  const card        = activeMoveCard;
  const oldCategories = getCardCategories(card);

  closeMoveModal();

  try {
    await apiPatchCategory(urlId, newCategory);
    oldCategories.forEach(cat => updateSidebarCount(cat, -1));
    updateSidebarCount(newCategory, +1);
    updateCardBadges(card, newCategory);
    card.style.outline = '2px solid #3b82f6';
    setTimeout(() => { card.style.outline = ''; }, 800);
  } catch (err) {
    alert('Не удалось переместить: ' + err.message);
  }
});


// ── Drag & Drop (десктоп) ─────────────────────────────────────────────────────
let draggedCard = null;

document.addEventListener('dragstart', (e) => {
  const card = e.target.closest('.url-card');
  if (!card) return;
  draggedCard = card;
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', card.dataset.id);
  setTimeout(() => card.classList.add('opacity-40'), 0);
});

document.addEventListener('dragend', () => {
  draggedCard?.classList.remove('opacity-40');
  draggedCard = null;
  document.querySelectorAll('.sidebar-cat').forEach(el =>
    el.classList.remove('bg-green-50', 'text-green-700', 'ring-2', 'ring-green-400')
  );
});

const sidebar = document.getElementById('sidebar');
sidebar?.addEventListener('dragover', (e) => {
  const cat = e.target.closest('.sidebar-cat');
  if (!cat) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  document.querySelectorAll('.sidebar-cat').forEach(el =>
    el.classList.remove('bg-green-50', 'text-green-700', 'ring-2', 'ring-green-400')
  );
  cat.classList.add('bg-green-50', 'text-green-700', 'ring-2', 'ring-green-400');
});

sidebar?.addEventListener('dragleave', (e) => {
  if (!sidebar.contains(e.relatedTarget)) {
    document.querySelectorAll('.sidebar-cat').forEach(el =>
      el.classList.remove('bg-green-50', 'text-green-700', 'ring-2', 'ring-green-400')
    );
  }
});

sidebar?.addEventListener('drop', async (e) => {
  e.preventDefault();
  const cat = e.target.closest('.sidebar-cat');
  if (!cat || !draggedCard) return;

  const newCategory   = cat.dataset.category;
  const urlId         = draggedCard.dataset.id;
  const card          = draggedCard;
  const oldCategories = getCardCategories(card);

  document.querySelectorAll('.sidebar-cat').forEach(el =>
    el.classList.remove('bg-green-50', 'text-green-700', 'ring-2', 'ring-green-400')
  );

  try {
    await apiPatchCategory(urlId, newCategory);
    oldCategories.forEach(c => updateSidebarCount(c, -1));
    updateSidebarCount(newCategory, +1);
    updateCardBadges(card, newCategory);
    card.classList.remove('opacity-40');
    card.style.outline = '2px solid #3b82f6';
    setTimeout(() => { card.style.outline = ''; }, 800);
  } catch (err) {
    alert('Не удалось переместить: ' + err.message);
  }
});
