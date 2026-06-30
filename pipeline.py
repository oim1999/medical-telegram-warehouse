"""
pipeline.py
------------
Dagster pipeline orchestrating the full ELT process as four sequential
ops, with a daily schedule for automated runs.

Op execution order:
    scrape_telegram_data
        -> load_raw_to_postgres
            -> run_dbt_transformations
                -> run_yolo_enrichment

Launch the Dagster UI to run and monitor this pipeline:
    dagster dev -f pipeline.py
    Then open http://localhost:3000
"""

import subprocess
import sys
from pathlib import Path

from dagster import (
    op, job, OpExecutionContext, Config,
    ScheduleDefinition, DefaultScheduleStatus,
    Failure, RetryPolicy, Definitions,
)

BASE_DIR = Path(__file__).resolve().parent


def run_command(cmd: list[str], cwd: Path, context: OpExecutionContext) -> None:
    """
    Helper that runs a subprocess command, streams output to the Dagster
    log, and raises a Dagster Failure with the captured output if the
    command exits non-zero. Centralizing this logic avoids repeating
    the same try/except subprocess pattern in every op.
    """
    context.log.info(f"Running: {' '.join(cmd)} (cwd={cwd})")

    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )

    if result.stdout:
        context.log.info(result.stdout)
    if result.stderr:
        context.log.warning(result.stderr)

    if result.returncode != 0:
        raise Failure(
            description=f"Command failed with exit code {result.returncode}: {' '.join(cmd)}",
            metadata={"stdout": result.stdout, "stderr": result.stderr},
        )


class ScrapeConfig(Config):
    """Configuration for the scrape_telegram_data op, settable from the Dagster UI."""
    limit: int = 200
    channels: list[str] = []   # empty = use scraper's DEFAULT_CHANNELS


# ── Op 1: Scrape Telegram ────────────────────────────────────────────────────

@op(
    retry_policy=RetryPolicy(max_retries=2, delay=30),
    # Telegram rate limits (FloodWaitError) are transient — retrying
    # after a delay is the correct recovery strategy rather than
    # failing the whole pipeline run immediately.
)
def scrape_telegram_data(context: OpExecutionContext, config: ScrapeConfig) -> str:
    """
    Runs the Telethon scraper (src/scraper.py) as a subprocess.
    Subprocess isolation is used because Telethon's asyncio event loop
    does not play well inside Dagster's own execution context when
    called as an in-process import.
    """
    cmd = [sys.executable, "src/scraper.py", "--limit", str(config.limit)]
    if config.channels:
        cmd += ["--channels"] + config.channels

    run_command(cmd, cwd=BASE_DIR, context=context)
    context.log.info("Scraping complete.")
    return "scrape_complete"


# ── Op 2: Load raw data to PostgreSQL ────────────────────────────────────────

@op(
    retry_policy=RetryPolicy(max_retries=2, delay=15),
)
def load_raw_to_postgres(context: OpExecutionContext, upstream: str) -> str:
    """
    Loads the JSON data lake into raw.telegram_messages.
    Depends on scrape_telegram_data via the `upstream` input, which
    enforces Dagster's execution order even though no data actually
    flows between the two ops (both communicate through the filesystem
    and database, not in-memory).
    """
    cmd = [sys.executable, "scripts/load_raw_to_postgres.py", "--all"]
    run_command(cmd, cwd=BASE_DIR, context=context)
    context.log.info("Raw data loaded to PostgreSQL.")
    return "load_complete"


# ── Op 3: Run dbt transformations ────────────────────────────────────────────

@op
def run_dbt_transformations(context: OpExecutionContext, upstream: str) -> str:
    """
    Runs `dbt run` followed by `dbt test` inside the medical_warehouse/
    directory. If any dbt test fails, this op fails the pipeline run —
    bad data should never silently propagate downstream.
    """
    dbt_dir = BASE_DIR / "medical_warehouse"

    run_command(["dbt", "run"], cwd=dbt_dir, context=context)
    run_command(["dbt", "test"], cwd=dbt_dir, context=context)

    context.log.info("dbt models built and tests passed.")
    return "dbt_complete"


# ── Op 4: Run YOLO enrichment ─────────────────────────────────────────────────

@op
def run_yolo_enrichment(context: OpExecutionContext, upstream: str) -> str:
    """
    Runs YOLOv8 detection on all downloaded images, then loads the
    results into PostgreSQL and rebuilds the fct_image_detections
    model (which depends on the freshly loaded raw.image_detections
    table, so dbt run is invoked again for just that model).
    """
    run_command(
        [sys.executable, "src/yolo_detect.py"],
        cwd=BASE_DIR, context=context,
    )
    run_command(
        [sys.executable, "scripts/load_yolo_results.py"],
        cwd=BASE_DIR, context=context,
    )
    run_command(
        ["dbt", "run", "--select", "stg_image_detections", "fct_image_detections"],
        cwd=BASE_DIR / "medical_warehouse", context=context,
    )

    context.log.info("YOLO enrichment complete and loaded into warehouse.")
    return "yolo_complete"


# ── Job: wires the ops together in dependency order ──────────────────────────

@job(
    description=(
        "Full ELT pipeline: scrape Telegram -> load raw -> dbt transform "
        "-> YOLO enrichment. Each op depends on the previous op's output, "
        "enforcing correct execution order."
    )
)
def medical_warehouse_pipeline():
    scrape_result = scrape_telegram_data()
    load_result = load_raw_to_postgres(scrape_result)
    dbt_result = run_dbt_transformations(load_result)
    run_yolo_enrichment(dbt_result)


# ── Schedule: daily execution ─────────────────────────────────────────────────

daily_schedule = ScheduleDefinition(
    job=medical_warehouse_pipeline,
    cron_schedule="0 2 * * *",   # Every day at 02:00 UTC — off-peak hours,
                                  # reduces overlap with manual development runs
                                  # and likely lower Telegram API load.
    default_status=DefaultScheduleStatus.STOPPED,
    # STOPPED by default: an operator must explicitly enable the schedule
    # from the Dagster UI. This prevents an accidental scrape of live
    # Telegram credentials immediately after first deploying the pipeline.
    description="Runs the full medical warehouse ELT pipeline daily at 02:00 UTC.",
)


# Definitions object — this is what `dagster dev -f pipeline.py` discovers
defs = Definitions(
    jobs=[medical_warehouse_pipeline],
    schedules=[daily_schedule],
)
