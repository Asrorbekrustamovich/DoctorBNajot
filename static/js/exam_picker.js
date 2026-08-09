/* ===========================================================================
   TEKSHIRUV TAYINLASH — «+Analiz / +EKG / +UZI / +Endoskop / +Rentgen»
   ---------------------------------------------------------------------------
   Vazifasi:
     · bir nechta tekshiruvni belgilash (guruhlar bo'ylab)
     · har guruhda va umumiy hisobda tanlanganlar soni + jami summa
     · «Tanlovni bekor qilish» — guruh bo'yicha va umumiy
     · «Bemorga tayinlash» — bir POST bilan hammasini yuborish

   Nima uchun alohida fayl: bu piker qabul modalida ham, statsionar
   ekranida ham ishlatiladi. Kod HTML ichida takrorlanmasligi kerak.

   Bog'liqlik: faqat Bootstrap 5 (modal) va standart DOM. jQuery kerak emas.
   =========================================================================== */
(function () {
  'use strict';

  /* ------------------------------------------------------------------
     MODALLARNI <body> GA KO'CHIRISH.

     Guruh modallari shablonda qabul oynasining ICHIDA chiziladi. Bu ikki
     xil buzilishga olib keladi:

       1) MODAL ICHIDA MODAL. Bootstrap 5 da ichkarisini yopganda
          <body> dan `modal-open` sinfi olib tashlanadi va fon (backdrop)
          yo'qoladi — tashqi qabul oynasi «singan» ko'rinadi, sahifa
          orqasi aylanib ketadi.

       2) FORMA ICHIDA INPUT. Qidiruv maydonida Enter bosilsa, u tashqi
          <form id="consultationForm"> ni YUBORADI, ya'ni shifokor
          bilmagan holda qabulni yakunlab qo'yadi.

     Ikkalasining ham yechimi bitta: modal tugunlarini <body> ga
     ko'chirish. Shablon o'qishga qulay bo'lib qoladi, DOM esa to'g'ri. */
  function detachModals() {
    document.querySelectorAll('.modal [id^="examModal-"]').forEach(function (m) {
      document.body.appendChild(m);
    });
  }

  function init(root) {
    if (!root || root.dataset.examPickerReady === '1') return;
    root.dataset.examPickerReady = '1';
    detachModals();

    var assignBtn = root.querySelector('#examAssignBtn');
    var clearAllBtn = root.querySelector('#examClearAll');
    var countEl = root.querySelector('#examPickedCount');
    var sumEl = root.querySelector('#examPickedSum');
    var msgEl = root.querySelector('#examPickerMsg');

    /* Modallar <body> ostiga ko'chirilgani uchun checkbox'larni root
       ichidan emas, butun hujjatdan qidiramiz.

       Allaqachon tayinlangan tekshiruvlar `disabled` bo'ladi va bu yerga
       tushmasligi kerak — aks holda «tanlovni bekor qilish» ularni ham
       yechib yuboradi. Filtrlash CSS selektoriga emas, JS xossasiga
       tayanadi: u har qanday muhitda bir xil ishlaydi. */
    function checks() {
      return Array.prototype.slice
        .call(document.querySelectorAll('.exam-check'))
        .filter(function (c) { return !c.disabled; });
    }

    function fmt(n) {
      return new Intl.NumberFormat('uz-UZ').format(Math.round(n));
    }

    function recount() {
      var picked = checks().filter(function (c) { return c.checked; });
      var total = picked.reduce(function (s, c) {
        return s + (parseFloat(c.dataset.price) || 0);
      }, 0);

      if (countEl) countEl.textContent = picked.length;
      if (sumEl) sumEl.textContent = fmt(total);
      if (assignBtn) assignBtn.disabled = picked.length === 0;
      if (clearAllBtn) clearAllBtn.disabled = picked.length === 0;

      // Guruh bo'yicha hisob
      var perGroup = {};
      picked.forEach(function (c) {
        var g = c.dataset.group;
        if (!perGroup[g]) perGroup[g] = { n: 0, sum: 0 };
        perGroup[g].n += 1;
        perGroup[g].sum += parseFloat(c.dataset.price) || 0;
      });

      document.querySelectorAll('[data-group-counter]').forEach(function (b) {
        var g = perGroup[b.dataset.groupCounter];
        b.textContent = g ? g.n : 0;
        b.classList.toggle('d-none', !g);
      });
      document.querySelectorAll('[data-group-picked]').forEach(function (el) {
        var g = perGroup[el.dataset.groupPicked];
        el.textContent = g ? g.n : 0;
      });
      document.querySelectorAll('[data-group-picked-badge]').forEach(function (el) {
        var g = perGroup[el.dataset.groupPickedBadge];
        el.textContent = g ? g.n : 0;
        el.classList.toggle('d-none', !g);
      });

      /* Qatorning ko'rinishi. Faqat katakchaning o'ziga tayanib bo'lmaydi —
         u kichkina va ro'yxat uzun bo'lganda ko'zga tashlanmaydi. Tanlangan
         qator ko'k ramka, ko'kimtir fon va ✓ bilan ajralib turadi. */
      Array.prototype.forEach.call(
        document.querySelectorAll('.exam-check'),
        function (c) {
          var item = c.closest('.exam-item');
          if (item) item.classList.toggle('is-picked', c.checked && !c.disabled);
        }
      );
      document.querySelectorAll('[data-group-sum]').forEach(function (el) {
        var g = perGroup[el.dataset.groupSum];
        el.textContent = fmt(g ? g.sum : 0);
      });
    }

    /* --- Hodisalar. Modal <body> ga ko'chgani uchun delegatsiya
           hujjat darajasida bo'lishi shart. --- */
    document.addEventListener('change', function (e) {
      if (e.target.classList && e.target.classList.contains('exam-check')) recount();
    });

    document.addEventListener('click', function (e) {
      var clear = e.target.closest && e.target.closest('[data-exam-clear]');
      if (clear) {
        var g = clear.dataset.examClear;
        checks().forEach(function (c) { if (c.dataset.group === g) c.checked = false; });
        recount();
      }
    });

    /* ----------------------------------------------------------------
       MODALLAR ZANJIRI: qabul oynasi → guruh oynasi → qabul oynasi.

       Bootstrap ikkita modalni bir vaqtda ochiq qoldirsa, orqa fon ikki
       qavat bo'lib qorayib ketadi va ichkarisini yopganda tashqarisi ham
       «o'lik» holatga tushadi. Shuning uchun guruh oynasi ochilishidan
       oldin qabul oynasi YASHIRILADI, yopilganda esa QAYTA ochiladi.
       Foydalanuvchi uchun bu oddiy «orqaga qaytish» bo'lib ko'rinadi.
       ---------------------------------------------------------------- */
    var parentModalEl = null;

    function bs(el) {
      return window.bootstrap
        ? window.bootstrap.Modal.getOrCreateInstance(el)
        : null;
    }

    function openGroup(id) {
      var target = document.getElementById(id);
      if (!target) return;
      var inst = bs(target);
      if (inst) inst.show(); else target.classList.add('show');
    }

    document.addEventListener('click', function (e) {
      var opener = e.target.closest && e.target.closest('[data-exam-open]');
      if (opener) {
        var id = opener.dataset.examOpen;
        var parent = opener.closest('.modal');
        if (!parent) { openGroup(id); return; }

        // Avval ota-oyna to'liq yopilishini kutamiz, keyin guruhni ochamiz
        parentModalEl = parent;
        parent.addEventListener('hidden.bs.modal', function once() {
          parent.removeEventListener('hidden.bs.modal', once);
          openGroup(id);
        });
        var pi = bs(parent);
        if (pi) pi.hide(); else { parent.classList.remove('show'); openGroup(id); }
        return;
      }

      var back = e.target.closest && e.target.closest('[data-exam-back]');
      if (back) {
        var m = back.closest('.modal');
        var bi = m && bs(m);
        if (bi) bi.hide(); else if (m) m.classList.remove('show');
      }
    });

    // Guruh oynasi yopilgach — qabul oynasini qaytaramiz («orqaga»)
    document.addEventListener('hidden.bs.modal', function (e) {
      if (!e.target.id || e.target.id.indexOf('examModal-') !== 0) return;
      if (!parentModalEl) return;
      var back = parentModalEl;
      parentModalEl = null;
      var inst = bs(back);
      if (inst) inst.show(); else back.classList.add('show');
    });

    /* Qidiruv maydonida Enter — formani yubormasin. Modal <body> ga
       ko'chirilgani uchun bu endi sodir bo'lmasligi kerak, lekin
       himoya ikki qavat bo'lgani ma'qul: yakunlangan qabulni orqaga
       qaytarib bo'lmaydi. */
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      if (e.target.closest && e.target.closest('[data-exam-search]')) {
        e.preventDefault();
      }
    });

    document.addEventListener('input', function (e) {
      var box = e.target.closest && e.target.closest('[data-exam-search]');
      if (!box) return;
      var q = box.value.trim().toLowerCase();
      var modal = box.closest('.modal');
      if (!modal) return;
      modal.querySelectorAll('.exam-row').forEach(function (row) {
        row.classList.toggle('d-none', q && row.dataset.examName.indexOf(q) < 0);
      });
    });

    if (clearAllBtn) {
      clearAllBtn.addEventListener('click', function () {
        checks().forEach(function (c) { c.checked = false; });
        recount();
      });
    }

    if (assignBtn) {
      assignBtn.addEventListener('click', function () {
        var picked = checks().filter(function (c) { return c.checked; });
        if (!picked.length) return;

        assignBtn.disabled = true;
        var old = assignBtn.innerHTML;
        assignBtn.innerHTML =
          '<span class="spinner-border spinner-border-sm"></span> Yuborilmoqda…';

        var body = new FormData();
        picked.forEach(function (c) { body.append('services', c.value); });
        var tok = document.querySelector('[name=csrfmiddlewaretoken]');
        if (tok) body.append('csrfmiddlewaretoken', tok.value);

        fetch(assignBtn.dataset.url, {
          method: 'POST',
          body: body,
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
          credentials: 'same-origin'
        })
          .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
          .then(function (res) {
            if (!res.ok) throw new Error(res.d.error || 'Xatolik');
            show('success', res.d.message || 'Tayinlandi.');
            // Tayinlanganlar endi qayta tanlanmasligi kerak
            picked.forEach(function (c) {
              c.checked = true;
              c.disabled = true;
              var wrap = c.closest('.form-check');
              if (wrap) wrap.classList.add('bg-light');
            });
            recount();
            document.dispatchEvent(new CustomEvent('exams:assigned', {
              detail: { count: picked.length }
            }));
          })
          .catch(function (err) { show('danger', err.message); })
          .then(function () {
            assignBtn.innerHTML = old;
            recount();
          });
      });
    }

    function show(kind, text) {
      if (!msgEl) return;
      msgEl.innerHTML =
        '<div class="alert alert-' + kind + ' py-2 px-3 mb-0 small">' +
        text.replace(/</g, '&lt;') + '</div>';
      if (kind === 'success') {
        setTimeout(function () { msgEl.innerHTML = ''; }, 6000);
      }
    }

    recount();
  }

  function boot() {
    document.querySelectorAll('#examPicker').forEach(init);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
  // HTMX bilan yuklangan modallar uchun
  document.addEventListener('htmx:afterSwap', boot);

  window.ExamPicker = { init: boot };
})();
