import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from a .env file (if present; in Docker the env
# is usually injected via docker-compose, so a missing file is fine).
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

# Base directories
BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMP_DIR = os.path.join(BASE_DIR, "temp")

# Where the wiki vault's raw/ folder is reachable from inside this process.
# In Docker this is the mount target (see docker-compose.yml); locally it can
# point straight at the vault on disk. Reels are written as raw source docs here.
VAULT_RAW_DIR = os.getenv("VAULT_RAW_DIR", "/vault/raw")
INSTAGRAM_SUBDIR = os.getenv("INSTAGRAM_SUBDIR", "instagram")

# API settings
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", 8000))

# Transcription settings
WHISPER_MODE = os.getenv("WHISPER_MODE", "LOCAL")          # LOCAL (faster-whisper) or API (OpenAI)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")         # tiny / base / small / medium / large-v3
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")  # int8 is fast & light on CPU
OPENAI_API_KEY = os.getenv("WHISPER_API_KEY")             # only needed when WHISPER_MODE=API

# Source-specific settings
# OCR on-screen text for YouTube too (off by default: long videos, low value)
YOUTUBE_OCR = os.getenv("YOUTUBE_OCR", "false").lower() == "true"

# Make sure temp directory exists
os.makedirs(TEMP_DIR, exist_ok=True)
