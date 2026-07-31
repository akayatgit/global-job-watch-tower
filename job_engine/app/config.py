from pathlib import Path

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql+psycopg2://jobengine:jobengine@127.0.0.1:5433/jobengine',
)
REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')

# Scraping behavior (locked pilot defaults)
SECTOR = os.getenv('SECTOR', 'software')
TIME_FILTER = 'r86400'  # always past 24 hours
# Pause between pages (after the per-page human dwell). Keep human-scale.
MIN_DELAY_S = float(os.getenv('MIN_DELAY_S', '8'))
MAX_DELAY_S = float(os.getenv('MAX_DELAY_S', '22'))
MAX_PAGES = int(os.getenv('MAX_PAGES', '10'))
PAGE_SIZE = 25  # LinkedIn jobs per page

# How long to "act human" on each results page before scraping it (seconds).
# Mimics a real reader: scrolling, hovering, pausing — then back to the top.
# Floor enforced in scraper so a bad .env cannot freeze-idle at 0s.
PAGE_DWELL_MIN_S = float(os.getenv('PAGE_DWELL_MIN_S', '75'))
PAGE_DWELL_MAX_S = float(os.getenv('PAGE_DWELL_MAX_S', '105'))

# Chrome profiles
CHROME_SOURCE_PROFILE = Path(os.getenv('CHROME_SOURCE_PROFILE', str(Path.home() / '.config' / 'google-chrome')))
CHROME_BOT_PROFILE = Path(os.getenv('CHROME_BOT_PROFILE', str(Path.home() / '.config' / 'google-chrome-linkedin')))

HEADLESS = os.getenv('HEADLESS', 'false').lower() == 'true'

# Local Ollama model used to filter irrelevant job titles
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen3.5:9b')
# Thinking mode is slow (can take many minutes per batch). Default OFF for
# reliable throughput; set true only when debugging filter quality.
OLLAMA_THINK = os.getenv('OLLAMA_THINK', 'false').lower() == 'true'
OLLAMA_TIMEOUT_S = float(os.getenv('OLLAMA_TIMEOUT_S', '90'))
# keyword = cool/fast (no GPU). ollama = quality when NVIDIA is healthy.
RELEVANCE_MODE = os.getenv('RELEVANCE_MODE', 'keyword').strip().lower()

# Transient page-fetch retries inside one browser session
FETCH_RETRIES = int(os.getenv('FETCH_RETRIES', '2'))

# Runs stuck in "running" longer than this are marked failed (worker crash)
STALE_RUN_MINUTES = int(os.getenv('STALE_RUN_MINUTES', '180'))

# How often Beat scans for due configs / queued one-off runs (seconds)
BEAT_SCAN_INTERVAL_S = int(os.getenv('BEAT_SCAN_INTERVAL_S', '60'))
