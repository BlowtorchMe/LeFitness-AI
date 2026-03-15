"""
Database connection and session management
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings
from app.database.base import Base
from app.models import lead, booking, conversation, faq

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
        conn.execute(text("DROP TYPE IF EXISTS conversationchannel CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS messagedirection CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS leadstatus CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS bookingstatus CASCADE"))
        conn.execute(text("DROP TYPE IF EXISTS appointmenttype CASCADE"))
        conn.commit()

    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
