# Medical Telegram Data Warehouse

An end-to-end ELT data pipeline for Ethiopian medical business intelligence,
built for **Kara Solutions**. Ingests data from public Telegram channels,
models it in a PostgreSQL star schema using **dbt**, enriches images with
**YOLOv8** object detection, and exposes insights through a **FastAPI**
analytical API orchestrated by **Dagster**.

---

## Architecture

```
Telegram API
     │ Telethon scraper
     ▼
Data Lake (JSON + Images)
     │ Python loader
     ▼
PostgreSQL — raw.telegram_messages
     │ dbt
     ▼
Staging → Star Schema (dim_channels, dim_dates, fct_messages)
     │ YOLOv8
     ▼
fct_image_detections
     │ FastAPI
     ▼
REST API endpoints
     │ Dagster
     ▼
Scheduled orchestration
```

---

## Telegram Channels

| Channel | Type |
|---------|------|
| [@EAHCI](https://t.me/EAHCI) | Medical Products |
| [@lobelia4cosmetics](https://t.me/lobelia4cosmetics) | Cosmetics & Health |
| [@tikvahpharma](https://t.me/tikvahpharma) | Pharmaceuticals |
| [@CheMed123](https://t.me/CheMed123) | Medical Products |
| [@medicalequipmentspare](https://t.me/medicalequipmentspare) | Medical equipment, spare parts and consultancy |


---

## Project Structure

```
medical-telegram-warehouse/
├── .github/workflows/    # CI pipeline (pytest)
├── data/
│   └── raw/
│       ├── telegram_messages/YYYY-MM-DD/{channel}.json
│       └── images/{channel}/{message_id}.jpg
├── logs/                 # Scraper and loader logs
├── medical_warehouse/    # dbt project
│   ├── dbt_project.yml
│   ├── profiles.yml
│   ├── models/
│   │   ├── staging/      # stg_telegram_messages.sql
│   │   └── marts/        # dim_channels, dim_dates, fct_messages
│   └── tests/            # Custom SQL tests
├── src/
│   └── scraper.py        # Telethon scraper
├── scripts/
│   ├── init_db.sql       # Database initialization
│   └── load_raw_to_postgres.py
├── api/                  # FastAPI application (Task 4)
├── tests/                # Python unit tests
├── docker-compose.yml    # PostgreSQL + pgAdmin
├── requirements.txt
└── .env.example
```

---

## Quick Start

### 1. Clone and configure environment

```bash
git clone https://github.com/your-org/medical-telegram-warehouse.git
cd medical-telegram-warehouse

cp .env.example .env
# Edit .env with your Telegram API credentials and PostgreSQL settings
```

### 2. Start the database

```bash
docker compose up -d
```

### 3. Install Python dependencies

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Scrape Telegram channels

```bash
python src/scraper.py --limit 500
```

### 5. Load raw data to PostgreSQL

```bash
python scripts/load_raw_to_postgres.py --all
```

### 6. Run dbt transformations

```bash
cd medical_warehouse
dbt deps
dbt run
dbt test
dbt docs generate && dbt docs serve
```

### 7. Run unit tests

```bash
pytest tests/ -v
```

---

## Environment Variables

Copy `.env.example` to `.env` and set:

| Variable | Description |
|----------|-------------|
| `TELEGRAM_API_ID` | From [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_API_HASH` | From [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_PHONE` | Your registered phone number |
| `POSTGRES_HOST` | Database host (default: `localhost`) |
| `POSTGRES_PORT` | Database port (default: `5432`) |
| `POSTGRES_DB` | Database name (default: `medical_warehouse`) |
| `POSTGRES_USER` | Database user |
| `POSTGRES_PASSWORD` | Database password |

> **Security:** Never commit `.env` to version control — it is listed in `.gitignore`.

---

## Data Sources

- [Telegram API](https://core.telegram.org/api) via [Telethon](https://docs.telethon.dev/)
- [et.tgstat.com/medicine](https://et.tgstat.com/medicine) — Ethiopian medical channel directory

---

## License

MIT — see `LICENSE` for details.
