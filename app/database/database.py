"""
Database connection and session management
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings
from app.database.base import Base

# Create database engine
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables"""
    # Import all models to register them with the shared Base
    from app.models import lead, booking, conversation
    from sqlalchemy import text
    
    # Drop all existing tables first using raw SQL (in reverse order of dependencies)
    with engine.connect() as conn:
        # Disable foreign key checks temporarily (PostgreSQL)
        if "postgresql" in settings.database_url:
            conn.execute(text("DROP TABLE IF EXISTS conversations CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS bookings CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS leads CASCADE"))
        # SQLite
        elif "sqlite" in settings.database_url:
            conn.execute(text("DROP TABLE IF EXISTS conversations"))
            conn.execute(text("DROP TABLE IF EXISTS bookings"))
            conn.execute(text("DROP TABLE IF EXISTS leads"))
        else:
            # For other databases, try to drop in order
            conn.execute(text("DROP TABLE IF EXISTS conversations"))
            conn.execute(text("DROP TABLE IF EXISTS bookings"))
            conn.execute(text("DROP TABLE IF EXISTS leads"))
        conn.commit()
    
    # Create all tables at once (SQLAlchemy will handle the order)
    # Since all models now use the same Base, foreign keys will resolve correctly
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

