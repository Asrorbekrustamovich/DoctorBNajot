# Interfeys testlari

Django testlari serverni tekshiradi: model, ruxsat, so'rov-javob. Ular
tugmalar bosilganda nima bo'lishini KO'RMAYDI. Bu yerdagi testlar shu
bo'shliqni to'ldiradi — skriptlar haqiqiy DOM'da (`linkedom`) ishlatiladi.

```bash
npm install
npm test
```

## Nimalar tekshiriladi

`exam_picker.test.js` — tekshiruv tayinlash pikeri (24 ta):
tanlash, jami summa, guruh hisoblagichlari, qidiruv, «Tanlovni bekor
qilish», POST tarkibi, CSRF, tayinlangandan keyin qayta tanlab
bo'lmasligi. Eng muhimi: guruh modallari `<body>` ga ko'chirilganmi.

`service_settings.test.js` — superadmin «kim bajaradi» modali (17 ta).
Sahifa Django tomonidan haqiqiy chiziladi (`/tmp/settings.html`), keyin
inline skript o'sha HTML ustida ishlatiladi.

## Nima uchun modal `<body>` ga ko'chiriladi

Guruh modallari shablonda qabul oynasining ichida chiziladi. U yerda
qolsa ikkita buzilish bo'ladi:

1. **Modal ichida modal** — Bootstrap 5 ichkarisini yopganda `<body>`
   dan `modal-open` ni olib tashlaydi, fon yo'qoladi va tashqi oyna
   singan ko'rinadi.
2. **Forma ichida input** — qidiruvda Enter bosilsa tashqi
   `<form id="consultationForm">` yuboriladi, ya'ni shifokor bilmagan
   holda qabulni yakunlab qo'yadi.

`detachModals()` ni o'chirib ko'ring — testning birinchi ikki bandi
yiqiladi.

## linkedom cheklovlari

`checked` IDL xossasi yo'q (atribut bor, `el.checked` — `undefined`).
Shuning uchun test boshida holat qo'lda tenglashtiriladi. Bu kodning
kamchiligi emas, muhitniki.
