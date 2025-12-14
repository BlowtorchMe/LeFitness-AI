"""
Database connection and session management
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings
from app.models.lead import Base as LeadBase
from app.models.booking import Base as BookingBase
from app.models.conversation import Base as ConversationBase

# Create database engine
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables"""
    # Import all models to register them
    from app.models import lead, booking, conversation
    
    # Create all tables using a single metadata that combines all bases
    # This ensures proper foreign key relationships
    from sqlalchemy import MetaData
    metadata = MetaData()
    
    # Import all table definitions
    for table in LeadBase.metadata.tables.values():
        table.tometadata(metadata)
    for table in BookingBase.metadata.tables.values():
        table.tometadata(metadata)
    for table in ConversationBase.metadata.tables.values():
        table.tometadata(metadata)
    
    # Create all tables at once
    metadata.create_all(bind=engine)


def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

