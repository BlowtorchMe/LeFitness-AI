"""
Configuration management for the application
"""
from dotenv import load_dotenv
load_dotenv()

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    app_name: str = "LE Fitness AI System"
    environment: str = "development"
    debug: bool = True

    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4"
    openai_embedding_model: str = "text-embedding-3-small"

    # META/Facebook (Optional in test mode)
    meta_app_id: Optional[str] = None
    meta_app_secret: Optional[str] = None
    meta_access_token: Optional[str] = None
    meta_verify_token: Optional[str] = None

    # Google Calendar (Optional - only needed for booking tracking)
    google_calendar_id: Optional[str] = None
    google_calendar_id_varmdo: Optional[str] = None
    google_calendar_id_taby: Optional[str] = None
    google_service_account: Optional[str] = None
    google_appointment_schedule_link: Optional[str] = None
    google_calendar_webhook_url: Optional[str] = None  # Public URL for calendar webhook
    timezone: str = "UTC"

    # Media / video
    machine_video_base_url: Optional[str] = None

    # Database (MÅSTE finnas i env/.env eller docker compose environment)
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Gym Information
    gym_name: str = "LE Fitness"
    gym_phone: Optional[str] = None
    gym_email: Optional[str] = None

    # Machine videos
    machine_video_base_url: Optional[str] = None

    # Free Trial Period
    free_trial_days: int = 10

    # Testing/Mock Mode
    use_mock_apis: bool = False
    test_mode: bool = False

    # Viktigt: ignorera env-variabler som inte finns som fält (t.ex. POSTGRES_PASSWORD)
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Global settings instance
settings = Settings()

# (valfritt) Debug-print: slå på bara om du vill felsöka
# import os
# if os.getenv("DEBUG_SETTINGS") == "1":
#     print("ENV OPENAI_API_KEY exists:", bool(os.getenv("OPENAI_API_KEY")))
#     print("settings.openai_api_key exists:", bool(getattr(settings, "openai_api_key", None)))
#     print("ENV keys sample:", [k for k in os.environ.keys() if "OPENAI" in k])