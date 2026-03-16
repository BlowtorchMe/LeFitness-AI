"""
Database connection and session management
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.config import settings
from app.database.base import Base
from app.models import lead, booking, conversation, faq  # noqa: F401

# Create database engine (PostgreSQL)
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Drop and recreate all tables and (PostgreSQL) enum types. Use with caution."""
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("DROP TABLE IF EXISTS conversations CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS bookings CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS leads CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS faqs CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS conversationchannel CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS messagedirection CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS leadstatus CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS bookingstatus CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS appointmenttype CASCADE"))
        conn.commit()

    Base.metadata.create_all(bind=engine)
    print("init_db() finished")


def ensure_db():
    """
    Safe DB initialization:
    - tries to ensure pgvector extension
    - creates tables if they do not already exist
    """
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            print("vector extension ensured")
        except Exception as e:
            print("Could not ensure vector extension:", str(e))
            conn.rollback()

    Base.metadata.create_all(bind=engine)
    print("Base.metadata.create_all finished")


def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()