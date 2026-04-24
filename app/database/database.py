"""
Database connection and session management
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings
from app.database.base import Base
from app.models import lead, booking, conversation, faq, gym

# Create database engine (PostgreSQL)
# pool_pre_ping: check connection before use to avoid "SSL connection closed" on stale connections
# pool_recycle: refresh connections before server idle timeout closes them
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


def init_db():
    """Drop and recreate all tables and (PostgreSQL) enum types. Ensures pgvector extension for FAQ indexer."""
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("DROP TABLE IF EXISTS conversations CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS bookings CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS leads CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS faqs CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS gyms CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS faq_gyms CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS haystack_documents CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS conversationchannel CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS messagedirection CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS leadstatus CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS bookingstatus CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS appointmenttype CASCADE"))
        conn.commit()

    Base.metadata.create_all(bind=engine)


def ensure_schema() -> None:
    """Create any missing tables and add any missing columns. Safe to call on every startup."""
    Base.metadata.create_all(bind=engine)
    _migrate_columns()


def _migrate_columns() -> None:
    """Add new columns to existing tables when they don't exist yet."""
    migrations = [
        ("gyms", "calendar_channel_id", "VARCHAR(255)"),
        ("gyms", "calendar_resource_id", "VARCHAR(255)"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            exists = conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ), {"t": table, "c": column}).fetchone()
            if not exists:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
        conn.commit()


def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
