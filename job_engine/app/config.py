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

# Title-relevance filter only — keep SMALL (title match, not deep reasoning).
# Locked default: qwen3.5:4b (not 9b/27b — cooler + faster for this job).
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen3.5:4b')
# Thinking mode is slow (can take many minutes per batch). Default OFF for
# reliable throughput; set true only when debugging filter quality.
OLLAMA_THINK = os.getenv('OLLAMA_THINK', 'false').lower() == 'true'
OLLAMA_TIMEOUT_S = float(os.getenv('OLLAMA_TIMEOUT_S', '45'))
# ollama = quality path (default). keyword = Plan B ONLY for critical heat /
# missing GPU — never normal ops (keyword corrupts relevance data).
# auto = same as ollama (legacy alias).
RELEVANCE_MODE = os.getenv('RELEVANCE_MODE', 'ollama').strip().lower()

# Transient page-fetch retries inside one browser session
FETCH_RETRIES = int(os.getenv('FETCH_RETRIES', '2'))

# Runs stuck in "running" longer than this are marked failed (worker crash)
STALE_RUN_MINUTES = int(os.getenv('STALE_RUN_MINUTES', '45'))

# How often Beat scans for due configs / queued one-off runs (seconds).
# Warm/hot host stretches this so new scrapes don't stack heat.
BEAT_SCAN_INTERVAL_S = int(os.getenv('BEAT_SCAN_INTERVAL_S', '90'))
BEAT_SCAN_WARM_S = int(os.getenv('BEAT_SCAN_WARM_S', '180'))
BEAT_SCAN_HOT_S = int(os.getenv('BEAT_SCAN_HOT_S', '300'))

# --- Thermal governor (ThinkPad P16 / RTX A3000) ---
HEAT_COOL_MAX_C = float(os.getenv('HEAT_COOL_MAX_C', '65'))
HEAT_WARM_MAX_C = float(os.getenv('HEAT_WARM_MAX_C', '75'))
HEAT_HOT_MAX_C = float(os.getenv('HEAT_HOT_MAX_C', '85'))
HEAT_WARM_LOAD = float(os.getenv('HEAT_WARM_LOAD', '4'))
HEAT_HOT_LOAD = float(os.getenv('HEAT_HOT_LOAD', '7'))
HEAT_CRITICAL_LOAD = float(os.getenv('HEAT_CRITICAL_LOAD', '10'))
HEAT_BREAK_COOL_S = float(os.getenv('HEAT_BREAK_COOL_S', '8'))
HEAT_BREAK_WARM_S = float(os.getenv('HEAT_BREAK_WARM_S', '25'))
HEAT_BREAK_HOT_S = float(os.getenv('HEAT_BREAK_HOT_S', '60'))
HEAT_BREAK_CRITICAL_S = float(os.getenv('HEAT_BREAK_CRITICAL_S', '120'))
HEAT_REQUIRE_GPU = os.getenv('HEAT_REQUIRE_GPU', 'true').lower() == 'true'
OLLAMA_BATCH_SIZE = int(os.getenv('OLLAMA_BATCH_SIZE', '10'))
