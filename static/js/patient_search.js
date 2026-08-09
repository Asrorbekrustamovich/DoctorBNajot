/* ===========================================================================
   BEMOR TEZKOR QIDIRUVI — ro'yxatni filtrlaydi
   ---------------------------------------------------------------------------
   Ishlatilishi (faqat belgilash, JS yozish shart emas):

       <input data-patient-search="bemorSelect" data-hint="hintId">
       <select id="bemorSelect">
         <option value="">-- Tanlang --</option>
         <option value="…" data-search="familiya ism jshshir metrika pasport karta">…</option>
       </select>

   Nima uchun umumiy fayl: bir xil qidiruv uch joyda kerak (kravat berish,
   operatsiya rejalashtirish, epizod). Har birida alohida yozilgani uchun
   ikkitasi buzuq edi:
     · shablon `pinfl` / `passport_number` deb yozgan — bunday maydonlar yo'q
     · jarrohlik oynasida `&& .hasClass(...)` degan sintaksis xatosi bor edi
       va butun skript bloki umuman ishlamagan

   Qidiriladi: F.I.Sh., JSHSHIR, metrika, pasport, karta raqami.
   Bo'shliq va tirelar hisobga olinmaydi («I-AB 123456» = «iab123456»).
   =========================================================================== */
(function () {
  'use strict';

  function norm(s) {
    return (s || '').toLowerCase().replace(/[\s\-]/g, '');
  }

  function setup(box) {
    if (box.dataset.patientSearchReady === '1') return;
    box.dataset.patientSearchReady = '1';

    var sel = document.getElementById(box.dataset.patientSearch);
    if (!sel) return;
    var hint = box.dataset.hint ? document.getElementById(box.dataset.hint) : null;

    var all = Array.prototype.slice.call(sel.options)
      .filter(function (o) { return o.value; })
      .map(function (o) {
        return {
          value: o.value,
          text: o.textContent,
          key: (o.getAttribute('data-search') || o.textContent).toLowerCase(),
        };
      });

    function apply() {
      var q = box.value.trim().toLowerCase();
      var qn = norm(q);
      var hits = !q ? all : all.filter(function (o) {
        return o.key.indexOf(q) >= 0 || norm(o.key).indexOf(qn) >= 0;
      });

      /* Joriy tanlovni option'dan o'qiymiz, `sel.value` dan emas.
         Yozish `option.selected` orqali bo'lgani uchun o'qishni ham
         shunday qilish kerak — aks holda ikkalasi bir-biriga mos
         kelmay, foydalanuvchining tanlovi filtrlashda yo'qoladi. */
      var chosen = Array.prototype.filter.call(
        sel.options, function (o) { return o.selected && o.value; })[0];
      var keep = chosen ? chosen.value : '';

      sel.innerHTML = '';
      var first = document.createElement('option');
      first.value = '';
      first.textContent = hits.length ? '-- Tanlang --' : '-- Topilmadi --';
      sel.appendChild(first);
      hits.forEach(function (o) {
        var e = document.createElement('option');
        e.value = o.value;
        e.textContent = o.text;
        sel.appendChild(e);
      });

      /* Tanlashni `select.value = …` orqali emas, option'ning o'zida
         qilamiz. Ba'zi muhitlarda `value` o'rnatgichi ishlamaydi va
         tanlov jimgina yo'qoladi — bu esa «tanladim, lekin bo'sh
         yuborildi» degan eng yoqimsiz xatoni beradi.

         DIQQAT: FAQAT keraklisiga `true` beriladi. Avval hammasiga
         `false` berib chiqsak, oxirgi `false` yangi qo'yilgan `true` ni
         bekor qiladi — bitta tanlovli ro'yxatda ular bitta ichki
         holatni (selectedIndex) baham ko'radi. Bitta tanlovli ro'yxat
         qolganlarini o'zi bo'shatadi. */
      function choose(v) {
        var target = Array.prototype.filter.call(
          sel.options, function (o) { return o.value === v; })[0];
        if (target) target.selected = true;
      }
      if (hits.length === 1) choose(hits[0].value);
      else if (keep && hits.some(function (o) { return o.value === keep; })) choose(keep);

      if (hint) {
        hint.textContent = !q
          ? "Yozgan sari ro'yxat qisqaradi. Bitta bemor qolsa — o'zi tanlanadi."
          : hits.length === 0 ? 'Mos bemor topilmadi.'
          : hits.length === 1 ? 'Bitta bemor topildi va tanlandi.'
          : hits.length + ' ta bemor topildi.';
        hint.className = 'form-text ' + (hits.length ? 'text-success' : 'text-danger');
      }

      if (window.jQuery && window.jQuery.fn.select2) {
        window.jQuery(sel).trigger('change.select2');
      }
    }

    box.addEventListener('input', apply);
    // Qidiruv maydonida Enter formani YUBORMASIN — aks holda
    // yarim to'ldirilgan forma jo'nab ketadi.
    box.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); apply(); }
    });
  }

  function boot(root) {
    (root || document).querySelectorAll('[data-patient-search]').forEach(setup);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { boot(); });
  } else {
    boot();
  }
  document.addEventListener('htmx:afterSwap', function (e) { boot(e.target); });
  document.addEventListener('shown.bs.modal', function (e) { boot(e.target); });

  window.PatientSearch = { boot: boot };
})();
