/* «Statsionar hisobotlari» modalidagi «Ko'chirish» tugmasi.
 *
 * HAQIQIY XATO: skript tugmalarni `querySelectorAll('.copy-blok')` bilan
 * bittalab bog'lardi, lekin u sahifada MODALLARDAN OLDIN turadi. Skript
 * ishga tushganda modal HTML'i hali o'qilmagan bo'ladi — ro'yxat bo'sh
 * qaytadi va tugmalar umuman ishlamaydi. Foydalanuvchi bosadi, hech
 * narsa bo'lmaydi.
 *
 * Test aynan shu tartibni takrorlaydi: avval skript, keyin modal.
 * Delegatsiya to'g'ri qo'yilgan bo'lsa — ishlaydi.
 */
const fs = require('fs');
const path = require('path');
const { parseHTML } = require('linkedom');

let pass = 0, fail = 0;
const ok = (n, c, e = '') => {
  if (c) { pass++; console.log('  OK  ' + n + (e ? '   ' + e : '')); }
  else { fail++; console.log('  YIQILDI  ' + n + (e ? '   ' + e : '')); }
};

// Shablondan skriptni ajratib olamiz — nusxa emas, ASL kod sinaladi.
const tpl = fs.readFileSync(
  path.join(__dirname, '..', 'templates', 'clinical', 'episode_detail.html'), 'utf8');

// Skript bloki bir necha bo'limdan iborat (MKB qidiruvi va h.k.) va
// ularda Django teglari bor. Bizga faqat hisobot bo'limi kerak —
// belgilangan sarlavhadan blok oxirigacha kesib olamiz.
const bloklar = [...tpl.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const toliq = bloklar.find(s => s.includes('copy-blok'));
ok('shablonda «Ko\'chirish» skripti topildi', !!toliq);
if (!toliq) { process.exit(1); }

const boshi = toliq.indexOf("document.addEventListener('click'");
const kod = boshi >= 0 ? toliq.slice(boshi) : '';
ok('delegatsiya ishlatilgan (document.addEventListener)', boshi >= 0,
   'tugmalarga bittalab bog\'lansa, keyin qo\'shilgan modal ishlamaydi');
if (!kod) { process.exit(1); }

// Django teglari JS emas — ular bo'lsa brauzer skriptni tashlab yuboradi.
ok('hisobot skriptida Django teglari yo\'q', !/\{%|\{\{/.test(kod));

const { window, document } = parseHTML(`<!doctype html><html><body>
  <textarea id="tpl-content"></textarea>
  <button type="button" id="tpl-clear">Tozalash</button>
  <button type="button" class="open-report" data-target="#rep1">Ko'rish</button>
</body></html>`);

global.window = window;
global.document = document;
global.setTimeout = (f) => f;          // animatsiyani kutmaymiz
window.bootstrap = { Modal: { getOrCreateInstance: () => ({ show() {} }) } };
global.bootstrap = window.bootstrap;

// --- 1) Skript ISHGA TUSHADI (modal hali yo'q — asl xato sharoiti)
new Function('bootstrap', kod)(window.bootstrap);

// --- 2) Modal KEYIN qo'shiladi
const modal = document.createElement('div');
modal.id = 'rep1';
modal.innerHTML = `
  <div class="rep-blok">
    <button type="button" class="copy-blok" data-title="Muolajalar va ukollar"
            data-date="11.08.2026">Ko'chirish</button>
    <div class="blok-text">11.08.2026 15:45 · Muolaja · ampitsilin</div>
  </div>
  <div class="rep-blok">
    <button type="button" class="copy-blok" data-title="Berilgan dorilar"
            data-date="11.08.2026">Ko'chirish</button>
    <div class="blok-text">ampitsilin x 1.00</div>
  </div>`;
document.body.appendChild(modal);

const maydon = document.getElementById('tpl-content');
const tugmalar = [...document.querySelectorAll('.copy-blok')];

// Hodisani TUGMANING O'ZIDAN yuboramiz va u hujjatga ko'tariladi —
// brauzerda ham aynan shunday bo'ladi.
const bos = (el) => el.dispatchEvent(new window.Event('click', { bubbles: true }));

// --- ASOSIY TEKSHIRUV
bos(tugmalar[0]);
ok('modal keyin qo\'shilsa ham «Ko\'chirish» ishlaydi',
   maydon.value.includes('ampitsilin'),
   'maydon: "' + maydon.value.slice(0, 60) + '"');

ok('sarlavha va sana bilan ko\'chiriladi',
   maydon.value.includes('Muolajalar va ukollar') && maydon.value.includes('11.08.2026'));

// --- IKKINCHI BO'LAK QO'SHILADI, USTIGA YOZILMAYDI
bos(tugmalar[1]);
ok('ikkinchi bo\'lak QO\'SHILADI (ustiga yozilmaydi)',
   maydon.value.includes('Muolajalar va ukollar')
   && maydon.value.includes('Berilgan dorilar'),
   'shifokor bir necha hisobotdan yig\'ishi kerak');

// --- TOZALASH
bos(document.getElementById('tpl-clear'));
ok('«Tozalash» maydonni bo\'shatadi', maydon.value === '');

// --- IKONKA BOSILGANDA HAM ISHLASHI (e.target = ichkaridagi <i>)
bos(tugmalar[0]);
const oldin = maydon.value;
const ikonka = document.createElement('i');
tugmalar[1].appendChild(ikonka);
bos(ikonka);
ok('tugma ichidagi ikonka bosilsa ham ishlaydi',
   maydon.value !== oldin && maydon.value.includes('Berilgan dorilar'),
   'closest() ishlatilmasa ikonkaga bosish e\'tiborsiz qolardi');

/* ================= SHABLONNI SAQLASH VA ISHLATISH =================
 *
 * HAQIQIY XATO 1: shablon oddiy `<form method="post">` bilan saqlanardi.
 * Saqlangach sahifa qayta yuklanar va yuqorida to'ldirilgan, hali
 * saqlanmagan ko'rik matnlari (shikoyatlar, anamnez) yo'qolib ketardi.
 *
 * HAQIQIY XATO 2: saqlangan shablonlar oddiy yorliq edi — bosib
 * bo'lmasdi, ya'ni saqlashning ma'nosi yo'q edi.
 */
const tplKodBoshi = toliq.indexOf("var quti = document.getElementById('tpl-box')");
ok('shablon skripti topildi', tplKodBoshi >= 0);

const tplKod = tplKodBoshi >= 0
  ? toliq.slice(toliq.lastIndexOf('(function () {', tplKodBoshi))
  : '';

ok('saqlash uchun forma ISHLATILMAYDI (sahifa yangilanmasin)',
   !/<form[^>]*episode_save_template/.test(tpl),
   'forma bo\'lsa POST sahifani qayta yuklab, yozilganlarni o\'chiradi');

// Yangi DOM — saqlash va tanlash uchun
const d2 = parseHTML(`<!doctype html><html><body>
  <input name="csrfmiddlewaretoken" value="TOKEN">
  <textarea id="shikoyat">Bosh og'rig'i</textarea>
  <div id="tpl-box" data-save-url="/save/"
       data-del-url="/del/00000000-0000-0000-0000-000000000000/">
    <input id="tpl-name">
    <textarea id="tpl-content"></textarea>
    <button type="button" id="tpl-save">Saqlash</button>
    <span id="tpl-msg"></span>
  </div>
  <div id="tpl-list">
    <span class="badge tpl-chip" data-id="T1">
      <button type="button" class="tpl-use">Tavsiyalar</button>
      <button type="button" class="tpl-del"></button>
      <textarea class="tpl-body">PARHEZ: sho'rvа, qaynatilgan ovqat</textarea>
    </span>
  </div>
</body></html>`);

global.window = d2.window;
global.document = d2.document;
global.FormData = d2.window.FormData || class { append() {} };
let soralganUrl = null;
global.fetch = (url, opt) => {
  soralganUrl = url;
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ ok: true, id: 'T2', name: 'Yangi', content: 'MATN' }),
  });
};
d2.window.fetch = global.fetch;

new Function('fetch', 'FormData', tplKod)(global.fetch, global.FormData);

const bos2 = (el) => el.dispatchEvent(new d2.window.Event('click', { bubbles: true }));
const fokus = (el) => el.dispatchEvent(new d2.window.Event('focusin', { bubbles: true }));

// --- SHABLONNI TANLASH: avval maydonni bosamiz, keyin shablonni
const shikoyat = d2.document.getElementById('shikoyat');
fokus(shikoyat);
bos2(d2.document.querySelector('.tpl-use'));

ok('shablon TANLANADI va oxirgi tegilgan maydonga qo\'yiladi',
   shikoyat.value.includes('PARHEZ'),
   'maydon: "' + shikoyat.value.slice(0, 50) + '"');
ok('maydondagi eski matn o\'chib ketmaydi',
   shikoyat.value.includes("Bosh og'rig'i"));

// --- SAQLASH: sahifa yangilanmaydi, fetch ishlatiladi
d2.document.getElementById('tpl-name').value = 'Yangi';
d2.document.getElementById('tpl-content').value = 'MATN';
bos2(d2.document.getElementById('tpl-save'));

ok('saqlash fetch orqali ketadi (sahifa yangilanmaydi)', soralganUrl === '/save/',
   'so\'ralgan URL: ' + soralganUrl);

console.log(`\n  ${pass} o'tdi, ${fail} yiqildi`);
process.exit(fail ? 1 : 0);
