# Serverga chiqarish — qadamma-qadam

Ubuntu 22.04, loyiha `/opt/edumed-his` da, domen `doctorbnajot.uz`.

Har bir bosqichdan keyin **tekshiruv buyrug'i** bor. Tekshiruvdan
o'tmasdan keyingisiga o'tmang — aks holda xato qayerdan kelganini
topish qiyin bo'ladi.

---

## 0. Zaxira (birinchi navbatda)

Yangilashdan oldin bazani saqlab qo'ying. Bu bir daqiqa vaqt oladi,
lekin xato bo'lsa yagona qutqaruvchi shu.

```bash
cd /opt/edumed-his
bash server/5-zaxira.sh
```

---

## 1. Kodni yangilash

```bash
cd /opt/edumed-his
sudo systemctl stop edumed-his          # serverni to'xtatamiz
git pull                                 # yoki fayllarni ko'chiring
```

---

## 2. Kutubxonalar

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Yangi kutubxona qo'shilmagan bo'lsa ham buni bajaring — `edge-tts`
yangilanishi mumkin.

---

## 3. Ma'lumotlar bazasi

```bash
python manage.py migrate
```

Kutilayotgan yangi migratsiyalar:

| Migratsiya | Nima qiladi |
|---|---|
| `clinical.0030–0031` | Tekshiruvlar guruhlari (+Analiz, +UZI…) va katalogni taqsimlash |
| `clinical.0032–0033` | Statsionar epizodi, MKB-10 kodlari |
| `clinical.0034` | Rektoromanoskopiya qo'shish, o'xshash nomlarni aniqlashtirish |
| `clinical.0035` | Vipiska (chiqish xulosasi) |
| `patients.0002` | Metrika (tug'ilganlik guvohnomasi) maydoni |
| `billing.0005` | To'lov tartibi: oldindan / kassaga |

Migratsiyalar ma'lumotni **o'chirmaydi**, faqat qo'shadi.

---

## 4. Statik fayllar

```bash
python manage.py collectstatic --noinput
```

Buni o'tkazib yuborsangiz sayt **bezaksiz** ochiladi: CSS va JS
yuklanmaydi, tekshiruv pikeri va matn maydonlari ishlamaydi.

---

## 5. Huquqlar

```bash
sudo chown -R www-data:www-data /opt/edumed-his/media
sudo chown -R www-data:www-data /opt/edumed-his/logs
sudo chmod -R u+rwX /opt/edumed-his/media
```

`media/tts/` ga yozib bo'lmasa ovoz fayllari saqlanmaydi va tabloda
jimlik bo'ladi.

---

## 6. TEKSHIRUV

```bash
python manage.py deploy_check
```

Har bir band uchun `[OK]`, `[OGOH]` yoki `[XATO]` va nima qilish
kerakligi chiqadi. **Bitta ham `[XATO]` qolmasin.**

---

## 7. Ishga tushirish

```bash
sudo systemctl start edumed-his
sudo systemctl status edumed-his --no-pager
sudo systemctl reload nginx
```

Jonli jurnal:

```bash
sudo journalctl -u edumed-his -f
```

---

## 8. Yakuniy tekshiruv (brauzerda)

1. `https://doctorbnajot.uz` — kirish sahifasi ochiladimi
2. Tizimga kiring, chap menyu to'liq ko'rinadimi
3. `https://doctorbnajot.uz/registration/board/tts/health/` — ovoz holati
4. Tabloni oching va bemor chaqirib ko'ring — ovoz eshitiladimi

---

# OVOZ ISHLAMASA — nima qilish kerak

Tabloda ovoz chiqmasligining **uchta** sababi bor va ular tashqaridan
bir xil ko'rinadi: shunchaki jimlik. Quyidagi tartibda ajrating.

## Qadam 1 — serverda ovoz ishlaydimi?

```bash
cd /opt/edumed-his && source .venv/bin/activate
python manage.py deploy_check --tts-only
```

### Natija: `[OK] O'zbekcha ovoz generatsiya qilindi`

Server tomoni **soz**. Muammo brauzerda — 2-qadamga o'ting.

### Natija: `[XATO] edge-tts o'rnatilmagan`

```bash
source /opt/edumed-his/.venv/bin/activate
pip install -r requirements.txt
python manage.py deploy_check --tts-only     # qayta tekshiring
```

### Natija: `[XATO] Ovoz keshiga yozib bo'lmaydi`

Papka huquqi. Gunicorn `www-data` nomidan ishlaydi:

```bash
sudo chown -R www-data:www-data /opt/edumed-his/media
sudo systemctl restart edumed-his
```

### Natija: `[XATO] Ovoz fayli yaratilmadi` yoki `muddatdan oshdi`

**Eng ko'p uchraydigan sabab.** `edge-tts` ovozni o'zi yasamaydi — u
Microsoft xizmatiga ulanadi. Ko'p VPS'da chiquvchi trafik yopiq bo'ladi.

Tekshiring:

```bash
curl -I --max-time 10 https://speech.platform.bing.com
```

- **Javob kelsa** — internet bor, sabab boshqada. Jurnalga qarang:
  `sudo journalctl -u edumed-his -n 100 --no-pager`
- **Javob kelmasa** — chiquvchi 443-port yopiq. Ikki yo'l:

  1. Provayderdan chiquvchi HTTPS ga ruxsat so'rang (odatda bir
     so'rov bilan ochiladi), yoki

  2. Proksi orqali ishlating — `/opt/edumed-his/.env` ga qo'shing:

     ```
     HTTPS_PROXY=http://proksi-manzili:port
     ```

     so'ng `sudo systemctl restart edumed-his`

> **Muhim:** ovoz ishlamasa ham tizim to'xtamaydi. Tabloda bemor
> raqami va ismi ko'rinib turaveradi, faqat ovoz eshitilmaydi.

## Qadam 2 — brauzerda ovoz to'silganmi?

Bu **eng ko'p uchraydigan** holat va uni server jurnalidan ko'rib
bo'lmaydi.

Brauzer sahifa bilan hech qanday aloqa bo'lmaguncha ovoz chiqarishga
ruxsat bermaydi. Tablo esa kun bo'yi ochiq turadi va unga hech kim
tegmaydi — natijada har bir chaqiruv jimgina yo'qoladi.

**Nima uchun localhostda ishlagan:** dasturchi sahifani doim ochgani
uchun brauzer uni «ishonchli» deb belgilaydi. Yangi domen bunday
ishonchga ega emas.

**Yechim tizimga qo'shilgan:** ovoz to'silganda tablo pastida katta
qizil yozuv chiqadi — **«Ovozni yoqish uchun bosing»**. Bir marta
bosilsa, brauzer shu sahifaga ruxsat beradi va keyingi chaqiruvlar
o'zi eshitiladi. Har kuni ertalab tabloni yoqqanda bir marta bosish
kifoya.

Umuman bosishni istamasangiz — Chrome'ni shu bayroq bilan ishga
tushiring:

```bash
chrome --kiosk --autoplay-policy=no-user-gesture-required \
       https://doctorbnajot.uz/registration/board/
```

Bu tablo kompyuteridagi yorliqqa yozib qo'yiladi va qizil yozuv
umuman chiqmaydi.

## Qadam 3 — sessiya tugab qolganmi?

Tablo 12 soatdan ko'p ochiq tursa sessiya tugaydi va ovoz manzili
kirish sahifasiga yo'naltiriladi. Sahifani yangilab, qayta kiring.
Bu takrorlansa `.env` da muddatni oshiring:

```
SESSION_COOKIE_AGE=86400
```

---

# Orqaga qaytarish

Yangilashdan keyin jiddiy muammo chiqsa:

```bash
sudo systemctl stop edumed-his
cd /opt/edumed-his
git reset --hard <oldingi-commit>
bash server/6-tiklash.sh          # bazani zaxiradan tiklash
sudo systemctl start edumed-his
```

Migratsiyalar faqat qo'shadi, shuning uchun eski kod yangi baza bilan
ham ishlaydi — bazani tiklash odatda shart emas.
