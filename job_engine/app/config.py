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

# Default Hidden (cooler). Visible only when Ashok flips the top-bar toggle.
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'

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

# --- Detail-page enrich — Plan B, discovery-first (2026-08-08) ---
# Search scrapes own the browser lane; per-job detail pages are a lower
# class of work. Modes:
#   off   = no detail pages at all (jobs stay pending, resumable)
#   light = budgeted trickle, only in idle + cool windows (default)
#   full  = legacy behavior (post-run bursts + 10-min backfill)
# Default 'full' since the MNC-first pivot (Ashok, 2026-08-14): collection
# is focused on watched giants, so every job affords a detail-page visit.
DETAIL_ENRICH_MODE = os.getenv('DETAIL_ENRICH_MODE', 'full').strip().lower()
# Max detail pages fetched per UTC day in light mode (~35-45 min of lane)
DETAIL_BUDGET_PER_DAY = int(os.getenv('DETAIL_BUDGET_PER_DAY', '60'))
# Jobs per trickle batch — small so a mistimed batch delays a search by
# minutes, never a half-hour burst
DETAIL_BATCH_SIZE = int(os.getenv('DETAIL_BATCH_SIZE', '6'))
# Trickle never starts when any search is due within this look-ahead
DETAIL_IDLE_LOOKAHEAD_MIN = int(os.getenv('DETAIL_IDLE_LOOKAHEAD_MIN', '15'))

# AI reading of stored job descriptions (app/ai_requirements.py): Ollama
# reports employer experience statements, grounded by verbatim quotes.
# 'on' (default) or 'off'. Costs no browser time; respects thermal gates.
AI_REQUIREMENTS_MODE = os.getenv('AI_REQUIREMENTS_MODE', 'on').strip().lower()

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
# Longer Warm/Hot rests keep Ollama (Plan A) and cut Plan B flapping on the P16.
HEAT_BREAK_COOL_S = float(os.getenv('HEAT_BREAK_COOL_S', '12'))
HEAT_BREAK_WARM_S = float(os.getenv('HEAT_BREAK_WARM_S', '55'))
HEAT_BREAK_HOT_S = float(os.getenv('HEAT_BREAK_HOT_S', '120'))
HEAT_BREAK_CRITICAL_S = float(os.getenv('HEAT_BREAK_CRITICAL_S', '180'))
# Within this many °C of critical → rest like critical while Plan A still open.
HEAT_PREEMPT_MARGIN_C = float(os.getenv('HEAT_PREEMPT_MARGIN_C', '4'))
# Extra cool-down rounds before keyword Plan B (prefer wait over corrupt data).
HEAT_COOLDOWN_RETRIES = int(os.getenv('HEAT_COOLDOWN_RETRIES', '3'))
HEAT_REQUIRE_GPU = os.getenv('HEAT_REQUIRE_GPU', 'true').lower() == 'true'
OLLAMA_BATCH_SIZE = int(os.getenv('OLLAMA_BATCH_SIZE', '8'))

# --- Prompt Tower pivot (Ashok, 2026-09-09: "Jobs are now prompts") ---
# TOWER_MODE decides who owns the browser lane + Ollama:
#   prompts = daily video-prompt collection/scoring; job scrapes are asleep
#   jobs    = legacy LinkedIn collection (kept, never deleted)
TOWER_MODE = os.getenv('TOWER_MODE', 'prompts').strip().lower()
# UTC hour:minute the daily prompt pipeline runs (03:30 UTC = 09:00 IST)
PROMPT_PIPELINE_UTC_HOUR = int(os.getenv('PROMPT_PIPELINE_UTC_HOUR', '3'))
PROMPT_PIPELINE_UTC_MINUTE = int(os.getenv('PROMPT_PIPELINE_UTC_MINUTE', '30'))
# Explicit ffmpeg binary for the reel composer. Empty = hunt the machine
# (PATH, conda envs, imageio-ffmpeg, Playwright…) then fall back to PyAV /
# OpenCV — see app/prompts/reel_engines.py.
REEL_FFMPEG = os.getenv('REEL_FFMPEG', '').strip()
# Comma-separated subreddits whose new posts are read as prompt sources
PROMPT_REDDIT_SUBS = os.getenv(
    'PROMPT_REDDIT_SUBS',
    'aivideo,PromptEngineering,VeoAI,KlingAI,Sora,runwayml,AIVideoPrompts',
).strip()
# Seconds between subreddit fetches — seven subs in a two-second burst earned
# HTTP 429 from Reddit on 2026-09-10.
PROMPT_REDDIT_PAUSE_S = float(os.getenv('PROMPT_REDDIT_PAUSE_S', '8'))
# Comma-separated public web pages to mine (prompt blogs, galleries).
# Default = public D2C ad-prompt handbooks (product-focused first) so the
# first Scan now is not empty when Reddit JSON is 403-blocked (2026-09-10).
_DEFAULT_PROMPT_WEB_URLS = (
    'https://raw.githubusercontent.com/LichAmnesia/awesome-ad-video-prompts/main/README.md,'
    'https://prompt-architects.com/blog/21-veo3-prompt-structure,'
    'https://www.veo3ai.io/blog/veo-3-product-ads-video-generator-2026,'
    'https://ugcvids.ai/blog/how-to-write-veo-3-1-prompts-for-product-ads,'
    'https://raw.githubusercontent.com/cclank/lanshu-awesome-ai-video-kit/main/prompts/kling/README.md,'
    'https://raw.githubusercontent.com/cclank/lanshu-awesome-ai-video-kit/main/prompts/veo/README.md'
)
# Blank env (PROMPT_WEB_URLS=) must not wipe the default — ThinkPad .env
# often sets the key empty, which would otherwise override the fallback.
_raw_prompt_web_urls = os.getenv('PROMPT_WEB_URLS')
PROMPT_WEB_URLS = (
    _raw_prompt_web_urls.strip()
    if _raw_prompt_web_urls and _raw_prompt_web_urls.strip()
    else _DEFAULT_PROMPT_WEB_URLS
)
# Comma-separated Instagram hashtags (no #) — needs the logged-in Chrome
# profile; empty = Instagram source off
PROMPT_INSTAGRAM_TAGS = os.getenv('PROMPT_INSTAGRAM_TAGS', '').strip()
# Max candidates fetched per source per run (keeps Ollama load bounded)
PROMPT_SOURCE_LIMIT = int(os.getenv('PROMPT_SOURCE_LIMIT', '40'))
PROMPT_SHORTLIST_SIZE = int(os.getenv('PROMPT_SHORTLIST_SIZE', '10'))
# Minimum final score to be eligible for the daily top-10
PROMPT_MIN_SCORE = float(os.getenv('PROMPT_MIN_SCORE', '55'))
# Ollama embedding model for the prompt RAG (dedupe + exemplar retrieval)
PROMPT_EMBED_MODEL = os.getenv('PROMPT_EMBED_MODEL', 'nomic-embed-text').strip()
# Replicate video model (image → video). Must include :version when the
# model requires it; bare owner/name works for official models.
REPLICATE_VIDEO_MODEL = os.getenv('REPLICATE_VIDEO_MODEL', 'kwaivgi/kling-v2.1').strip()
PROMPT_VIDEO_DURATION_S = int(os.getenv('PROMPT_VIDEO_DURATION_S', '10'))
# How long the worker waits for the video model before cancelling the
# prediction (a 10 s Kling 1080p render takes minutes; the Telegram watcher
# waits 20 min).
PROMPT_VIDEO_TIMEOUT_S = int(os.getenv('PROMPT_VIDEO_TIMEOUT_S', '900'))
# Reverse prompt (2026-09-10): the vision model that watches a downloaded
# Instagram / Pinterest clip and writes the timestamped prompt. Replicate
# google/gemini-* take `prompt`, `videos[]`, `system_instruction`.
REPLICATE_VISION_MODEL = os.getenv('REPLICATE_VISION_MODEL', 'google/gemini-2.5-flash').strip()
# Reverse-prompt file path: Astra / Fable get the mp4 (native video if the
# API accepts it, otherwise the file in their code sandbox — same as Codex).
PROMPT_REVERSE_ASTRA_MODEL = os.getenv('PROMPT_REVERSE_ASTRA_MODEL', 'gpt-6-astra').strip()
PROMPT_REVERSE_FABLE_MODEL = os.getenv('PROMPT_REVERSE_FABLE_MODEL', 'claude-fable-5').strip()
# The exemplar prompt the model is shown as the quality bar (Ashok's "best
# prompt on the internet"). Empty = the bundled default next to the module.
PROMPT_REVERSE_EXEMPLAR_PATH = os.getenv('PROMPT_REVERSE_EXEMPLAR_PATH', '').strip()
# Largest source clip we download / accept (Telegram uploads are ≤20 MB)
PROMPT_REVERSE_MAX_VIDEO_MB = int(os.getenv('PROMPT_REVERSE_MAX_VIDEO_MB', '80'))
# Where rendered prompt videos / cards / product images live — same asset
# root AvatarPitch reads from, served by /api/partner/v1/assets/{key}
PROMPT_ASSET_PREFIX = os.getenv('PROMPT_ASSET_PREFIX', 'prompts').strip().strip('/')

# Partner API (/api/partner/v1/ — AvatarPitch integration, 2026-08-14).
# Static bearer token; AvatarPitch (Vercel) calls over the Cloudflare
# tunnel. Unset = the partner surface answers 503 (disabled by default).
PARTNER_API_TOKEN = os.getenv('PARTNER_API_TOKEN', '').strip()
# Asset storage root (PUT/GET /api/partner/v1/assets/{key}) — created by
# scripts/setup_avatarpitch_host.sh; 48h GC timer owns retention.
PARTNER_ASSETS_DIR = os.getenv('PARTNER_ASSETS_DIR', '/srv/avatarpitch/uploads').strip()
# Public base used in upload responses' url field (the tunnel hostname).
PARTNER_PUBLIC_BASE_URL = os.getenv(
    'PARTNER_PUBLIC_BASE_URL', 'https://tower.jobmaster.agency',
).strip()

# Replicate — Telegram image chat + Carousel (Gate 1)
# Must include :version hash (bare owner/name returns "No adapter found").
REPLICATE_API_TOKEN = os.getenv('REPLICATE_API_TOKEN', '').strip()
REPLICATE_MODEL = os.getenv(
    'REPLICATE_MODEL',
    'google/nano-banana-2:d1be8b5fc0931a253d417e12a484ac01ee9ccbc6daffd4792151377d5e5ff55f',
).strip()

# DIRECTOR — OpenAI Agents SDK brain above Hermes (COURIER)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
OPENAI_BRAIN_MODEL = os.getenv('OPENAI_BRAIN_MODEL', 'gpt-4.1-mini').strip()
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '').strip()
DIRECTOR_SESSION_DB = Path(
    os.getenv(
        'DIRECTOR_SESSION_DB',
        str(BASE_DIR / '.data' / 'director_sessions' / 'director.db'),
    )
)
