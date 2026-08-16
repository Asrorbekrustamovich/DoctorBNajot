/**
 * «Statsionarga yo'naltirish» tugmasi: sahifa yangilanmasligi, ikki
 * marta bosilmasligi va bekor qilingandan keyin qaytadan ochilishi.
 *
 * Bu yerda aynan brauzerdagi xatti-harakat tekshiriladi: Django testi
 * serverni tekshiradi, lekin tugma kulrang bo'lyaptimi-yo'qmi — buni
 * faqat DOM ko'rsatadi.
 */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { parseHTML } = require("linkedom");

const TEMPLATE = path.join(
    __dirname, "..", "templates", "clinical", "modals", "consultation_modal.html");

/** Shablondan faqat kerakli JS bo'lagini ajratib olamiz. */
function referScript() {
    const src = fs.readFileSync(TEMPLATE, "utf8");
    const boshi = src.indexOf("STATSIONARGA YO'NALTIRISH — sahifani yangilamasdan");
    assert.ok(boshi > -1, "yo'naltirish skripti topilmadi");
    // IIFE izohdan KEYIN keladi — orqaga qarasak boshqa blok topiladi
    const ochilish = src.indexOf("(function () {", boshi);
    const yopilish = src.indexOf("})();", boshi);
    return src.slice(ochilish, yopilish + 5);
}

function muhit({ sent = false } = {}) {
    const { document, window } = parseHTML(`<html><body>
        <div id="referBox"
             data-url="/yubor/"
             data-sent="${sent ? 1 : 0}"
             data-cancel-url="${sent ? "/bekor/" : ""}">
          <button type="button" id="referBtn"
                  class="btn ${sent ? "btn-secondary" : "btn-outline-primary"}"
                  ${sent ? "disabled" : ""}>Statsionarga yo'naltirish</button>
          <button type="button" id="referCancelBtn"
                  class="btn ${sent ? "" : "d-none"}">Bekor qilish</button>
          <span id="referMsg"></span>
        </div></body></html>`);

    const soravlar = [];
    const javoblar = [];

    global.document = document;
    global.window = window;
    global.alert = () => {};
    global._csrf = () => "TOKEN";
    global.confirm = () => true;
    global.URLSearchParams = window.URLSearchParams || URLSearchParams;
    global.fetch = (url) => {
        soravlar.push(url);
        const j = javoblar.shift() || { ok: true };
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(j),
        });
    };

    eval(referScript());
    return { document, soravlar, javoblar };
}

const kut = () => new Promise((r) => setTimeout(r, 0));

test("bosilganda sahifa yangilanmaydi, so'rov yuboriladi", async () => {
    const m = muhit();
    m.javoblar.push({ ok: true, yangi: true, cancel_url: "/bekor/",
                      message: "yuborildi" });
    m.document.getElementById("referBtn").dispatchEvent(
        new m.document.defaultView.Event("click", { bubbles: true }));
    await kut();
    assert.deepStrictEqual(m.soravlar, ["/yubor/"]);
});

test("yuborilgach tugma kulrang va bosilmaydigan bo'ladi", async () => {
    const m = muhit();
    m.javoblar.push({ ok: true, yangi: true, cancel_url: "/bekor/", message: "" });
    const btn = m.document.getElementById("referBtn");
    btn.dispatchEvent(new m.document.defaultView.Event("click", { bubbles: true }));
    await kut();

    assert.ok(btn.disabled, "tugma bosilmaydigan bo'lishi kerak");
    assert.ok(btn.className.includes("btn-secondary"), "kulrang bo'lishi kerak");
    assert.match(btn.innerHTML, /Statsionarga yuborildi/);
});

test("ikkinchi marta bosilsa qayta yuborilmaydi", async () => {
    const m = muhit();
    m.javoblar.push({ ok: true, yangi: true, cancel_url: "/bekor/", message: "" });
    const btn = m.document.getElementById("referBtn");
    const bosish = () => btn.dispatchEvent(
        new m.document.defaultView.Event("click", { bubbles: true }));

    bosish();
    await kut();
    bosish();
    await kut();

    assert.strictEqual(m.soravlar.length, 1, "faqat bitta so'rov ketishi kerak");
});

test("yuborilgach bekor qilish tugmasi chiqadi", async () => {
    const m = muhit();
    m.javoblar.push({ ok: true, yangi: true, cancel_url: "/bekor/", message: "" });
    m.document.getElementById("referBtn").dispatchEvent(
        new m.document.defaultView.Event("click", { bubbles: true }));
    await kut();
    assert.ok(!m.document.getElementById("referCancelBtn")
                 .className.includes("d-none"));
});

test("bekor qilingach tugma yana ochiladi", async () => {
    const m = muhit({ sent: true });
    m.javoblar.push({ ok: true, message: "bekor qilindi" });

    m.document.getElementById("referCancelBtn").dispatchEvent(
        new m.document.defaultView.Event("click", { bubbles: true }));
    await kut();

    const btn = m.document.getElementById("referBtn");
    assert.ok(!btn.disabled, "tugma yana bosiladigan bo'lishi kerak");
    assert.ok(btn.className.includes("btn-outline-primary"));
    assert.match(btn.innerHTML, /naltirish/);
    assert.ok(m.document.getElementById("referCancelBtn")
                .className.includes("d-none"));
    assert.deepStrictEqual(m.soravlar, ["/bekor/"]);
});
