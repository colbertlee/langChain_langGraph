import os
from dotenv import load_dotenv
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")
MODEL_NAME = "gpt-4o-mini"
MAX_HISTORY_LENGTH = 10
TEMPERATURE = 0.7
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL_TYPE = os.getenv("EMBEDDING_MODEL_TYPE", "openai")