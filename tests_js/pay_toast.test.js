/* TO'LOV BILDIRISHNOMASI.
 *
 * Registrator dasturning boshqa bo'limida turgan bo'lsa (navbat,
 * klinika), shifokor tekshiruv tayinlaganini bilmaydi va bemor kassada
 * kutib qoladi. Shuning uchun o'ng yuqorida qisqa xabar chiqadi.
 *
 * Talablar:
 *   · 5 soniya turadi, keyin o'zi yo'qoladi;
 *   · «×» bosilsa DARROV yo'qoladi (5 soniyani kutmaydi);
 *   · sahifa ochilgan zahoti eski tayinlovlar uchun bezovta qilmaydi —
 *     faqat YANGISI kelganda chiqadi;
 *   · to'lov sahifasining o'zida umuman chiqmaydi.
 */
const fs = require('fs');
const path = require('path');
const { parseHTML } = require('linkedom');

let pass = 0, fail = 0;
const ok = (n, c, e = '') => {
  if (c) { pass++; console.log('  OK  ' + n + (e ? '   ' + e : '')); }
  else { fail++; console.log('  YIQILDI  ' + n + (e ? '   ' + e : '')); }
};

const tpl = fs.readFileSync(
  path.join(__dirname, '..', 'templates', 'base.html'), 'utf8');

const kod = [...tpl.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1])
  .find(s => s.includes('pay-toasts'));
ok('bildirishnoma skripti topildi', !!kod);
if (!kod) process.exit(1);

ok('skriptda Django teglari yo\'q', !/\{%|\{\{/.test(kod));
ok('5 soniya belgilangan', /KECHIKISH\s*=\s*5000/.test(kod));

/* ---------- Sinov muhiti ---------- */
function muhit(yol, saqlangan) {
  const { window, document } = parseHTML(`<!doctype html><html><body>
    <div id="pay-toasts" data-url="/pay.json" data-target="/billing/registrator/"></div>
  </body></html>`);

  // Brauzer xotirasi — sahifalar orasida holat saqlanishini sinash uchun
  const ombor = { [saqlangan !== undefined ? 'pay-oxirgi' : '_']: saqlangan };
  window.localStorage = {
    getItem: (k) => (k in ombor && ombor[k] !== undefined ? ombor[k] : null),
    setItem: (k, v) => { ombor[k] = v; },
  };

  const soatlar = [];
  let davriy = null;                     // setInterval'ga berilgan funksiya

  global.window = window;
  global.document = document;
  window.location = { pathname: yol };
  global.setTimeout = (f, ms) => { soatlar.push({ f, ms, bekor: false }); return soatlar.length; };
  global.clearTimeout = (id) => { if (soatlar[id - 1]) soatlar[id - 1].bekor = true; };
  global.setInterval = (f) => { davriy = f; return 0; };

  let javob = { count: 0, patients: 0, signature: 'A' };
  const sorovlar = [];
  global.fetch = (u) => {
    sorovlar.push(u);
    return Promise.resolve({ ok: true, json: () => Promise.resolve(javob) });
  };

  return {
    window, document, soatlar, sorovlar,
    javobBer(j) { javob = j; },
    ishlat() { new Function(kod)(); },
    // Vaqt o'tishini taqlid qilamiz — 20 soniyadan keyingi so'rov
    kutish() { if (davriy) davriy(); },
    xabarlar() { return document.querySelectorAll('#pay-toasts .alert'); },
    soni() { return this.xabarlar().length; },
    // 5 soniyalik soatni ishga tushiramiz
    vaqtOtdi() {
      soatlar.filter(s => !s.bekor && s.ms === 5000).forEach(s => s.f());
    },
  };
}

const kut = () => new Promise(r => setImmediate(r));

(async function () {
  /* 1) TO'LOV SAHIFASINING O'ZIDA chiqmaydi */
  let m = muhit('/billing/registrator/');
  m.ishlat();
  await kut();
  ok('to\'lov sahifasining o\'zida so\'rov yubormaydi', m.sorovlar.length === 0,
     'u yerda ro\'yxat allaqachon ko\'rinib turibdi');

  /* 2) BIRINCHI so'rovda bezovta qilmaydi */
  m = muhit('/registration/queue/');
  m.javobBer({ count: 3, patients: 2, signature: 'A' });
  m.ishlat();
  await kut();
  ok('sahifa ochilganda eski tayinlovlar uchun xabar chiqmaydi',
     m.soni() === 0, 'xabarlar: ' + m.soni());

  /* 3) YANGI tayinlov kelganda chiqadi */
  m = muhit('/registration/queue/');
  m.javobBer({ count: 3, patients: 2, signature: 'A' });
  m.ishlat();
  await kut();

  m.javobBer({ count: 4, patients: 3, signature: 'B' });   // yangi tayinlov
  m.kutish();
  await kut();

  ok('yangi tayinlov kelganda xabar chiqadi', m.soni() === 1,
     'xabarlar: ' + m.soni());
  const matn = m.xabarlar()[0] ? m.xabarlar()[0].textContent : '';
  ok('xabarda tayinlovlar soni ko\'rsatiladi', matn.includes('4'),
     'matn: "' + matn.replace(/\s+/g, ' ').trim().slice(0, 70) + '"');
  ok('xabarda bemorlar soni ko\'rsatiladi', matn.includes('3 bemor'));

  /* 4) HOLAT O'ZGARMASA takrorlanmaydi */
  m.kutish();                       // o'sha «B» javobi bilan yana so'rov
  await kut();
  ok('holat o\'zgarmasa xabar takrorlanmaydi', m.soni() === 1,
     'aks holda har 20 soniyada bir xil xabar chiqib turardi');

  /* 5) 5 SONIYADAN keyin o'zi yo'qoladi */
  m.vaqtOtdi();
  ok('5 soniyadan keyin xabar o\'zi yo\'qoladi', m.soni() === 0);

  /* 5b) SAHIFA ALMASHGANDA HOLAT YO'QOLMAYDI.
   *
   * HAQIQIY XATO: holat faqat xotirada edi va har sahifa ochilganda
   * nolga tushardi. Birinchi so'rov esa ataylab jim, shuning uchun
   * sahifadan sahifaga o'tib yurgan registratorga bildirishnoma
   * UMUMAN chiqmasdi — har safar «birinchi so'rov» bo'lib qolardi. */
  m = muhit('/registration/queue/', 'ESKI-BELGI');
  m.javobBer({ count: 2, patients: 1, signature: 'YANGI-BELGI' });
  m.ishlat();
  await kut();
  ok('sahifa yangi ochilsa ham yangi tayinlov darrov sezilади',
     m.soni() === 1,
     'oldingi holat brauzerda saqlanadi');

  /* 5c) Saqlangan holat bilan bir xil bo'lsa — jim */
  m = muhit('/registration/queue/', 'BIR-XIL');
  m.javobBer({ count: 2, patients: 1, signature: 'BIR-XIL' });
  m.ishlat();
  await kut();
  ok('holat o\'zgarmagan bo\'lsa sahifa ochilganda bezovta qilmaydi',
     m.soni() === 0);

  ok('tekshirish oralig\'i 8 soniya', /ORALIQ\s*=\s*8000/.test(kod),
     '20 soniya juda uzoq — bemor kassada kutib qoladi');

  /* 6) «×» bosilganda DARROV yo'qoladi */
  m = muhit('/registration/queue/');
  m.javobBer({ count: 1, patients: 1, signature: 'A' });
  m.ishlat();
  await kut();
  m.javobBer({ count: 2, patients: 1, signature: 'B' });
  m.kutish();
  await kut();
  ok('sinov uchun xabar chiqdi', m.soni() === 1);

  const xabar = m.xabarlar()[0];
  const yopish = xabar.querySelector('.btn-close');
  ok('xabarda «×» tugmasi bor', !!yopish);

  yopish.dispatchEvent(new m.window.Event('click', { bubbles: true }));
  ok('«×» bosilganda DARROV yo\'qoladi', m.soni() === 0,
     '5 soniyani kutmasligi kerak');

  // Soat bekor qilinmasa, element o'chgandan keyin ham ishlab turardi
  ok('«×» 5 soniyalik soatni ham bekor qiladi',
     m.soatlar.some(s => s.ms === 5000 && s.bekor));

  console.log(`\n  ${pass} o'tdi, ${fail} yiqildi`);
  process.exit(fail ? 1 : 0);
})();
