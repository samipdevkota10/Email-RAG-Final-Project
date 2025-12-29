# src/config.py
"""
Centralized configuration using Pydantic Settings.
All environment variables are loaded and validated here.

Supports TWO databases:
- LOCAL: DATABASE_URL or LOCAL_DB_* (for chat/search)
- ANALYTICS: DB_* variables (AWS database with companies table)
"""
import os
from typing import List, Optional
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # OpenAI
    openai_api_key: str
    openai_model_chat: str = "gpt-4o-mini"
    openai_model_embed: str = "text-embedding-3-small"
    
    # LOCAL Database (chat/search) - DATABASE_URL takes priority
    database_url: Optional[str] = Field(default=None, description="Local Postgres DSN")
    
    # ANALYTICS Database (AWS - has companies table)
    # Uses DB_* environment variables
    db_host: Optional[str] = Field(default=None, alias="DB_HOST")
    db_port: Optional[str] = Field(default="5432", alias="DB_PORT")
    db_name: Optional[str] = Field(default=None, alias="DB_NAME")
    db_user: Optional[str] = Field(default=None, alias="DB_USER")
    db_password: Optional[str] = Field(default=None, alias="DB_PASSWORD")
    db_sslmode: Optional[str] = Field(default="require", alias="DB_SSLMODE")
    
    # CORS
    cors_origins: List[str] = ["http://localhost:5173"]
    
    # App settings
    max_llm_chars_body_preview: int = 1500
    max_llm_chars_snippet: int = 500
    default_limit: int = 12
    vector_dim: int = 1536
    
    model_config = ConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )
    
    def get_database_url(self) -> str:
        """
        Returns the LOCAL database URL (for chat/search).
        Uses DATABASE_URL if set, otherwise falls back to DB_* vars.
        """
        if self.database_url:
            return self.database_url
        
        # Fall back to DB_* if DATABASE_URL not set
        return self.get_analytics_database_url()
    
    def get_analytics_database_url(self) -> str:
        """
        Returns the ANALYTICS database URL (AWS with companies table).
        Always uses DB_* environment variables.
        """
        if not all([self.db_host, self.db_name, self.db_user, self.db_password]):
            raise ValueError(
                "Analytics database configuration missing. Set: "
                "DB_HOST, DB_NAME, DB_USER, DB_PASSWORD"
            )
        
        sslmode = f"?sslmode={self.db_sslmode}" if self.db_sslmode else ""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}{sslmode}"


# Singleton instance
settings = Settings()
