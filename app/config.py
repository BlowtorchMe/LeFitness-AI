"""
Configuration management for the application
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application
    app_name: str = "LE Fitness AI System"
    environment: str = "development"
    debug: bool = True
    
    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4"
    
    # META/Facebook (Optional in test mode)
    meta_app_id: Optional[str] = None
    meta_app_secret: Optional[str] = None
    meta_access_token: Optional[str] = None
    meta_verify_token: Optional[str] = None
    
    # Google Calendar (Optional - only needed for booking tracking)
    google_calendar_id: Optional[str] = None
    google_service_account: Optional[str] = None
    google_appointment_schedule_link: Optional[str] = None
    google_calendar_webhook_url: Optional[str] = None  # Public URL for calendar webhook (e.g., https://yourdomain.com/webhooks/calendar)
    timezone: str = "UTC"
    
    # Database
    database_url: str = "postgresql://user:password@localhost:5432/lefitness"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Gym Information
    gym_name: str = "LE Fitness"
    gym_phone: Optional[str] = None
    gym_email: Optional[str] = None
    
    # Free Trial Period
    free_trial_days: int = 10
    
    # Testing/Mock Mode
    use_mock_apis: bool = False  # Set to True to use mock APIs instead of real ones
    test_mode: bool = False  # Enable test mode features
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        env_file_encoding = "utf-8"
        # Don't fail if .env file doesn't exist (for Vercel)
        env_file_required = False


# Global settings instance
# Pydantic will use environment variables and defaults
settings = Settings()

