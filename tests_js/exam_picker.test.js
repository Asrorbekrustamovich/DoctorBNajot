/* exam_picker.js ni haqiqiy DOM'da sinash.
 *
 * NEGA KERAK: Django testlari faqat serverni tekshiradi. Tugmalar
 * ishlaydimi, hisob to'g'ri chiqadimi, modal formadan chiqarilganmi —
 * bularni faqat brauzer DOM'ida ko'rish mumkin. linkedom shu vazifani
 * bajaradi (haqiqiy brauzersiz).
 */
const fs = require('fs');
const path = require('path');
const { parseHTML } = require('linkedom');

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => {
  if (cond) { pass++; console.log('  OK  ' + name + (extra ? '   ' + extra : '')); }
  else { fail++; console.log('  YIQILDI  ' + name + (extra ? '   ' + extra : '')); }
};

// Qabul oynasiga o'xshash tuzilma: modal > form > piker > guruh modallari
const HTML = `<!doctype html><html><body>
<div class="modal" id="consultationModal">
  <form id="consultationForm">
    <input type="hidden" name="csrfmiddlewaretoken" value="TOK">
    <div class="exam-picker" id="examPicker">
      <button class="exam-group-btn" data-exam-open="examModal-G1"><span class="badge d-none" data-group-counter="G1">0</span></button>
      <span id="examPickedCount">0</span><span id="examPickedSum">0</span>
      <button id="examClearAll" disabled></button>
      <button id="examAssignBtn" disabled data-url="/assign/"></button>
      <div id="examPickerMsg"></div>
    </div>
    <div class="modal" id="examModal-G1">
      <span class="badge d-none" data-group-picked-badge="G1">0</span>
      <button data-exam-back>Orqaga</button>
      <input type="text" data-exam-search="G1">
      <div class="exam-row" data-exam-name="umumiy qon tahlili">
        <label class="exam-item"><input class="exam-check" type="checkbox" value="S1" data-group="G1" data-price="40000"></label>
      </div>
      <div class="exam-row" data-exam-name="uzi qorin">
        <label class="exam-item"><input class="exam-check" type="checkbox" value="S2" data-group="G1" data-price="90000"></label>
      </div>
      <div class="exam-row" data-exam-name="tayinlangan">
        <label class="exam-item is-assigned"><input class="exam-check" type="checkbox" value="S3" data-group="G1" data-price="10000" checked disabled></label>
      </div>
      <button data-exam-clear="G1"></button>
      <span data-group-picked="G1">0</span><span data-group-sum="G1">0</span>
    </div>
  </form>
</div>
</body></html>`;

const { window, document } = parseHTML(HTML);

// linkedom'da yo'q, lekin skript ishlatadigan narsalar
window.Intl = Intl;
window.CustomEvent = window.CustomEvent || class extends window.Event {
  constructor(t, o) { super(t); this.detail = (o || {}).detail; }
};
// Bootstrap modal taqlidi: ochilgan/yopilganini kuzatamiz va
// `hidden.bs.modal` hodisasini haqiqiy Bootstrap kabi yuboramiz.
const modalLog = [];
window.bootstrap = {
  Modal: {
    getOrCreateInstance(el) {
      return {
        show() { el.classList.add('show'); modalLog.push('show:' + el.id); },
        hide() {
          el.classList.remove('show');
          modalLog.push('hide:' + el.id);
          const ev = new window.Event('hidden.bs.modal', { bubbles: true });
          Object.defineProperty(ev, 'target', { value: el, enumerable: true });
          el.dispatchEvent(ev);
        },
      };
    },
  },
};

let posted = null;
window.fetch = function (url, opts) {
  posted = { url, body: opts.body };
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ status: 'ok', message: '2 ta xizmat tayinlandi.' }),
  });
};
window.FormData = class {
  constructor() { this._d = []; }
  append(k, v) { this._d.push([k, v]); }
  getAll(k) { return this._d.filter(x => x[0] === k).map(x => x[1]); }
};

// Skriptni shu window kontekstida bajaramiz
const code = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'exam_picker.js'), 'utf8');
const ctx = { window, document, Intl, console: { log() {}, warn() {} } };
new Function('window', 'document', 'Intl', 'console', code)(
  window, document, Intl, ctx.console);

// linkedom `checked` IDL xossasini qo'llab-quvvatlamaydi: atribut bor,
// lekin `el.checked` — undefined. Brauzerda bunday emas. Shuning uchun
// boshlang'ich holatni qo'lda tenglashtiramiz, aks holda test kodni emas,
// linkedom kamchiligini o'lchagan bo'lardi.
[...document.querySelectorAll('.exam-check')].forEach(el => {
  el.checked = el.hasAttribute('checked');
});

const $ = id => document.getElementById(id);
const checks = () => [...document.querySelectorAll('.exam-check')];
const checks2 = () => [...document.querySelectorAll('.exam-check')];
const click = el => {
  const e = new window.Event('click', { bubbles: true });
  Object.defineProperty(e, 'target', { value: el, enumerable: true });
  el.dispatchEvent(e);
};
const fire = (el, type) => {
  const e = new window.Event(type, { bubbles: true });
  Object.defineProperty(e, 'target', { value: el, enumerable: true });
  el.dispatchEvent(e);
};

// --- 1) Modal formadan chiqarilganmi?
// Bu ENG MUHIM tekshiruv: modal <form> ichida qolsa, qidiruvda Enter
// bosilganda qabul yakunlanib ketadi; modal ichida modal esa Bootstrap'ning
// fonini buzadi.
const gm = $('examModal-G1');
ok('guruh modali <body> ga ko\'chirildi', gm.parentNode === document.body,
   'ota-ona: ' + gm.parentNode.tagName + (gm.parentNode.id ? '#' + gm.parentNode.id : ''));
ok('guruh modali forma ichida emas', !$('consultationForm').contains(gm));

// --- 2) Boshlang'ich holat
ok('boshda 0 ta tanlangan', $('examPickedCount').textContent === '0');
ok('tayinlash tugmasi o\'chirilgan', $('examAssignBtn').disabled);
ok('bekor qilish tugmasi o\'chirilgan', $('examClearAll').disabled);
ok('tayinlangan (disabled) hisobga olinmaydi', $('examPickedSum').textContent === '0');

// --- 3) Belgilash va hisob
const c1 = checks()[0], c2 = checks()[1];
c1.checked = true; fire(c1, 'change');
ok('1 ta tanlandi', $('examPickedCount').textContent === '1');
ok('summa 40 000', $('examPickedSum').textContent.replace(/\D/g, '') === '40000',
   $('examPickedSum').textContent);
ok('tayinlash tugmasi yoqildi', !$('examAssignBtn').disabled);

c2.checked = true; fire(c2, 'change');
ok('2 ta tanlandi', $('examPickedCount').textContent === '2');
ok('summa 130 000', $('examPickedSum').textContent.replace(/\D/g, '') === '130000',
   $('examPickedSum').textContent);

// --- 4) Guruh hisoblagichlari
ok('guruh sanog\'i 2', document.querySelector('[data-group-picked="G1"]').textContent === '2');
const badge = document.querySelector('[data-group-counter="G1"]');
ok('tugmadagi nishon ko\'rindi', !badge.classList.contains('d-none') && badge.textContent === '2');

// --- 5) Qidiruv
const box = document.querySelector('[data-exam-search="G1"]');
box.value = 'uzi'; fire(box, 'input');
const rows = [...document.querySelectorAll('.exam-row')];
ok('qidiruv mos kelmaganini yashiradi',
   rows[0].classList.contains('d-none') && !rows[1].classList.contains('d-none'));
box.value = ''; fire(box, 'input');
ok('qidiruv tozalanganda hammasi qaytadi',
   rows.every(r => !r.classList.contains('d-none')));

// --- 6) Enter formani yubormaydi
let submitted = false;
$('consultationForm').addEventListener('submit', () => { submitted = true; });
const ke = new window.Event('keydown', { bubbles: true, cancelable: true });
ke.key = 'Enter';
Object.defineProperty(ke, 'target', { value: box, enumerable: true });
box.dispatchEvent(ke);
ok('qidiruvda Enter bloklandi', ke.defaultPrevented && !submitted);

// --- 7) Guruh bo'yicha tanlovni bekor qilish
const clearBtn = document.querySelector('[data-exam-clear="G1"]');
const ce = new window.Event('click', { bubbles: true });
Object.defineProperty(ce, 'target', { value: clearBtn, enumerable: true });
clearBtn.dispatchEvent(ce);
ok('guruh tanlovi bekor qilindi', $('examPickedCount').textContent === '0');
ok('o\'chirilgan (tayinlangan) katak tegilmadi', checks()[2].checked === true);

// --- 7b) TANLANGANLIK KO'RINADIMI
// Foydalanuvchi «belgilangan yoki belgilanmaganini bilib bo'lmayapti»
// dedi: katakchaning o'zi kichkina va Bootstrap'ning `.form-check`
// manfiy chekkasi uni chegara ustiga surib yuborardi. Endi butun qator
// `is-picked` klassi bilan ajralib turadi.
const item1 = c1.closest('.exam-item');
ok('boshda qator belgilanmagan', !item1.classList.contains('is-picked'));
c1.checked = true; fire(c1, 'change');
ok('tanlanganda qator ajralib turadi', item1.classList.contains('is-picked'));
c1.checked = false; fire(c1, 'change');
ok('yechilganda ajratish olib tashlanadi', !item1.classList.contains('is-picked'));
ok('tayinlangan qatorga is-picked qo\'yilmaydi',
   !checks2()[2].closest('.exam-item').classList.contains('is-picked'));

// Sarlavhadagi nishon
c1.checked = true; fire(c1, 'change');
const hBadge = document.querySelector('[data-group-picked-badge="G1"]');
ok('modal sarlavhasida tanlanganlar soni', hBadge.textContent === '1' &&
   !hBadge.classList.contains('d-none'));
c1.checked = false; fire(c1, 'change');
ok('nol bo\'lganda nishon yashirinadi', hBadge.classList.contains('d-none'));

// --- 7c) MODALLAR ZANJIRI: qabul → guruh → qabul
modalLog.length = 0;
const openBtn = document.querySelector('[data-exam-open]');
click(openBtn);
ok('qabul oynasi yashirildi, keyin guruh ochildi',
   JSON.stringify(modalLog) === JSON.stringify(['hide:consultationModal', 'show:examModal-G1']),
   JSON.stringify(modalLog));
ok('ikkita modal bir vaqtda ochiq emas',
   document.querySelectorAll('.modal.show').length === 1);

modalLog.length = 0;
click(document.querySelector('[data-exam-back]'));
ok('«Orqaga» guruhni yopib, qabulni qaytardi',
   JSON.stringify(modalLog) === JSON.stringify(['hide:examModal-G1', 'show:consultationModal']),
   JSON.stringify(modalLog));
ok('qabul oynasi yana ochiq',
   document.getElementById('consultationModal').classList.contains('show'));

// --- 8) Tayinlash so'rovi
c1.checked = true; fire(c1, 'change');
c2.checked = true; fire(c2, 'change');
$('examAssignBtn').click();

setTimeout(() => {
  ok('POST yuborildi', posted && posted.url === '/assign/');
  ok('faqat tanlanganlar yuborildi',
     posted && JSON.stringify(posted.body.getAll('services')) === JSON.stringify(['S1', 'S2']),
     posted ? JSON.stringify(posted.body.getAll('services')) : '');
  ok('CSRF qo\'shildi', posted && posted.body.getAll('csrfmiddlewaretoken')[0] === 'TOK');
  ok('tayinlangач qayta tanlab bo\'lmaydi', c1.disabled && c2.disabled);
  ok('muvaffaqiyat xabari chiqdi', /tayinlandi/.test($('examPickerMsg').textContent),
     $('examPickerMsg').textContent.trim());
  ok('hisob nolga qaytdi', $('examPickedCount').textContent === '0');

  console.log(`\n=== ${pass} o'tdi, ${fail} yiqildi ===`);
  process.exit(fail ? 1 : 0);
}, 50);
