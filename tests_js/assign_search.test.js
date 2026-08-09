/* «Bemorni joylashtirish» oynasidagi tezkor qidiruv.
 *
 * HAQIQIY XATO: shablon `patient.pinfl` va `patient.passport_number` ni
 * o'qigan, `Patient` modelida esa bu maydonlar YO'Q (`jshshir` va
 * `passport`). Natijada har bir variantda «JSHSHIR: -» turgan va
 * qidiruv hech qachon mos kelmagan. Bundan tashqari eski kod ro'yxatni
 * filtrlamas, faqat avto-tanlashga urinardi.
 *
 * Bu test qidiruvni haqiqiy DOM'da ishlatib ko'radi.
 */
const fs = require('fs');
const path = require('path');
const { parseHTML } = require('linkedom');

let pass = 0, fail = 0;
const ok = (n, c, e = '') => {
  if (c) { pass++; console.log('  OK  ' + n + (e ? '   ' + e : '')); }
  else { fail++; console.log('  YIQILDI  ' + n + (e ? '   ' + e : '')); }
};

// Qidiruv mantig'i umumiy faylda — uni to'g'ridan-to'g'ri o'qiymiz.
const code = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'js', 'patient_search.js'), 'utf8');
const T = f => fs.readFileSync(
  path.join(__dirname, '..', 'templates', 'clinical', f), 'utf8');
// Izohlarni olib tashlaymiz: ular xatoni TUSHUNTIRADI, ya'ni eski
// maydon nomlari matn sifatida uchraydi va tekshiruvni chalg'itadi.
const noComments = s => s.replace(/\{%\s*comment\s*%\}[\s\S]*?\{%\s*endcomment\s*%\}/g, '')
                         .replace(/\/\*[\s\S]*?\*\//g, '');
const tpl = noComments(T('_assign_bed_form.html'));
const surgeryTpl = noComments(T('surgery_dashboard.html'));

const HTML = `<!doctype html><html><body>
<form id="assignForm">
  <input type="text" id="assign_quick_search" data-patient-search="assign_visit_select" data-hint="assign_search_hint">
  <small id="assign_search_hint"></small>
  <select id="assign_visit_select" name="visit_id">
    <option value="">-- Tanlang --</option>
    <option value="V1" data-search="valiyev ali 51012037250024  aa1234567 p-000001">Valiyev Ali · JSHSHIR 51012037250024</option>
    <option value="V2" data-search="karimova aziza  i-ab 123456  p-000002">Karimova Aziza · Metrika I-AB 123456</option>
    <option value="V3" data-search="valiyev bobur 99999999999999  p-000003">Valiyev Bobur · JSHSHIR 99999999999999</option>
  </select>
</form>
</body></html>`;

const { window, document } = parseHTML(HTML);
window.jQuery = undefined;
new Function('window', 'document', code)(window, document);

const box = document.getElementById('assign_quick_search');
const sel = document.getElementById('assign_visit_select');
const hint = document.getElementById('assign_search_hint');
const type = v => {
  box.value = v;
  const e = new window.Event('input', { bubbles: true });
  Object.defineProperty(e, 'target', { value: box, enumerable: true });
  box.dispatchEvent(e);
};
const shown = () => [...sel.options].filter(o => o.value).map(o => o.value);
// `sel.value` ba'zi muhitlarda ishonchsiz — tanlovni option'ning
// o'zidan o'qiymiz.
const picked = () => ([...sel.options].find(o => o.selected && o.value) || {}).value || '';

// --- boshlang'ich holat
ok('boshda hamma variant bor', shown().length === 3, shown().join(','));

// --- JSHSHIR bo'yicha
type('51012037250024');
ok('JSHSHIR bo\'yicha filtrlandi', shown().join(',') === 'V1', shown().join(','));
ok('bitta qolganda o\'zi tanlandi', picked() === 'V1', picked());
ok('xabar to\'g\'ri', /tanlandi/.test(hint.textContent), hint.textContent);

// --- JSHSHIR qismi bo'yicha
type('5101203');
ok('to\'liqmas JSHSHIR ham topadi', shown().join(',') === 'V1');

// --- metrika, yozilishi farq qilsa ham
type('I-AB 123456');
ok('metrika bo\'yicha topadi', shown().join(',') === 'V2', shown().join(','));
type('iab123456');
ok('metrika tiresiz ham topadi', shown().join(',') === 'V2', shown().join(','));

// --- ism-familiya bo'yicha
type('valiyev');
ok('familiya bo\'yicha ikkitasi', shown().join(',') === 'V1,V3', shown().join(','));
// Ilgari tanlangan bemor yangi ro'yxatda bo'lmasa — tanlov bekor
// bo'lishi kerak, aks holda ekranda «Valiyev» ko'rinib turib,
// yashirincha boshqa bemor yuboriladi.
ok('mos kelmaydigan eski tanlov bekor bo\'ladi', picked() === '', picked());
ok('nechta topilgani yoziladi', /2 ta/.test(hint.textContent), hint.textContent);

type('bobur');
ok('ism bo\'yicha bittasi', shown().join(',') === 'V3' && picked() === 'V3', picked());

// Eski tanlov yangi ro'yxatda BOR bo'lsa — saqlanishi kerak
type('valiyev ali');
ok('mos keladigan eski tanlov saqlanadi', picked() === 'V1', picked());
type('valiyev');
ok('ikkitasidan biri tanlangan qoladi', picked() === 'V1', picked());

// --- pasport va karta raqami
type('AA1234567');
ok('pasport bo\'yicha topadi', shown().join(',') === 'V1', shown().join(','));
type('P-000002');
ok('karta raqami bo\'yicha topadi', shown().join(',') === 'V2', shown().join(','));

// --- topilmasa
type('yoq-bunday-odam');
ok('topilmasa ro\'yxat bo\'sh', shown().length === 0);
ok('topilmadi deb aytiladi', /topilmadi/i.test(hint.textContent), hint.textContent);

// --- tozalanganda hammasi qaytadi
type('');
ok('tozalanganda hammasi qaytadi', shown().length === 3, shown().join(','));

// --- Enter formani yubormaydi
let submitted = false;
document.getElementById('assignForm').addEventListener('submit', () => { submitted = true; });
const ke = new window.Event('keydown', { bubbles: true, cancelable: true });
ke.key = 'Enter';
Object.defineProperty(ke, 'target', { value: box, enumerable: true });
box.dispatchEvent(ke);
ok('Enter formani yubormaydi', ke.defaultPrevented && !submitted);

// --- shablonda eski maydon nomlari qolmaganini tekshiramiz
ok('`pinfl` ishlatilmaydi', !/patient\.pinfl/.test(tpl));
ok('`passport_number` ishlatilmaydi', !/passport_number/.test(tpl));
ok('`jshshir` ishlatiladi', /patient\.jshshir/.test(tpl));
ok('`birth_certificate` (metrika) ishlatiladi', /birth_certificate/.test(tpl));

// --- jarrohlik oynasi ham xuddi shu xatoga ega edi
ok('jarrohlik: `pinfl` ishlatilmaydi', !/\.pinfl/.test(surgeryTpl));
ok('jarrohlik: `passport_number` ishlatilmaydi', !/passport_number/.test(surgeryTpl));
ok('jarrohlik: umumiy qidiruvga ulangan',
   /data-patient-search="surgery_patient_select"/.test(surgeryTpl));
ok('jarrohlik: buzuq `&& .hasClass` yo\'q', !/&&\s*\.hasClass/.test(surgeryTpl));

console.log(`\n=== ${pass} o'tdi, ${fail} yiqildi ===`);
process.exit(fail ? 1 : 0);
