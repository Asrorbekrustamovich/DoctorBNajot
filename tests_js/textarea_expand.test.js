/* Matn maydonlarini kattalashtirish — DOM testi.
 *
 * Nima tekshiriladi: ⤢ tugmasi paydo bo'lishi, katta oyna ochilishi,
 * matn ikki tomonga ko'chishi, «Yopish» o'zgarishni saqlamasligi,
 * Esc/Ctrl+Enter ishlashi, o'chirilgan maydon tahrirlanmasligi va
 * eng muhimi — tugma formani YUBORMASLIGI.
 */
const fs = require('fs');
const path = require('path');
const { parseHTML } = require('linkedom');

let pass = 0, fail = 0;
const ok = (n, c, e = '') => {
  if (c) { pass++; console.log('  OK  ' + n + (e ? '   ' + e : '')); }
  else { fail++; console.log('  YIQILDI  ' + n + (e ? '   ' + e : '')); }
};

const HTML = `<!doctype html><html><body>
<form id="examForm">
  <label for="ta1">Allergoanamnez</label>
  <textarea id="ta1" name="allergo">Boshlang'ich matn</textarea>

  <label for="ta2">Nevrologik holati</label>
  <textarea id="ta2" name="neuro" disabled>Faqat o'qish</textarea>

  <textarea id="ta3" name="skip" data-no-expand></textarea>
</form>
</body></html>`;

const { window, document } = parseHTML(HTML);
window.Event = window.Event || Event;

// linkedom'da tartib hisoblanmaydi — o'sish mantig'i uchun taqlid
Object.defineProperty(window.HTMLTextAreaElement.prototype, 'scrollHeight', {
  get() { return 20 + (this.value.split('\n').length * 20); },
  configurable: true,
});
Object.defineProperty(window.HTMLElement.prototype, 'offsetParent', {
  get() { return document.body; }, configurable: true,
});

const code = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'js', 'textarea_expand.js'), 'utf8');
new Function('window', 'document', code)(window, document);

const $ = s => document.querySelector(s);
const click = el => {
  const e = new window.Event('click', { bubbles: true });
  Object.defineProperty(e, 'target', { value: el, enumerable: true });
  el.dispatchEvent(e);
};
const key = (el, k, mods = {}) => {
  const e = new window.Event('keydown', { bubbles: true, cancelable: true });
  e.key = k; Object.assign(e, mods);
  Object.defineProperty(e, 'target', { value: el, enumerable: true });
  el.dispatchEvent(e);
  return e;
};

// --- 1) Ulanish
const ta1 = $('#ta1');
ok('maydon o\'ralgan', ta1.parentNode.classList.contains('ta-wrap'));
ok('⤢ tugmasi qo\'shildi', !!ta1.parentNode.querySelector('.ta-expand'));
ok('data-no-expand e\'tiborga olinadi',
   !$('#ta3').parentNode.classList.contains('ta-wrap'));

// Tugma formani yubormasligi kerak — bu eng xavfli xato bo'lardi
const btn = ta1.parentNode.querySelector('.ta-expand');
ok('tugma type="button"', btn.type === 'button', btn.type);

let submitted = false;
$('#examForm').addEventListener('submit', () => { submitted = true; });

// --- 2) Ochilish
click(btn);
const modal = document.querySelector('.ta-modal');
ok('katta oyna yaratildi', !!modal);
ok('oyna ochiq', modal.hidden === false);
ok('forma yuborilmadi', !submitted);
ok('sarlavha yorliqdan olindi',
   modal.querySelector('.ta-modal-title').textContent === 'Allergoanamnez',
   modal.querySelector('.ta-modal-title').textContent);
ok('matn ko\'chirildi',
   modal.querySelector('.ta-modal-input').value === "Boshlang'ich matn");
ok('body qulflandi', document.body.classList.contains('ta-modal-open'));

// --- 3) Tahrirlab «Tayyor»
const big = modal.querySelector('.ta-modal-input');
big.value = "Yangi uzun matn\nikkinchi qator";
let inputFired = false;
ta1.addEventListener('input', () => { inputFired = true; });
click(modal.querySelector('[data-ta-apply]'));
ok('matn asl maydonga qaytdi', ta1.value === "Yangi uzun matn\nikkinchi qator");
ok('oyna yopildi', modal.hidden === true);
ok('body qulfi ochildi', !document.body.classList.contains('ta-modal-open'));
ok('input hodisasi yuborildi (avtosaqlash uchun)', inputFired);

// --- 4) «Yopish» o'zgarishni SAQLAMAYDI
click(btn);
modal.querySelector('.ta-modal-input').value = 'BEKOR QILINSIN';
click(modal.querySelector('[data-ta-close]'));
ok('«Yopish» o\'zgarishni saqlamaydi',
   ta1.value === "Yangi uzun matn\nikkinchi qator", ta1.value);

// --- 5) Klaviatura
click(btn);
const esc = key(modal.querySelector('.ta-modal-input'), 'Escape');
ok('Esc oynani yopadi', modal.hidden === true && esc.defaultPrevented);

click(btn);
modal.querySelector('.ta-modal-input').value = 'Ctrl bilan';
key(modal.querySelector('.ta-modal-input'), 'Enter', { ctrlKey: true });
ok('Ctrl+Enter saqlab yopadi', modal.hidden === true && ta1.value === 'Ctrl bilan');

// --- 6) O'chirilgan maydon
const ta2 = $('#ta2');
click(ta2.parentNode.querySelector('.ta-expand'));
ok('o\'chirilgan maydon faqat o\'qish uchun ochiladi',
   modal.querySelector('.ta-modal-input').readOnly === true);
modal.querySelector('.ta-modal-input').value = 'HAMSHIRA YOZDI';
click(modal.querySelector('[data-ta-apply]'));
ok('o\'chirilgan maydon o\'zgarmaydi', ta2.value === "Faqat o'qish", ta2.value);

// --- 7) O'zi o'sishi
ta1.value = 'a\nb\nc\nd\ne';
ta1.dispatchEvent(new window.Event('input', { bubbles: true }));
ok('maydon balandligi o\'sdi', parseInt(ta1.style.height) > 60, ta1.style.height);

ta1.value = Array(50).fill('qator').join('\n');
ta1.dispatchEvent(new window.Event('input', { bubbles: true }));
ok('cheksiz o\'smaydi (420px chegara)',
   parseInt(ta1.style.height) === 420 && ta1.style.overflowY === 'auto',
   ta1.style.height + ' / ' + ta1.style.overflowY);

// --- 8) Ikki marta ulanmaydi
window.TextareaExpand.boot();
ok('qayta ulanmaydi (tugma bitta)',
   ta1.parentNode.querySelectorAll('.ta-expand').length === 1);

console.log(`\n=== ${pass} o'tdi, ${fail} yiqildi ===`);
process.exit(fail ? 1 : 0);
