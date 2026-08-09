/* ===========================================================================
   MATN MAYDONLARINI KATTALASHTIRISH
   ---------------------------------------------------------------------------
   Muammo: dastlabki ko'rikda 9 ta matn maydoni bor va har biri 2–3 qator.
   Shifokor anamnezni to'liq yozganda matn ichkariga sig'may qoladi —
   yozganini ko'rish uchun maydon ichida aylantirish kerak bo'ladi. Bu
   uzun matnni o'qishni ham, tekshirishni ham qiyinlashtiradi.

   Yechim uch qavat:
     1) O'ZI O'SADI — yozgan sari maydon uzayadi (belgilangan chegaragacha)
     2) ⤢ KATTALASHTIRISH — katta oynada to'liq ekranga yaqin holda yozish
     3) Pastki burchakdan qo'lda cho'zish (brauzerning o'z imkoniyati)

   Sahifadagi HAR QANDAY <textarea> avtomatik shu imkoniyatni oladi.
   Kerak bo'lmasa: <textarea data-no-expand>.

   Bog'liqlik yo'q — faqat standart DOM.
   =========================================================================== */
(function () {
  'use strict';

  var MAX_AUTO_HEIGHT = 420;   // piksel: bundan keyin maydon ichida aylanadi
  var modal = null;
  var current = null;          // hozir kattalashtirilgan maydon

  /* ---------------------------------------------------------------- o'sish */
  function autoGrow(el) {
    if (!el) return;
    el.style.height = 'auto';
    var h = el.scrollHeight;
    el.style.height = Math.min(h, MAX_AUTO_HEIGHT) + 'px';
    el.style.overflowY = h > MAX_AUTO_HEIGHT ? 'auto' : 'hidden';
  }

  /* ---------------------------------------------------------- katta oyna */
  function buildModal() {
    if (modal) return modal;

    modal = document.createElement('div');
    modal.className = 'ta-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.hidden = true;
    modal.innerHTML =
      '<div class="ta-modal-box">' +
      '  <div class="ta-modal-head">' +
      '    <span class="ta-modal-title"></span>' +
      '    <div class="ta-modal-actions">' +
      '      <span class="ta-modal-count"></span>' +
      '      <button type="button" class="btn btn-sm btn-outline-secondary" data-ta-close>' +
      '        <i class="bi bi-x-lg"></i> Yopish</button>' +
      '      <button type="button" class="btn btn-sm btn-primary" data-ta-apply>' +
      '        <i class="bi bi-check2"></i> Tayyor</button>' +
      '    </div>' +
      '  </div>' +
      '  <textarea class="ta-modal-input form-control" spellcheck="true"></textarea>' +
      '  <div class="ta-modal-foot">' +
      '    <kbd>Esc</kbd> — yopish · <kbd>Ctrl</kbd>+<kbd>Enter</kbd> — tayyor' +
      '  </div>' +
      '</div>';
    document.body.appendChild(modal);

    var input = modal.querySelector('.ta-modal-input');
    var count = modal.querySelector('.ta-modal-count');

    function updateCount() {
      var n = input.value.length;
      count.textContent = n ? n + ' belgi' : '';
    }
    input.addEventListener('input', updateCount);

    modal.addEventListener('click', function (e) {
      // Fon bosilsa yopamiz, ichki qism bosilsa — yo'q
      if (e.target === modal) close(true);
      if (e.target.closest('[data-ta-close]')) close(false);
      if (e.target.closest('[data-ta-apply]')) close(true);
    });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); close(true); }
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); close(true); }
    });

    modal._input = input;
    modal._count = updateCount;
    return modal;
  }

  function open(el, label) {
    var m = buildModal();
    current = el;
    m.querySelector('.ta-modal-title').textContent = label || 'Matn';
    m._input.value = el.value;
    m._input.readOnly = el.disabled || el.readOnly;
    m.hidden = false;
    document.body.classList.add('ta-modal-open');
    m._count();
    m._input.focus();
    // Kursorni oxiriga qo'yamiz — odam odatda davomini yozadi.
    // Bu shunchaki qulaylik: qo'llab-quvvatlanmasa, oyna baribir ochilishi
    // kerak, shuning uchun xatoni yutamiz.
    try {
      m._input.setSelectionRange(m._input.value.length, m._input.value.length);
    } catch (e) { /* muhim emas */ }
  }

  function close(apply) {
    if (!modal) return;
    if (apply && current && !current.disabled && !current.readOnly) {
      current.value = modal._input.value;
      // Boshqa skriptlar (avtosaqlash va h.k.) xabardor bo'lsin
      current.dispatchEvent(new Event('input', { bubbles: true }));
      current.dispatchEvent(new Event('change', { bubbles: true }));
      autoGrow(current);
    }
    modal.hidden = true;
    document.body.classList.remove('ta-modal-open');
    if (current) current.focus();
    current = null;
  }

  /* ------------------------------------------------------------- ulanish */
  function enhance(el) {
    if (!el || el.dataset.expandReady === '1') return;
    if (el.hasAttribute('data-no-expand')) return;
    if (el.type === 'hidden' || el.offsetParent === null && el.closest('[hidden]')) {
      // Yashirin maydonlarga tegmaymiz, lekin modal ichidagilar ko'rinadi
    }
    el.dataset.expandReady = '1';

    var wrap = document.createElement('div');
    wrap.className = 'ta-wrap';
    el.parentNode.insertBefore(wrap, el);
    wrap.appendChild(el);

    var btn = document.createElement('button');
    btn.type = 'button';          // forma yuborilib ketmasin
    btn.className = 'ta-expand';
    btn.title = 'Kattalashtirish';
    btn.setAttribute('aria-label', 'Matnni kattalashtirish');
    btn.innerHTML = '<i class="bi bi-arrows-fullscreen"></i>';
    wrap.appendChild(btn);

    // Yorliqni topamiz — katta oynada sarlavha bo'lib chiqadi
    var label = '';
    if (el.id) {
      var l = document.querySelector('label[for="' + el.id + '"]');
      if (l) label = l.textContent.trim();
    }
    if (!label) {
      var prev = wrap.previousElementSibling;
      if (prev && prev.tagName === 'LABEL') label = prev.textContent.trim();
    }
    if (!label) label = el.getAttribute('placeholder') || 'Matn';

    btn.addEventListener('click', function () { open(el, label); });
    el.addEventListener('input', function () { autoGrow(el); });
    autoGrow(el);
  }

  function boot(root) {
    (root || document).querySelectorAll('textarea').forEach(enhance);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { boot(); });
  } else {
    boot();
  }
  // HTMX bilan kelgan yangi bo'laklar
  document.addEventListener('htmx:afterSwap', function (e) { boot(e.target); });
  // Bootstrap modali ochilganda o'lchamlar to'g'ri hisoblanadi
  document.addEventListener('shown.bs.modal', function (e) {
    e.target.querySelectorAll('textarea').forEach(function (t) {
      enhance(t); autoGrow(t);
    });
  });

  window.TextareaExpand = { boot: boot, autoGrow: autoGrow };
})();
