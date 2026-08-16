/* VIPISKANI BITTA A4 GA SIG'DIRISH.
 *
 * Talab: hujjat iloji boricha bitta varaqqa sig'sin, shrift matn ko'p
 * bo'lganda kichraysin — LEKIN o'qib bo'lmaydigan darajada emas.
 *
 * Ikki xato bo'lishi mumkin va ikkalasi ham jiddiy:
 *   · chegara qo'yilmasa — shrift nolgacha kichrayadi, hujjat o'qilmaydi;
 *   · kichraytirish bo'lmasa — qisqa vipiska ham ikki varaqqa cho'ziladi.
 *
 * linkedom haqiqiy tartiblashni (layout) hisoblamaydi, shuning uchun
 * balandlikni O'ZIMIZ modellashtiramiz: shrift qancha kichik bo'lsa,
 * matn shuncha kam joy egallaydi. Sinaladigan narsa — SIQISH MANTIG'I.
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
  path.join(__dirname, '..', 'templates', 'clinical', 'discharge_print.html'), 'utf8');

const blok = [...tpl.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1])
  .find(s => s.includes('sigdir'));
ok('sig\'dirish skripti topildi', !!blok);
if (!blok) process.exit(1);

ok('skriptda Django teglari yo\'q', !/\{%|\{\{/.test(blok));

/* --- Sinov muhiti: balandlik shriftga proportsional --- */
function ishlat(asilBalandlik) {
  const { window, document } = parseHTML(
    `<!doctype html><html><body>
       <span id="fit-info"></span><div id="sheet"></div>
     </body></html>`);

  let joriy = 12.5;
  // `style` ni butunlay almashtiramiz: linkedom uni har murojaatda
  // yangidan yasashi mumkin va bitta metodni almashtirish yo'qoladi.
  Object.defineProperty(document.documentElement, 'style', {
    configurable: true,
    value: { setProperty: (nom, qiymat) => {
      if (nom === '--fs') joriy = parseFloat(qiymat);
    } },
  });

  // 12.5px da `asilBalandlik`, kichraytirilganda mutanosib kamayadi
  document.getElementById('sheet').getBoundingClientRect =
    () => ({ height: asilBalandlik * (joriy / 12.5) });

  global.window = window;
  global.document = document;
  new Function(blok)();

  return { fs: joriy, info: document.getElementById('fit-info').textContent };
}

const MM = 96 / 25.4;
const VARAQ = 297 * MM - 24 * MM;      // ≈ 1031 px

// 1) Qisqa hujjat — kichraytirishning hojati yo'q
let r = ishlat(VARAQ * 0.6);
ok('qisqa vipiskada shrift kichraymaydi', r.fs === 12.5,
   'shrift: ' + r.fs);

// 2) Biroz uzun — sig'guncha kichrayadi
r = ishlat(VARAQ * 1.12);
ok('sal uzun hujjatda shrift kichrayadi', r.fs < 12.5, 'shrift: ' + r.fs);
ok('kichraygach bitta varaqqa sig\'adi', VARAQ * 1.12 * (r.fs / 12.5) <= VARAQ,
   'balandlik: ' + Math.round(VARAQ * 1.12 * (r.fs / 12.5)) + ' / ' + Math.round(VARAQ));

// 3) Juda uzun — CHEGARADAN pastga tushmaydi
r = ishlat(VARAQ * 3);
ok('juda uzun hujjatda ham shrift 10px dan kichraymaydi', r.fs >= 10,
   'shrift: ' + r.fs + ' (o\'qilmaydigan hujjatdan ko\'ra 2-varaq afzal)');
ok('foydalanuvchiga necha varaq bo\'lishi aytiladi', /varaq/.test(r.info),
   'xabar: "' + r.info + '"');

// 4) Chop etishdan oldin qayta hisoblash
ok('beforeprint ga ulangan', blok.includes('beforeprint'),
   'ekran va qog\'oz kengligi boshqa');

console.log(`\n  ${pass} o'tdi, ${fail} yiqildi`);
process.exit(fail ? 1 : 0);
