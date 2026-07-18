# Perfumaria — demo VPS

App pessoal do Renato para inventário e uso da coleção de perfumes.

Embedado no [clavis-renato](https://clavis-renato.napel.com.br) → **Vida → Perfumaria**.
Standalone em https://perfumaria.demos.napel.com.br.

## Stack
- Flask 3 + gunicorn + SQLite (`/data/perfumaria.db`)
- Frontend: HTML + Alpine.js + Tailwind CDN (single-file `static/app.html`)
- Scrape Fragrantica via cache local (v1) — Playwright headless na v2

## Rodar local
```bash
python app.py
# ou
DB_PATH=/tmp/dev.db PORT=5006 gunicorn -c gunicorn_conf.py app:app
```
Abre em http://localhost:5006.

## Endpoints REST
- `GET /api/perfumes` · `POST /api/perfumes` · `PUT /api/perfumes/:id` · `DELETE /api/perfumes/:id`
- `POST /api/perfumes/:id/spray` · `GET /api/perfumes/:id/sprays` · `DELETE /api/sprays/:id`
- `POST /api/scrape` (body: `{"url": "..."}`)
- `GET /api/random-pick`
- `POST /api/import` (mock)

## Deploy
Push em `main` → deploy manual no Coolify (não tem auto-deploy).
