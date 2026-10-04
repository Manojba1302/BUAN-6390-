"""Single place every setting is read from. Nothing else reads os.environ."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "HomeFlow API"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    database_url: str = "postgresql+psycopg://homeflow:homeflow@localhost:5432/homeflow"
    rabbitmq_url: str = "amqp://homeflow:homeflow@localhost:5672/"
    extraction_queue: str = "document.extract"

    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "documents"
    s3_access_key: str = "homeflow"
    s3_secret_key: str = "homeflow123"
    s3_region: str = "us-east-1"
    markdown_dir: str = "/srv/markdown"

    ollama_base_url: str = "http://host.docker.internal:11434"
    classifier_model: str = "gemma3:4b"
    classifier_timeout_seconds: float = 120.0

    max_upload_mb: int = 20
    allowed_content_types: str = "application/pdf,image/jpeg,image/png,image/heic,image/webp,image/tiff"

    cookie_secure: bool = False  # Set true when serving through HTTPS.
    frontend_url: str = "http://localhost:5173"
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_from: str = "HomeFlow <no-reply@homeflow.local>"
    smtp_starttls: bool = False
    smtp_user: str = ""
    smtp_password: str = ""



    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_types(self) -> set[str]:
        return {t.strip() for t in self.allowed_content_types.split(",") if t.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


