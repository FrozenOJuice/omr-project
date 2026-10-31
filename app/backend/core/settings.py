from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "OMR System"
    debug: bool = False
    postgres_user: str
    postgres_password: str
    postgres_db: str
    database_url: str
    jwt_access_secret: str
    jwt_refresh_secret: str
    jwt_access_expire_seconds: int = Field(gt=0)
    jwt_refresh_expire_seconds: int = Field(gt=0)
    resend_api_key: str | None = None
    # Dev-only: log emails (with their links) instead of sending them via
    # Resend, so email flows can be tested without an external service or key.
    email_console_mode: bool = False
    email_from: str | None = None
    frontend_password_reset_url: str | None = None
    frontend_origin: str | None = None
    course_invite_expire_seconds: int = Field(
        default=604800,
        gt=0,
        le=2592000,
    )
    password_reset_expire_seconds: int = Field(default=1800, gt=0, le=86400)
    # Activation links are mailed to someone who wasn't at the keyboard when the
    # account was made, so they need to outlive the 30-minute reset window.
    account_activation_expire_seconds: int = Field(
        default=259200, gt=0, le=1209600
    )
    omr_host: str = "omr_service"
    omr_port: int = 3000
    canvas_public_base_url: str = "http://localhost:6700"
    canvas_api_base_url: str = "http://localhost:6700"
    canvas_token_encryption_secret: str | None = None
    canvas_student_access_token_expire_seconds: int = Field(
        default=604800,
        gt=0,
        le=2592000,
    )
    canvas_http_timeout_seconds: float = Field(default=10, gt=0, le=60)
    canvas_operation_timeout_seconds: float = Field(default=60, gt=0, le=300)
    canvas_batch_concurrency: int = Field(default=5, ge=1, le=20)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    @property
    def omr_base_url(self) -> str:
        return f"http://{self.omr_host}:{self.omr_port}"

settings = Settings()
