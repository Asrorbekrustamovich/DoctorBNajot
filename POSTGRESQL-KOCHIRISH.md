# SQLite → PostgreSQL ga ko'chirish

Hozir tizim SQLite'da ishlayapti. Jiddiy klinika uchun **PostgreSQL** kerak:
bir vaqtda ko'p xodim yozganda ishonchli, ma'lumot buzilmaydi, tez ishlaydi.

Ma'lumotlaringiz **yo'qolmaydi** — hammasi ko'chiriladi.

---

## 1-qadam. PostgreSQL o'rnatish (bir marta)

1. Yuklab oling: https://www.postgresql.org/download/windows/
   (EDB Installer → PostgreSQL 16 yoki 17)
2. O'rnatishda:
   - **Parol** so'raydi — uni yozib qo'ying (masalan: `Najot2026Db!`)
   - Port: `5432` (o'zgartirmang)
   - Locale: default
3. O'rnatish tugagach **pgAdmin 4** ham o'rnatiladi.

## 2-qadam. Baza yaratish

**pgAdmin 4** ni oching → chapda `Servers` → `PostgreSQL` → parolni kiriting →
`Databases` ustiga o'ng tugma → **Create → Database…** →
- Database: `edumed_his`
- Save

Yoki terminalda:

```
"C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE edumed_his;"
```

## 3-qadam. Ma'lumotlarni zaxiralash (SQLite'dan)

Papkada terminal oching:

```
.venv\Scripts\python.exe manage.py backup_db
```

`backups/edumed_backup_YYYYMMDD_HHMMSS.zip` yaratiladi — **fayl nomini eslab qoling**.

## 4-qadam. `.env` faylini PostgreSQL'ga burish

`.env` faylini Notepad'da oching. Quyidagi qatorni toping:

```
DATABASE_URL=sqlite:///db.sqlite3
```

Uni **izohga oling** va tagiga PostgreSQL qatorini yozing
(`POSTGRES_PAROL` o'rniga 1-qadamdagi parolingizni qo'ying):

```
# DATABASE_URL=sqlite:///db.sqlite3
DATABASE_URL=postgres://postgres:POSTGRES_PAROL@localhost:5432/edumed_his
```

Saqlang.

## 5-qadam. Jadvallarni yaratish va ma'lumotni yuklash

```
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py restore_db --file edumed_backup_YYYYMMDD_HHMMSS.zip --yes
```

(fayl nomini 3-qadamdagi bilan almashtiring)

## 6-qadam. Tekshirish

```
START.bat
```

Kiring va tekshiring: bemorlar, tashriflar, cheklar, operatsiyalar — hammasi joyida
bo'lishi kerak. Endi tizim PostgreSQL'da ishlayapti.

---

## Orqaga qaytish (agar muammo bo'lsa)

`.env` da PostgreSQL qatorini izohga oling, SQLite qatorini qaytaring:

```
DATABASE_URL=sqlite:///db.sqlite3
# DATABASE_URL=postgres://...
```

Eski `db.sqlite3` fayli o'z joyida turadi — hech narsa yo'qolmaydi.

---

## Zaxira (backup) — eng muhim qoida

- **Har ishga tushirishda** avtomatik zaxira olinadi (`START.bat`)
- **Qo'lda zaxira:** `BACKUP.bat`
- **Tiklash:** `RESTORE.bat`
- Zaxiralar: `backups/` papkasida (oxirgi 30 tasi saqlanadi)

**MUHIM:** `backups` papkasini haftada bir marta **tashqi diskka yoki bulutga**
nusxalang. Kompyuter buzilsa yoki virus tegsa, faqat shu nusxa qutqaradi.

PostgreSQL'da qo'shimcha professional zaxira:

```
"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe" -U postgres -F c -f edumed.dump edumed_his
```
