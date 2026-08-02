# Serverga o'rnatish — Doctor B Najot HIS

Linux (Ubuntu/Debian) serverda ishga tushirish bo'yicha to'liq qo'llanma.

---

## Tez ma'lumot

| Skript | Qachon ishlatiladi |
|---|---|
| `1-ornatish.sh` | Serverda **bir marta**, birinchi o'rnatishda |
| `2-yangilash.sh` | Kod o'zgargandan keyin **har safar** |
| `3-malumot-kochirish.sh` | SQLite'dan PostgreSQL ga ko'chirishda, **bir marta** |
| `4-tekshirish.sh` | "Hammasi joyidami?" — **har kuni** yoki muammoda |
| `5-zaxira.sh` | Zaxira nusxa — **har kuni avtomatik** (cron) |
| `6-tiklash.sh` | Zaxiradan qaytarish — **muammo bo'lganda** |

---

## Birinchi o'rnatish

### 1. Kodni serverga qo'yish

```bash
sudo mkdir -p /opt/edumed-his
sudo chown -R $USER:$USER /opt/edumed-his
cd /opt/edumed-his

# git bo'lsa:
git clone <repo-manzil> .
# yoki fayllarni scp bilan ko'chiring
```

### 2. Sozlamalar

```bash
cp .env.server .env
nano .env
```

**Albatta o'zgartiring:**
- `SECRET_KEY` — yangi kalit (o'rnatish skripti o'zi ham yaratadi)
- `ALLOWED_HOSTS` — domeningiz

**Tekshiring:** `DATABASE_URL` dagi parol kodlangan bo'lishi kerak.
Asl parolda `/`, `+`, `=` bo'lsa, ular URL ichida `%2F`, `%2B`, `%3D` bo'ladi.

### 3. O'rnatish

```bash
bash server/1-ornatish.sh
```

Skript hamma narsani qiladi: paketlar, virtual muhit, baza tekshiruvi,
migratsiya, statik fayllar. Oxirida keyingi qadamlarni yozib beradi.

### 4. Xizmatlar

```bash
sudo cp server/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now edumed-his edumed-celery

sudo cp server/nginx-edumed.conf /etc/nginx/sites-available/edumed
sudo ln -sf /etc/nginx/sites-available/edumed /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

### 5. HTTPS

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d doctorbnajot.uz -d www.doctorbnajot.uz
```

> Sertifikat o'rnatilgunga qadar `.env` da
> `SECURE_SSL_REDIRECT=False` qilib turing, aks holda sayt ochilmaydi.

### 6. Ma'lumotlarni ko'chirish

```bash
# Eski db.sqlite3 ni serverga ko'chiring, keyin:
bash server/3-malumot-kochirish.sh /yo/l/db.sqlite3
```

### 7. Kunlik zaxira (cron)

```bash
crontab -e
```
Quyidagini qo'shing:
```
0 2 * * * cd /opt/edumed-his && bash server/5-zaxira.sh >> logs/backup.log 2>&1
```

---

## Kundalik ish

```bash
cd /opt/edumed-his

bash server/4-tekshirish.sh          # hammasi joyidami
bash server/2-yangilash.sh           # kodni yangilash
bash server/5-zaxira.sh              # qo'lda zaxira

sudo systemctl restart edumed-his    # qayta ishga tushirish
sudo journalctl -u edumed-his -f     # jonli jurnal
```

---

## Muammolarni hal qilish

### Bazaga ulanmayapti

```bash
source .venv/bin/activate
python manage.py check_db
```

Bu buyruq muammoni aniq aytadi: port yopiqmi, parol xatomi, SSL muammosimi.

| Xato | Sabab | Yechim |
|---|---|---|
| `password authentication failed` | Paroldagi `/ + =` kodlanmagan | `.env` da `%2F`, `%2B`, `%3D` qiling |
| `Network is unreachable` | Firewall yoki IP oq ro'yxatda emas | Baza provayderida server IP'sini ruxsat bering |
| `SSL is not enabled` | Server SSL qo'llamaydi | `.env` da `DB_SSLMODE=disable` |
| `database does not exist` | Baza nomi xato | `DATABASE_URL` oxiridagi nomni tekshiring |

### CSRF verification failed

`.env` da `ALLOWED_HOSTS` to'g'ri yozilganini tekshiring —
`CSRF_TRUSTED_ORIGINS` o'sha ro'yxatdan avtomatik yasaladi.

### Sayt ochilmaydi / cheksiz yo'naltirish

Nginx'da `proxy_set_header X-Forwarded-Proto $scheme;` borligini tekshiring.
Bu sarlavha bo'lmasa Django HTTPS'ni ko'rmaydi va cheksiz redirect qiladi.

### Statik fayllar (CSS) ko'rinmayapti

```bash
source .venv/bin/activate
python manage.py collectstatic --noinput
sudo systemctl restart edumed-his
```

---

## Xavfsizlik eslatmasi

- `.env` faylini **hech qachon** git'ga yuklamang (`.gitignore` da bor)
- Baza paroli chat/xabar orqali yuborilgan bo'lsa — uni **almashtiring**
- Zaxira nusxalarni **boshqa joyda** ham saqlang (server buzilsa ular ham yo'qoladi)
- `python manage.py check --deploy` — vaqti-vaqti bilan ishga tushiring
