import os
import logging
from functools import lru_cache

class Config:
    """Base configuration."""
    APP_ENV = os.getenv("APP_ENV", "development")
    
    # Server
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", 8181))
    
    # Nacos
    NACOS_SERVER_ADDR = os.getenv("NACOS_SERVER_ADDR", "pei.12277.xyz:18848")
    NACOS_NAMESPACE = os.getenv("NACOS_NAMESPACE", "public")
    NACOS_USERNAME = os.getenv("NACOS_USERNAME", "nacos")
    NACOS_PASSWORD = os.getenv("NACOS_PASSWORD", "nacos")
    SERVICE_NAME = os.getenv("SERVICE_NAME", "python-agent")
    
    # MCP Clients
    MCP_BRAVE_PATH = os.getenv("MCP_BRAVE_PATH") # Optional override
    NACOS_GATEWAY_SERVICE_NAME = os.getenv("NACOS_GATEWAY_SERVICE_NAME", "gateway")

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
