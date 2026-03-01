import os

from functools import lru_cache


class Config:
    """Base configuration."""

    APP_ENV = os.getenv("APP_ENV", "development")

    # Server
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", 8181))

    # Nacos
    NACOS_SERVER_ADDR = os.getenv("NACOS_SERVER_ADDR", "127.0.0.1:8848")
    NACOS_NAMESPACE = os.getenv("NACOS_NAMESPACE", "public")
    NACOS_USERNAME = os.getenv("NACOS_USERNAME", "")
    NACOS_PASSWORD = os.getenv("NACOS_PASSWORD", "")
    SERVICE_NAME = os.getenv("SERVICE_NAME", "python-agent")

    # MCP Clients
    MCP_BRAVE_PATH = os.getenv("MCP_BRAVE_PATH")  # Optional override
    NACOS_GATEWAY_SERVICE_NAME = os.getenv("NACOS_GATEWAY_SERVICE_NAME", "gateway")

    # Database
    PG_HOST = os.getenv("PG_HOST", "localhost")
    PG_PORT = int(os.getenv("PG_PORT", 5432))
    PG_USER = os.getenv("PG_USER", "postgres")
    PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
    PG_DB = os.getenv("PG_DB", "postgres")
    DB_URI = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    DB_ASYNC_URI = (
        f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    )

    # LLM Configuration
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # gemini, openai
    # Default Base URL for Gemini via Gateway (assuming Gateway is at localhost:8281)
    # The Gateway route is /gemini/** -> https://generativelanguage.googleapis.com
    # So we point the client to http://localhost:8281/gemini
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8281/gemini")
    LLM_MODEL = os.getenv("LLM_MODEL", "gemini-1.5-flash")


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True
    # In Dev, we might want to default to localhost if not specified,
    # but the user's current valid config points to an external Nacos.
    # We'll keep the external Nacos as default for now based on current working code.
    pass


class ProductionConfig(Config):
    """Production configuration."""

    DEBUG = False
    # Enforce stricter defaults or require env vars here if needed


@lru_cache()
def get_settings():
    env = os.getenv("APP_ENV", "development")
    if env == "production":
        return ProductionConfig()
    return DevelopmentConfig()


settings = get_settings()
