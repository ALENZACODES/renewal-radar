"""Configuration that never exposes API credentials to browser clients."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv('DATABASE_URL','sqlite:///./renewal_radar.db')
    nebius_api_key: str = os.getenv('NEBIUS_API_KEY','')
    nebius_model: str = os.getenv('NEBIUS_MODEL','nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B')
    nebius_base_url: str = os.getenv('NEBIUS_BASE_URL','https://api.tokenfactory.nebius.com/v1')
    tavily_api_key: str = os.getenv('TAVILY_API_KEY','')
    allowed_origins: tuple[str,...] = tuple(s.strip() for s in os.getenv('ALLOWED_ORIGINS','http://localhost:8000,http://127.0.0.1:8000').split(','))
    app_env: str = os.getenv('APP_ENV','development')
    max_pdf_bytes: int = int(os.getenv('MAX_PDF_MB','8')) * 1024 * 1024

settings = Settings()
