/**
 * matrix-rain.js — Matrix falling characters animation
 * Активируется только для скина cyberpunk
 */
(function () {
  'use strict';

  const CHARS = 'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
  const FONT_SIZE  = 14;
  const FPS        = 20;
  const INTERVAL   = 1000 / FPS;
  const BG_COLOR   = '#0a0e27';
  const HEAD_COLOR = '#ccffdd';  // яркий почти-белый зелёный — голова колонки
  const TRAIL_ALPHA = 0.05;      // скорость затухания хвоста

  let canvas, ctx, columns, animId, lastTs = 0;

  function build() {
    canvas = document.createElement('canvas');
    canvas.id = 'matrix-rain-canvas';
    Object.assign(canvas.style, {
      position:      'fixed',
      top:           '0',
      left:          '0',
      width:         '100%',
      height:        '100%',
      zIndex:        '-1',
      pointerEvents: 'none',
    });
    document.body.insertBefore(canvas, document.body.firstChild);
    ctx = canvas.getContext('2d');
    resize();
    window.addEventListener('resize', resize);
  }

  function resize() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    const count = Math.floor(canvas.width / FONT_SIZE);
    // Колонки стартуют в случайных позициях выше экрана для плавного появления
    columns = Array.from({ length: count }, () =>
      Math.floor(Math.random() * -(canvas.height / FONT_SIZE))
    );
    // Начальная заливка фоном
    ctx.fillStyle = BG_COLOR;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  function frame(ts) {
    animId = requestAnimationFrame(frame);
    if (ts - lastTs < INTERVAL) return;
    lastTs = ts;

    // Полупрозрачный overlay — создаёт эффект затухающего хвоста
    ctx.fillStyle = `rgba(10,14,39,${TRAIL_ALPHA})`;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.font      = `${FONT_SIZE}px monospace`;
    ctx.fillStyle = HEAD_COLOR;

    for (let i = 0; i < columns.length; i++) {
      const y = columns[i] * FONT_SIZE;
      if (y >= 0) {
        ctx.fillText(
          CHARS[Math.floor(Math.random() * CHARS.length)],
          i * FONT_SIZE,
          y
        );
      }
      // Сброс колонки после выхода за нижний край
      if (y > canvas.height && Math.random() > 0.975) {
        columns[i] = Math.floor(Math.random() * -40);
      } else {
        columns[i]++;
      }
    }
  }

  function start() {
    if (!canvas) build();
    canvas.style.display = 'block';
    if (!animId) animId = requestAnimationFrame(frame);
  }

  function stop() {
    if (animId) { cancelAnimationFrame(animId); animId = null; }
    if (canvas) canvas.style.display = 'none';
  }

  function check() {
    if (document.documentElement.getAttribute('data-skin') === 'cyberpunk') {
      start();
    } else {
      stop();
    }
  }

  window.addEventListener('skin-changed', check);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', check);
  } else {
    check();
  }
})();
