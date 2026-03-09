# ZIK Bot System (Telegram Bot + Web Redirect + Extension)

Bu ZIP faylının içində 3 hissə var:

1) **Telegram bot** – istifadəçilərə ZIK hesabı paylayır (növbə, 5/10 dəqiqə təsdiq, 60 dəq sessiya, uzatma və s.)
2) **Web server (FastAPI)** – `.../zik/<slug>` linkini real ZIK login səhifəsinə yönləndirir və Extension üçün `/api/session/<token>` API verir.
3) **Chrome Extension (MVP)** – istifadəçi linki botdan açanda tokeni oxuyur, serverdən login/parolu götürür və ZIK login səhifəsində doldurur + countdown göstərir.

> ⚠️ Təhlükəsizlik: ZIP-də **.env yoxdur**. Token və DB məlumatlarını Render-də environment variables kimi yazın.

---

## 1) Database

PostgreSQL yaradın və `database/schema.sql` faylını icra edin.

Render Postgres istifadə edirsinizsə:
1. Postgres service yaradın
2. `DATABASE_URL` alın
3. SQL editor ilə `schema.sql` run edin

---

## 2) Bot (aiogram)

### Environment variables

`.env.example`-də olanları Render-də yazın:

- `BOT_TOKEN`
- `DATABASE_URL`
- `TIMEZONE=Asia/Baku`

### Lokal run

```bash
pip install -r requirements.txt
python main.py
```

### Render run command

```bash
python main.py
```

---

## 3) Web server (FastAPI)

### Lokal run

```bash
pip install -r requirements.txt
uvicorn web.server:app --host 0.0.0.0 --port 8000
```

### Render run command

```bash
uvicorn web.server:app --host 0.0.0.0 --port $PORT
```

Server işləyəndə bu endpointlər hazır olur:

- `GET /zik/<slug>?t=<token>` → ZIK login səhifəsinə redirect
- `GET /api/session/<token>` → Extension üçün login/parol + qalan vaxt
- `POST /api/heartbeat/<token>` → tab heartbeat

Default ZIK login URL: `https://app.zikanalytics.com/login`.
İstəsəniz `ZIK_LOGIN_URL` env var ilə dəyişə bilərsiniz.

---

## 4) Chrome Extension (MVP)

`extension/` qovluğunu Chrome-da `chrome://extensions` → **Developer mode** → **Load unpacked** ilə yükləyin.

Extension tokeni `zik_token` və ya `t` query parametrindən oxuyur.

---

## Admin ID-lər

`config.py` içində sabitdir:

- `7665317457`
- `2091774116`

İstəsəniz dəyişə bilərsiniz.

---

## Qısa istifadə

1) İstifadəçi /start → dil seçir → menü
2) Abunəlik aktiv deyilsə bot xəbərdarlıq verir
3) “ZIK hesabı al” → boş hesab varsa 5 dəq təsdiq, yoxdursa növbə
4) “ZIK-ə daxil ol” → 60 dəq sessiya başlayır
5) 30 dəq qalanda bot “Müddəti uzat” göndərir (30 və ya 60 dəq)
