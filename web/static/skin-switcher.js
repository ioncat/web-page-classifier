/**
 * Skin Switcher - управление темами оформления
 */

(function() {
  const SKIN_KEY = 'app-skin';
  const DEFAULT_SKIN = 'minimalism';
  const AVAILABLE_SKINS = ['minimalism', 'cyberpunk']; // Расширяется в будущем

  /**
   * Получить сохранённый скин или значение по умолчанию
   */
  function getSavedSkin() {
    const saved = localStorage.getItem(SKIN_KEY);
    return (saved && AVAILABLE_SKINS.includes(saved)) ? saved : DEFAULT_SKIN;
  }

  /**
   * Установить скин и сохранить его
   */
  function setSkin(skinName) {
    if (!AVAILABLE_SKINS.includes(skinName)) {
      console.warn(`Skin "${skinName}" not available`);
      return false;
    }

    document.documentElement.setAttribute('data-skin', skinName);
    localStorage.setItem(SKIN_KEY, skinName);

    // Dispatch event для других скриптов
    window.dispatchEvent(new CustomEvent('skin-changed', { detail: { skin: skinName } }));

    return true;
  }

  /**
   * Инициализировать скин при загрузке страницы
   */
  function initSkin() {
    const skin = getSavedSkin();
    setSkin(skin);
  }

  // Экспортировать функции в глобальную область
  window.SkinSwitcher = {
    getSkin: () => document.documentElement.getAttribute('data-skin'),
    setSkin: setSkin,
    getAvailableSkins: () => [...AVAILABLE_SKINS],
  };

  // Инициализировать при загрузке документа
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSkin);
  } else {
    initSkin();
  }
})();
