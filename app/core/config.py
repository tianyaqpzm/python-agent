import os
from typing import Optional
from dotenv import load_dotenv
from functools import lru_cache

# Load environment variables from .env file (if still exists)
load_dotenv()

class Config:
    """Base configuration."""

    APP_ENV: str = os.getenv("APP_ENV", "development")

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT") or 8181)

    # Nacos Bootstrap
    NACOS_SERVER_ADDR: str = os.getenv("NACOS_SERVER_ADDR", "127.0.0.1:8848")
    NACOS_NAMESPACE: str = os.getenv("NACOS_NAMESPACE", "")
    NACOS_GROUP: str = os.getenv("NACOS_GROUP", "DEFAULT_GROUP")
    NACOS_USERNAME: str = os.getenv("NACOS_USERNAME", "")
    NACOS_PASSWORD: str = os.getenv("NACOS_PASSWORD", "")
    SERVICE_NAME: str = os.getenv("SERVICE_NAME", "ms-py-agent")
    SERVICE_IP: Optional[str] = os.getenv("SERVICE_IP")
    NACOS_HEARTBEAT_INTERVAL: int = int(os.getenv("NACOS_HEARTBEAT_INTERVAL", 5)) # 默认为 5s
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")
    NACOS_TIMEOUT: int = int(os.getenv("NACOS_TIMEOUT", 10))
    NACOS_RETRIES: int = int(os.getenv("NACOS_RETRIES", 5))

    # MCP / Discovery
    MCP_BRAVE_PATH: Optional[str] = os.getenv("MCP_BRAVE_PATH")
    NACOS_GATEWAY_SERVICE_NAME: str = os.getenv("NACOS_GATEWAY_SERVICE_NAME", "ms-java-gateway")
    NACOS_JAVA_SERVICE_NAME: str = os.getenv("NACOS_JAVA_SERVICE_NAME", "ms-java-biz")

    # Security
    JWT_SECRET: str = os.getenv("JWT_SECRET", "your-256-bit-secret-your-256-bit-secret")
    JWT_WHITELIST: list[str] = ["/health", "/docs", "/openapi.json", "/redoc"]

    # Database
    PG_HOST: str = os.getenv("PG_HOST", "localhost")
    PG_PORT: int = int(os.getenv("PG_PORT") or 5432)
    PG_USER: str = os.getenv("PG_USER", "postgres")
    PG_PASSWORD: str = os.getenv("PG_PASSWORD", "postgres")
    PG_DB: str = os.getenv("PG_DB", "postgres")

    @property
    def DB_URI(self) -> str:
        return f"postgresql://{self.PG_USER}:{self.PG_PASSWORD}@{self.PG_HOST}:{self.PG_PORT}/{self.PG_DB}?sslmode=require&connect_timeout=10"

    @property
    def DB_ASYNC_URI(self) -> str:
        return f"postgresql+psycopg://{self.PG_USER}:{self.PG_PASSWORD}@{self.PG_HOST}:{self.PG_PORT}/{self.PG_DB}?sslmode=require&connect_timeout=10"

    # LLM
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "new-api")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "dummy")
    LLM_SKIP_SSL_VERIFY: bool = os.getenv("LLM_SKIP_SSL_VERIFY", "true").lower() == "true"
    LLM_RPM: int = int(os.getenv("LLM_RPM") or 2) # 每分钟最大请求数

    # KB
    KB_LLM_PROVIDER: str = os.getenv("KB_LLM_PROVIDER", "new-api")
    KB_LLM_MODEL: str = os.getenv("KB_LLM_MODEL", "gpt-4o")
    KB_EMBEDDING_PROVIDER: str = os.getenv("KB_EMBEDDING_PROVIDER", "new-api")
    KB_EMBEDDING_MODEL: str = os.getenv("KB_EMBEDDING_MODEL", "gemini-embedding-2")
    KB_EMBEDDING_RPM: int = int(os.getenv("KB_EMBEDDING_RPM") or 2) # 每分钟最大请求数
    KB_CHUNK_SIZE: int = int(os.getenv("KB_CHUNK_SIZE") or 500)
    KB_CHUNK_OVERLAP: int = int(os.getenv("KB_CHUNK_OVERLAP") or 50)
    KB_VECTOR_TABLE: str = os.getenv("KB_VECTOR_TABLE", "langchain_pg_embedding")
    KB_LLM_TEMPERATURE: float = float(os.getenv("KB_LLM_TEMPERATURE") or 0.7)

    @property
    def KB_BASE_URL(self) -> str:
        return os.getenv("KB_BASE_URL") or self.LLM_BASE_URL

    @property
    def KB_API_KEY(self) -> str:
        return os.getenv("KB_API_KEY") or self.LLM_API_KEY

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

@lru_cache()
def get_settings():
    env = os.getenv("APP_ENV", "development")
    if env == "production":
        return ProductionConfig()
    return DevelopmentConfig()

settings = get_settings()
