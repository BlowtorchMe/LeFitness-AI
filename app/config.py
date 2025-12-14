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
    openai_api_key: str
    openai_model: str = "gpt-4"
    
    # Twilio SMS (Optional - only needed for SMS features)
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None
    
    # META/Facebook (Optional in test mode)
    meta_app_id: Optional[str] = None
    meta_app_secret: Optional[str] = None
    meta_access_token: Optional[str] = None
    meta_verify_token: Optional[str] = None
    
    # Google Calendar (Optional - only needed for calendar features)
    google_calendar_id: Optional[str] = None  # Calendar ID (usually your email)
    google_client_config: Optional[str] = None  # JSON string for OAuth
    google_service_account: Optional[str] = None  # Path to service account JSON
    google_api_key: Optional[str] = None  # API key (for read-only access)
    timezone: str = "UTC"
    
    # Email (SMTP) (Optional - Google Calendar sends emails automatically)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: Optional[str] = None  # SMTP username (usually your email)
    smtp_password: Optional[str] = None  # SMTP password or app password
    from_email: Optional[str] = None  # From email (defaults to smtp_user)
    
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


# Global settings instance
settings = Settings()

