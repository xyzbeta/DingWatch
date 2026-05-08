from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Admin defaults — override in .env
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""

    # JWT / Logging — read from .env or environment
    DINGWATCH_JWT_SECRET: str = ""
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
