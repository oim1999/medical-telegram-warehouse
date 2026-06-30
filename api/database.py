"""
api/database.py
-----------------
SQLAlchemy database connection setup for the FastAPI application.

Provides a session factory and a FastAPI dependency (get_db) that
endpoints use to obtain a database session, ensuring sessions are
always properly closed after each request.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

POSTGRES_HOST     = os.environ.get("POSTGRES_HOST",     "localhost")
POSTGRES_PORT     = os.environ.get("POSTGRES_PORT",     "5432")
POSTGRES_DB       = os.environ.get("POSTGRES_DB",       "medical_warehouse")
POSTGRES_USER     = os.environ.get("POSTGRES_USER",     "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "root")

DATABASE_URL = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# pool_pre_ping=True checks connection liveness before each use,
# preventing "server closed the connection unexpectedly" errors
# after periods of inactivity (common with default Postgres timeouts).
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    FastAPI dependency that yields a database session and guarantees
    it is closed after the request completes, even if an exception
    is raised during request handling.

    Usage in an endpoint:
        @app.get("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
