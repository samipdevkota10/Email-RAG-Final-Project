# src/ai.py
"""
OpenAI client initialization.
Centralized AI/LLM configuration for the application.
"""
from openai import OpenAI
from src.config import settings

# Singleton OpenAI client
client = OpenAI(api_key=settings.openai_api_key)

