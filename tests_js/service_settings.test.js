/* Superadmin sozlamalar sahifasidagi «kim bajaradi» modali.
 *
 * Bitta modal ikki vazifani bajaradi: XIZMAT tahriri va GURUH tahriri.
 * Ular maydon nomlari bilan farq qiladi (`allowed_role` / `default_role`).
 * Adashsa, saqlash jimgina noto'g'ri joyga yozadi — shuning uchun test.
 *
 * Sahifa Django tomonidan haqiqiy chizilgan (/tmp/settings.html).
 */
const fs = require('fs');
const { parseHTML } = require('linkedom');

let pass = 0, fail = 0;
const ok = (n, c, e = '') => {
  if (c) { pass++; console.log('  OK  ' + n + (e ? '   ' + e : '')); }
  else { fail++; console.log('  YIQILDI  ' + n + (e ? '   ' + e : '')); }
};

const html = fs.readFileSync('/tmp/settings.html', 'utf8');
const { window, document } = parseHTML(html);

let shown = false;
window.bootstrap = { Modal: class { constructor() {} show() { shown = true; } } };

// Sahifadagi inline skriptni bajaramiz
const code = [...document.querySelectorAll('script')]
  .filter(s => !s.src && /routingOptions/.test(s.textContent))
  .map(s => s.textContent).join('\n');
ok('sahifadagi skript topildi', code.length > 0);
new Function('window', 'document', 'bootstrap', 'JSON', code)(
  window, document, window.bootstrap, JSON);

const $ = id => document.getElementById(id);
const click = el => {
  const e = new window.Event('click', { bubbles: true });
  Object.defineProperty(e, 'target', { value: el, enumerable: true });
  el.dispatchEvent(e);
};

// --- variantlar sahifada bir marta
const opts = JSON.parse($('routingOptions').textContent);
ok('variantlar JSON bir marta yuborilgan',
   opts.roles.length > 0 && opts.staff.length > 0,
   `rollar=${opts.roles.length} xodimlar=${opts.staff.length} guruhlar=${opts.categories.length}`);
ok('sahifada takroriy <select> yo\'q (og\'irlik)',
   document.querySelectorAll('select').length <= 6,
   document.querySelectorAll('select').length + ' ta select');

// --- XIZMAT tahriri
const svcBtn = document.querySelector('[data-edit-routing]');
ok('xizmat tugmasi bor', !!svcBtn);
click(svcBtn);
ok('modal ochildi', shown);
ok('forma manzili o\'rnatildi', /\/routing\/$/.test($('routingForm').getAttribute('action')),
   $('routingForm').getAttribute('action'));
ok('sarlavha xizmat nomi', $('routingName').textContent === svcBtn.dataset.name,
   $('routingName').textContent);
ok('guruh maydoni ko\'rinadi', !$('routingCategoryBox').classList.contains('d-none'));
ok('guruh maydoni yoqilgan', $('routingCategory').disabled === false);
ok('maydon nomlari xizmatniki',
   $('routingRole').name === 'allowed_role' &&
   $('routingStaff').name === 'responsible_staff' &&
   $('routingRoom').name === 'room',
   `${$('routingRole').name} / ${$('routingStaff').name} / ${$('routingRoom').name}`);
ok('rollar to\'ldirildi', $('routingRole').options.length === opts.roles.length + 1,
   $('routingRole').options.length + ' variant');

// --- GURUH tahriri
const catBtn = document.querySelector('[data-edit-category]');
ok('guruh tugmasi bor', !!catBtn);
click(catBtn);
ok('forma manzili guruhniki', /\/defaults\/$/.test($('routingForm').getAttribute('action')),
   $('routingForm').getAttribute('action'));
ok('guruh maydoni yashirildi', $('routingCategoryBox').classList.contains('d-none'));
ok('guruh maydoni o\'chirilgan (yuborilmaydi)', $('routingCategory').disabled === true);
ok('maydon nomlari guruhniki',
   $('routingRole').name === 'default_role' &&
   $('routingStaff').name === 'default_staff' &&
   $('routingRoom').name === 'default_room',
   `${$('routingRole').name} / ${$('routingStaff').name} / ${$('routingRoom').name}`);

// --- xizmatga qaytish (holat qolib ketmasin)
click(svcBtn);
ok('xizmatga qaytganda guruh maydoni tiklandi',
   !$('routingCategoryBox').classList.contains('d-none') &&
   $('routingCategory').disabled === false &&
   $('routingCategory').options.length === opts.categories.length + 1);

console.log(`\n=== ${pass} o'tdi, ${fail} yiqildi ===`);
process.exit(fail ? 1 : 0);
