# Prompt Tower — "Jobs are now prompts" (pivot 2026-09-09)

| Field | Value |
|---|---|
| **Ruling** | Ashok, 2026-09-09: *"Jobs are now prompts. Do what I say. We don't need jobs."* |
| **Product** | Daily top-10 **AI video prompts for D2C product videos** (Veo / Kling / Sora), scored by Hermes, posted on Instagram for authority, sold later as prompt + video packs |
| **Authority channel** | Instagram, cinematic 9:16 reel: owner-typed header → 9:16 clip · storyboard · scrolling prompt → hardcoded `Comment “AI” to get / all the prompts` |
| **Owner surface** | **VIGIL admin** at `http://127.0.0.1:8001` is the collection cockpit (Tower · Prompts · Scores · Sources · Activity · Live · Health). Telegram is delivery + approve-to-video, not the monitor. |

| **Learning loop** | RAG of proven winners (rated ≥4 or strong engagement) → few-shot anchors + baseline for tomorrow's scoring → outliers flagged 🔥 |
| **Two workflows (Ashok 2026-09-10)** | **prompt to video** — daily top-10 → Telegram ✅ + product photo → Kling → reel. **reverse prompt** — `/igtovid` · `/pintovid` → Instagram / Pinterest URL (or forwarded video) → **header title** → Gemini writes a timestamped prompt → **the same cinematic reel**. |
| **Render** | Replicate image→video (`REPLICATE_VIDEO_MODEL`, default `kwaivgi/kling-v2.1`) → MP4 + Instagram card stored in the AvatarPitch asset root, served at `/api/partner/v1/assets/{key}` (play) and `?download=1` (Save As — Telegram **⬇️ Save clip**) |
| **Jobs stack** | **Asleep, not deleted.** `TOWER_MODE=prompts` (default) pauses the job beat; `TOWER_MODE=jobs` wakes it. Every job table, search, command and test stays intact (source-safety law). |
| **Code** | `job_engine/app/prompts/` · `app/api/prompts.py` · `app/telegram_prompts.py` · tasks in `app/tasks.py` · migration `b7c3e9a12d45` |

---

## 1. Why this shape (Akay's assessment, accepted by Ashok)

- Standalone prompts sell for $1.99–$4.99 on PromptBase (new sellers capped at $4.99) — no moat, copy-once.
- D2C founders pay for the **video** (Koro ₹999/mo, UGCad $0.79/render). The prompt is our engine; the finished video + card is the SKU.
- Authority first: a daily Instagram post in the reference format builds the audience that later buys prompt+video packs.
- Ashok's ordering: **Instagram authority → daily top-10 via Hermes scoring → rank + RAG learning → Telegram button flow → AI video through AvatarPitch assets.**

## 2. Daily pipeline (Celery beat, 03:30 UTC = 09:00 IST + idle kick)

The crontab still fires at 09:00 IST. If the catalogue is **empty** or the last catch is **older than 6 hours**, the 90-second beat also kicks one scan (Redis lock, 25-minute retry after a zero result) so a deploy does not sit at 0 prompts until tomorrow. **Scan now** is the same pipeline.

```
sources ──► normalize/dedupe ──► RAG embed ──► Hermes score ──► top-10 ──► Telegram deck
 reddit       is_prompt?          near-dup?      detail+flow      🔥 outliers   (owner, once/day)
 web/promptbase  fingerprint      exemplars      + heuristic      per-source cap
 instagram*   heuristic 0–100     baseline μ/σ   blend 35/65      min score 55
 manual (/addprompt)
```

| Step | Module | Law |
|---|---|---|
| Collect | `app/prompts/sources.py` | Every candidate carries `source`, `source_url`, `author`. Sources are independent; one failing never blocks the rest. Instagram runs through the logged-in stealth Chrome and is **off unless `PROMPT_INSTAGRAM_TAGS` is set** (Instagram is hostile to scraping). |
| Normalize | `app/prompts/normalize.py` | Deterministic: a prompt must be ≥180 chars, touch ≥3 vocabulary families, include camera-or-lighting **and a product** (a category or a whole-word product noun — `can` inside "candle" and `ad` inside "shadow" no longer count; samurai/eagle/stadium scenes are out, 2026-09-10). Rejected outright: fill-in templates (>2 `[slots]`; `[brand]` alone is fine), non-English index pages (CJK >15 %), and **explainer prose about prompting** (FAQ / "use this when" / "0-2s: Hook —" outlines, or ≥2 reader-facing words such as *guide, because, if you, usually, examples*; constraint words like *should/avoid* and product words like *model/notes* are deliberately not counted). Markdown chrome (headings, nav links, tag lines, tables) is stripped first. Heuristic 0–100 from literal structure (families, length, numbers, sentence flow). Category (perfume, skincare, beverage…) and model hint (veo/kling/sora…) from literal words only. |
| Re-audit | `pipeline.reaudit_stored` | Every scan re-reads unrated, unposted rows against the current gate; rows that no longer pass are marked `rejected`, pulled from their shortlist, and that day's top-10 is rebuilt. Rated, posted, or exemplar rows are never touched. |
| RAG | `app/prompts/rag.py` | Ollama embeddings (`PROMPT_EMBED_MODEL`, fallback hashed bag-of-words). Near-duplicate ≥0.93 cosine is not stored twice. Exemplars = winners nearest the candidate (k=3). Baseline = mean/std of winners' final scores; **outlier = > mean + 1σ (σ floor 5)**. |
| Score | `app/prompts/scoring.py` | Hermes (local Ollama `OLLAMA_MODEL`) grades **DETAIL** and **FLOW** 0–100 relative to the exemplars; reply validated strictly (types, ranges, ≤4 short reasons). **Final = 0.35·heuristic + 0.65·AI**; without an AI grade the heuristic stands alone **capped at 70** so an unjudged prompt never tops a judged one. Respects heat gates (`thermal.ollama_path_open`). |
| Shortlist | `app/prompts/pipeline.py::build_shortlist` | Top `PROMPT_SHORTLIST_SIZE` (10) with `final_score ≥ PROMPT_MIN_SCORE` (55), collected in the last 48h, outliers first. Diversity pass: **≤3 per origin** — a subreddit or a web page's host (`prompt_origin`), manual exempt — so one page cannot own the day; then a **fill pass** tops the deck up from the best leftovers so a thin day is never a 3-row "top 10" (2026-09-10: keyed on `source='web'`, six handbooks counted as one and the deck stalled at 3). Idempotent per UTC day; `force` rebuilds. |
| Learn | `pipeline.record_rating / record_performance` → `rag.promote_winners` | ⭐≥4 **or** performance ≥24 pts (≈1,000 weighted interactions: likes + 3·comments + 4·saves + 4·shares + views/100 on a log scale) ⇒ exemplar. Winners feed tomorrow's anchors and baseline. |

## 3. Telegram deck (owner-only)

| Command / tap | What happens |
|---|---|
| `/prompts [YYYY-MM-DD]` | Top-10 list: `rank. score/100 🔥 — title · category · model — source ⭐rating`; number buttons 1–10, `🔄 Scan now`, `📊 Stats`. Auto-delivered **once per UTC day** the moment the beat's shortlist exists (bot-side loop, 10-min check). |
| tap `N` (`pt:sel:<id>`) | Full prompt verbatim + Detail/Flow/Structure/baseline + Hermes reasons + source URL. Buttons: `📸 Send product image → video`, `⭐1…5`, `📣 Posted on Instagram`, `◂ Top 10`. |
| `📸` (`pt:img:<id>`) | Bot waits for a photo. Owner sends a photo **with no caption** → poll loop stashes the `file_id` and queues the synthetic `pt:photo` tap. |
| `pt:photo` | "Prompt #N + your product photo are paired" → `✅ Make video` / `✖ Cancel`. |
| `✅` (`pt:go:<id>`) | Bot downloads the photo (Bot API `getFile`), POSTs base64 to `/api/prompts/{id}/render`. Tower stores the product image, renders the **preview card** immediately (Pillow), queues the Celery video render. The worker gets the AI clip from Replicate, then **composes the reel** (§3a) — the post asset. A watcher thread polls `/api/prompts/renders/{rid}` (15 s, max 20 min), uploads the preview card, then the **reel MP4** ("reel ready, post this", raw-clip link in the caption). If the reel could not be composed (e.g. ffmpeg missing) the raw clip is sent with the reason — a finished video is never hidden. |
| `⭐n` | `/api/prompts/{id}/rate` → winner promotion when n ≥ 4. |
| `📣 Posted` | Marks posted; reply asks for `/promptperf <id> likes=.. comments=.. saves=.. shares=.. views=..`. |
| `/promptperf` | Stores Instagram numbers → performance score → RAG winner when strong. |
| `/addprompt <text>` | Manual ingest (rejects captions), scored right away. |
| `/promptscan` | Runs the daily pipeline now (Celery). |
| `/promptstats` | Prompts, scored/pending, shortlisted today, posted, videos, winners, baseline μ±σ, sources, last catch. |
| `/igtovid` · `/pintovid` [`url`] | **Reverse prompt** (§3b). URL (or forwarded video) then the **header title**. Footer is hardcoded. Forwarding the video file is the fallback when the page is login-walled. |

Guests never see any of it: `pt:` taps and prompt commands are gated on the real owner check; a guest's photo is ignored exactly as before.

### 3a. The reel — the post is a video, not a picture (2026-09-10)

Ashok: "wherever the image is you need to place the video … this entire template should come out as a video … the prompt scrolls … storyboard: six frames in the same aspect ratio next to each other in the other half." `app/prompts/post_reel.py` composes a 1080×1920 MP4 on whatever video engine the machine already has (`app/prompts/reel_engines.py`, no new Python package — the ThinkPad deploy does not `pip install`):

```
TITLE                                 ← owner-typed header (reverse) or prompt title
[ 9:16 clip, rounded ]   STORYBOARD
                         [6 stills, clip aspect]
                         PROMPT
                         scrolling verbatim — starts immediately
Comment “AI” to get                   ← hardcoded footer, glow + shadow
all the prompts
```

Background is one storyboard frame, Gaussian-blurred (radius 64) and darkened — not the old white card. Hero box is **660×1173 (true 9:16, sized like the Snickers reference)**. The full stack (title → hero → footer) is **vertically centered** on the 1080×1920 canvas, with a margin under the title. Title is **Playfair Display** in gold `(236, 201, 64)` — Vogue serif, sampled from Ashok's aesthetic-fonts reference. Footer stays white Inter. Storyboard and prompt sit in white-bordered rounded panels.

- **Storyboard** (right rail, white-bordered 3×2): six stills cover-fitted into a compact grid that fills the panel — the reference's storyboard, not tiny letterboxed portraits.
- **Prompt** (right rail, under the storyboard): the stored prompt **verbatim, never truncated**, rendered as one tall transparent strip. Scroll **starts on frame 1** (no lead-in hold) and finishes with a tiny rest at the end so the last line can land. Short prompts sit still.
- Frame rate = the clip's (capped at 30), duration = the clip's, **audio copied** when the clip has a track (Veo). The engine decodes already cover-fitted to the hero box; Pillow composites; the engine encodes H.264 yuv420p `+faststart` for iPhone playback.
- Stored as `prompts/<day>/reel-<id>-<rand>.mp4` next to the raw clip; `prompt_renders.reel_key / reel_url`. A composition failure sets `reel_error` and keeps the clip — the render is still `done`.
- **Engine hunt (2026-09-10, Ashok away from the ThinkPad: "something for video creation must be there, check properly").** The service PATH has no `ffmpeg` and nobody can install one remotely, so `reel_engines.discover()` looks instead of demanding, in order: (1) an **ffmpeg binary** anywhere plausible — `REEL_FFMPEG`, PATH, the interpreter's own `bin`, `CONDA_PREFIX`, every conda root (`anaconda3 / miniconda3 / miniforge3 / mambaforge`: `bin`, `envs/*/bin`, `pkgs/ffmpeg-*/bin`), imageio-ffmpeg's bundled static binary in any env / `~/.local` / pipx venv / `~/.hermes` venv, `~/.imageio`, Playwright's download, `~/bin`, `~/ffmpeg*`, `~/Downloads/ffmpeg*`, `/usr/local/bin`, `/snap/bin`, `/opt/conda/bin` — each candidate is **verified** (`-decoders` must list `h264`, `-encoders` must list `libx264` / `libopenh264` / `mpeg4`; Playwright's stripped build is rejected with the reason). No `ffprobe` next to it? The clip is probed from `ffmpeg -i` output. (2) **PyAV** (`av`) — ffmpeg's libraries linked into Python, libx264 in-process, audio packets copied. (3) **OpenCV** (`cv2`) — decodes anything, writes MPEG-4 **without audio**, the last resort so a finished clip is never left without its reel. The result is cached (a failed hunt retries every 10 min, so a later install is picked up without a restart).
- **Readable from the phone:** `GET /api/prompts/stats` → `reel_engine` (`engine` ffmpeg|pyav|opencv|none, path, version, codec, audio, every location `searched`, each `rejected` path with its reason, python libs, fix hint) plus `reels_done` / `reels_failed`; `/promptstats` prints one line ("Reels 3 · failed 0 · engine ffmpeg (libx264) at …" or "⚠️ no video engine — 14 ffmpeg spot(s) checked, av/cv2 absent · fix: sudo apt install -y ffmpeg"). The worker console says which engine composed each reel; `reel_error` carries the full hunt summary when none exists. Deploy runs `python -m app.prompts.reel_engines` in the `ai` env and logs `reel engine — …` (a `WARNING:` line when none).

### 3b. Reverse prompt — a best-performing post → the prompt behind it (2026-09-10)

Ashok: "/igtovid or /pintovid … ask for the Instagram or Pinterest url, download the video, take 6 frames, pass the video to Gemini to get a timestamp-based prompt … place the video, the prompt and the screenshots as storyboard frames in the same final template." This is the high-value path: reverse the prompt from a post that already performed, then re-post it.

```
URL or forwarded clip
  → fetch_video (HTTP + stealth Chrome + ffmpeg HLS)
  → store source MP4
  → Gemini on Replicate (google/gemini-2.5-flash) watches the clip
  → keyword + timestamped prompt (verbatim) + `cuts` array
  → strip `cuts` from the stored prompt · grab ~14 JPEGs at those times
  → second pass: same video + ≤10 of those JPEGs → rewrite the prompt so each timestamp matches the JPEG
  → post_reel.compose_reel (same template as prompt-to-video)
  → Telegram: reel → attended prompt → downloadable cut-reference frames → **💥✏️ Twist**
  → magic pencil: Gemini rewrites every beat · Gemini 3 Pro Image (nano-banana-pro) identity-lock edit on each still
  → Telegram: twisted prompt + twisted cut frames
```

| Step | Law |
|---|---|
| Intake | `/igtovid` · `/pintovid` · `/pintovideo` · `/reverseprompt`. URL (or forwarded video) then **header title** then **magic-pencil twist** (one line, or Skip) then **model buttons** (Gemini · GPT-6 Astra · Claude Fable 5). Footer is hardcoded. A stray direct `.mp4` in chat does **not** start a run unless he already typed the command. Cancel clears the wait. |
| Download | `app/prompts/reverse_prompt.py::fetch_video`. Plain HTTP with a Safari UA first (Pinterest pages often carry the mp4 in JSON). Instagram login walls fall through to the logged-in stealth Chrome profile (`sources.browser_fetch`, **90s timeout** — reverse #14 hung here with no Gemini call). HLS playlists are stitched by ffmpeg (copy, then H.264 transcode if copy fails). After store, **remux HEVC/VP9 → H.264** so Gemini can read Pinterest pins (reverse #16 died with Google E001 on the raw file). Cap `PROMPT_REVERSE_MAX_VIDEO_MB` (80). Telegram forwarded files are ≤20 MB — larger clips must arrive as a link. A deploy purge can drop the Celery job: worker start re-queues unfinished reverses; Telegram announces queued/downloading and has **Retry**. |
| Describe | After the title, Telegram asks **Gemini · GPT-6 Astra · Claude Fable 5**. **Every engine gets the video file** — we never extract stills and call that the reverse (Ashok 2026-09-11: Codex handed Astra the mp4). Gemini via Replicate (`REPLICATE_VISION_MODEL`) watches the **public `.mp4` asset URL** (Replicate fetches it — no multi-MB data-URI upload). Data-URI is the fallback when the URL cannot be fetched, or on Google **E001** after an H.264 remux. GPT-6 Astra (`gpt-6-astra`, `OPENAI_API_KEY`) tries native `input_video` / `input_file`, then Files API + `code_interpreter` with the mp4 in the container. Claude Fable 5 (`claude-fable-5`, `ANTHROPIC_API_KEY`) tries a native video block, then Files API + `container_upload` + code execution. Same system instruction + exemplar + JSON salvage/retry. JSON is `keyword` + `prompt` + `cuts` (hard-cut start/end seconds). **`cuts` is stripped before storage** — the prompt Ashok copies never contains the array. Missing keys refuse that button and keep the other two. Stored as `vision_engine` (`gemini \| astra \| fable`); `model` is the API id that wrote the prompt. **This is the one place an AI authors a prompt** — first pass is video-only; a second pass may rewrite it against the cut-reference JPEGs (below). After that, stored and shown verbatim, never shipped half-finished. Failures say **Gemini**, never Kling's "video model failed" costume. |
| Recreate frames | After the first-pass prompt, grab **~14 JPEGs from the downloaded clip at cut timestamps** (start + end of each shot; interiors of the longest cuts if fewer than 14; never an equal-interval grid). Not the 6-frame reel storyboard. **Those JPEGs go back to the same vision model** with the video (Gemini `images[]`, max 10 — first + last cut plus a spread; Astra/Fable get the same stills after the mp4). The rewrite must match product pose, crop, lighting, camera, set, glass/liquid/hand at each labeled time. Failure or a much shorter rewrite keeps the draft. Frames are **not** re-extracted after refine, so Telegram files stay aligned with the stored prompt. Telegram sends them as **downloadable documents** (`sendDocument`, filenames `cut-01-0.00s.jpg`) so Ashok can attach them with the prompt and recreate the clip. Stored as `ref_frames` JSON (migration `a3c9e1b72d04`). A grab failure keeps the prompt (`ref_error`); the row is still `done`. |
| Reel | Same composer, same 6 storyboard frames from **the source clip**, prompt scrolls verbatim. Keys `prompts/<day>/rreel-<id>-….mp4`. A reel failure keeps the clip + prompt (`reel_error`); the row is still `done`. |
| Catalogue | Best-effort ingest through the existing `read_prompt` gate (`source='reverse'`) **after** the cut-frame refine, so the catalogue gets the attended prompt. Rejection is fine — the reverse row still holds the text. |
| Magic pencil | After the original prompt + 14 stills land, Telegram shows **💥✏️ Twist**. That is our touch on the recreation — not a caption. Gemini (text-only second call) rewrites **every** timestamped beat: timing, emotion, context, imagination. Then each cut JPEG goes through **text+image→image** on **Gemini 3 Pro Image** (`PROMPT_TWIST_IMAGE_MODEL`, default `google/nano-banana-pro`, 2K): pose, lighting, details and identity stay locked — only the twist is applied; the frame is not restaged. (Older Flash nano-banana-2 was hitty quality.) Original prompt and original frames stay. Delivery: twisted prompt + `twist-01-0.00s.jpg` documents. Stored as `twist_text` / `twist_prompt` / `twist_frames` (migration `b4e7c1a90d28`). Skip at intake still leaves the button; tapping it asks for the line if none was stored. |

Owner-only. Guests never see these commands.

## 4. API

Owner surface (local tower, `/api/prompts`):

| Route | Purpose |
|---|---|
| `GET /today?day=&full=1` | Day's shortlist (rank, scores, provenance; `full=1` = whole text) |
| `GET /stats` | Tower numbers + winners baseline + `reels_done` / `reels_failed` + `reel_engine` (which video engine this machine composes with, everywhere it looked) |
| `GET /{id}` | One prompt, full text |
| `POST /scan {force, inline}` | Run the pipeline (Celery by default; `inline` for dev/tests) |
| `POST /ingest {text, author, source_url}` | Manual add + immediate score (422 when it isn't a prompt) |
| `POST /{id}/rate {rating 1–5}` · `POST /{id}/performance {likes…}` · `POST /{id}/posted` | Feedback → RAG |
| `POST /{id}/render {image_base64, chat_id, content_type}` | Store image, render card, queue video → render row |
| `GET /renders/{id}` | `queued | running | done | failed`, `video_url` (raw clip), `reel_url` (post asset) or `reel_error`, `card_image_url` (preview) |
| `POST /reverse {source_url \| video_base64, chat_id, title, vision_engine, twist}` | Queue a reverse-prompt run (`vision_engine`: gemini · astra · fable). Optional `twist` is the magic-pencil line. Must stay registered **before** `GET /{id}` |
| `POST /reverse/{id}/twist {twist}` | Queue the magic-pencil pass on a finished reverse |
| `GET /reverse` · `GET /reverse/{id}` | Recent rows / one row: `queued \| downloading \| describing \| composing \| done \| failed`, clip + prompt + `ref_frames` + twist + reel |

Partner surface (AvatarPitch, bearer `PARTNER_API_TOKEN`): **`GET /api/partner/v1/prompts?day=`** — the day's top-10 with full text, scores, provenance and any finished `video_url` (raw clip) / `reel_url` (post asset) / `card_image_url`. Rows verbatim; the tower owns scoring, AvatarPitch renders/presents.

## 5. Data model (migrations `b7c3e9a12d45` → `d9e5a1c47f02`)

- `video_prompts` — text, fingerprint (unique), source/source_url/author/source_posted_at, model_hint, category, heuristic_score, ai_detail/ai_flow/ai_score/ai_reasons, final_score, baseline_mean/std, is_outlier, embedding (JSON), status (`new | shortlisted | posted | rejected`), rating, performance (JSON), performance_score, posted_at, exemplar.
- `prompt_shortlists` — (day, rank) unique → prompt_id.
- `prompt_renders` — prompt_id, chat_id, product_image_key, card_image_key, video_key, video_url, **reel_key, reel_url, reel_error** (migration `c8d4f0b23e56`), model, status, error, timestamps.
- `reverse_prompts` (migration `d9e5a1c47f02`) — platform (`instagram \| pinterest \| direct \| upload`), source/media URL, stored clip, duration, **header_title**, **vision_engine** (`gemini \| astra \| fable`, migration `f2c4d6e8a910`), **keyword + prompt_text** (verbatim from the chosen model; `cuts` stripped), **ref_frames / ref_error** (migration `a3c9e1b72d04` — ~14 cut-reference JPEGs), **twist_text / twist_prompt / twist_frames / twist_status** (migration `b4e7c1a90d28` — magic pencil), optional `prompt_id` into the catalogue, reel key/url/error, status (`queued \| downloading \| describing \| composing \| done \| failed`).

Guest/alert/broadcast SQLite state is untouched; the deck's pending states live in the same `bot_state` table (`prompt_selected:`, `prompt_await_image:`, `pending_prompt_photo:`, `prompt_await_url:`, `pending_prompt_video:`, `prompt_daily_sent:<day>`).

## 6. Configuration (`job_engine/.env`)

| Key | Default | Meaning |
|---|---|---|
| `TOWER_MODE` | `prompts` | `prompts` = job beat asleep · `jobs` = legacy collection |
| `PROMPT_PIPELINE_UTC_HOUR` / `_MINUTE` | `3` / `30` | Daily run (09:00 IST) |
| `PROMPT_REDDIT_SUBS` | `aivideo,PromptEngineering,VeoAI,KlingAI,Sora,runwayml,AIVideoPrompts` | Public listings. **JSON is 403-blocked** from typical server IPs — collector tries `.json` then falls back to Atom `.rss`. A 403 switches the rest of the run to RSS only; a **429** stops touching Reddit for that run (remaining subs reported as *skipped*, not failed). |
| `REEL_FFMPEG` | empty | Explicit ffmpeg binary for the reel composer. Empty = hunt the machine (PATH, conda envs, imageio-ffmpeg, Playwright…), then PyAV, then OpenCV (§3a). |
| `PROMPT_REDDIT_PAUSE_S` | `8` | Seconds between subreddit fetches (+ a ≤3 s breather before an RSS retry). Seven subs in a two-second burst earned HTTP 429 on 2026-09-10. |
| `PROMPT_WEB_URLS` | Six D2C ad-prompt handbooks: LichAmnesia *awesome-ad-video-prompts*, prompt-architects Veo 3 structure, veo3ai.io product-ads guide, ugcvids.ai Veo 3.1 product ads, cclank Kling + Veo READMEs | Public pages to mine (product-focused first). Blank `PROMPT_WEB_URLS=` in `.env` still uses this default. Probe 2026-09-10: 115 blocks → 75 real prompts kept, 40 prose/TOC/FAQ blocks dropped. |
| `PROMPT_INSTAGRAM_TAGS` | empty (off) | Hashtags via the logged-in stealth Chrome profile |
| `PROMPT_SOURCE_LIMIT` | `40` | Per-source fetch cap |
| `PROMPT_SHORTLIST_SIZE` / `PROMPT_MIN_SCORE` | `10` / `55` | Deck size, eligibility floor |
| `PROMPT_EMBED_MODEL` | `nomic-embed-text` | `ollama pull nomic-embed-text` on the ThinkPad |
| `REPLICATE_VIDEO_MODEL` | `kwaivgi/kling-v2.1` | Also handled: `google/veo-3*`, `bytedance/seedance*`, `minimax/*`, `wan-video/*` |
| `PROMPT_VIDEO_DURATION_S` | `10` | Kling 5/10 · Veo 8 |
| `PROMPT_VIDEO_TIMEOUT_S` | `900` | How long the worker polls the video model before cancelling the prediction. **Why (2026-09-10):** both #29 renders died with `The read operation timed out` — `replicate.Client.run()` sends `Prefer: wait` and holds ONE HTTP call open with a 60.5 s read timeout while the server waits up to 60 s; a 10 s Kling 1080p render takes minutes. `video_creator.replicate_render` now creates the prediction without waiting, polls every 5 s (status changes land in the worker console: `starting → processing`), tolerates 12 consecutive poll blips, cancels at the budget so nothing keeps billing, and surfaces the model's own error text (`video model failed: …`). |
| `PROMPT_ASSET_PREFIX` | `prompts` | Under `PARTNER_ASSETS_DIR` (48h GC applies — download/post within 2 days) |
| `REPLICATE_VISION_MODEL` | `google/gemini-2.5-flash` | Reverse prompt: the vision model that watches the downloaded clip. Inputs: `prompt`, `videos[]`, `system_instruction`, plus `images[]` (≤10 cut-reference JPEGs) on the second pass. |
| `PROMPT_REVERSE_EXEMPLAR_PATH` | empty | Quality-bar prompt shown to Gemini. Empty = bundled `app/prompts/reverse_exemplar.txt` (Louis Vuitton Pacific Chill — Ashok 2026-09-10). |
| `PROMPT_REVERSE_MAX_VIDEO_MB` | `80` | Largest source clip we download or accept as base64. Telegram uploads are still capped at 20 MB by the Bot API. |

## 7. Deploy checklist (ThinkPad)

1. `alembic upgrade head` (runs in `scripts/deploy_local.sh`).
2. `ollama pull nomic-embed-text` (embeddings; hashed fallback works without it, worse dedupe recall).
3. `job_engine/.env`: `REPLICATE_API_TOKEN` set; optionally `REPLICATE_VIDEO_MODEL`, `PROMPT_WEB_URLS`, `PROMPT_INSTAGRAM_TAGS`.
4. Restart worker + beat + Telegram bot (the beat now carries `daily-prompt-pipeline` and `score-pending-prompts`; the bot carries the daily deck loop).
5. Open VIGIL at `http://127.0.0.1:8001` — Tower should say Prompt Tower, not Jobs. Tap **Scan now**. Watch Live + Activity. Prompts list fills as rows land.
6. Phone (secondary): `/promptscan` / `/prompts` → tap 1 → 📸 → ✅.

## 7b. VIGIL admin (prompt collection engine)

The left rail is the same modules, remapped:

| Rail | What it shows |
|---|---|
| Tower | Caught today, pending scores, top sources, categories, today's top-10, freshest catches, **Scan now** |
| Prompts | Full catalogue — live source/category chips, search, sort newest/score/rating |
| Scores | Mean, outliers, score bands, growing categories, fastest sources |
| Categories | Category mix over a time window |
| Hermes vs Recipe | Heuristic vs Hermes vs blend |
| Sources | Reddit / web / Instagram / pasted, last catch, **Scan now** |
| Activity | Catch / score / video timeline |
| Live | Engine log stream |
| Health | Heat, memory, caught today, pending scores, next scan, stall honesty |
| Winners | RAG exemplars, posted, your ratings |

Job stall banners stay off while `TOWER_MODE=prompts`. The old "Collection stalled — tower engine not running" was a false alarm: the job beat is asleep on purpose.

VIGIL must be built with a real `npm` (never the GitHub Actions runner copy — that npm is missing `lib/cli.js`). `job_engine/restart_app.sh` picks a working npm.

## 8. Honest limits (today)

- **Instagram posting is manual**: the bot delivers the card + video into Telegram; Ashok posts from the phone. Instagram Graph API publishing needs a Business account + app review — queued, not built.
- **Instagram scraping is best-effort** and off by default; Reddit + web pages + manual adds are the reliable daily feed until IG tags are enabled and verified live.
- **Prompts are other people's text**: every stored prompt keeps `source_url` + `author`; the card credits nothing by default — decide the attribution line before the first post.
- Video model input shapes on Replicate change; `video_creator.build_input` is the single place to adjust.

## 9. Definition of Done for this pivot

- [x] Migration + models · sources · normalize · RAG · Hermes scoring · daily top-10 · feedback learning
- [x] Video creator (Replicate) + Instagram card + asset storage on the AvatarPitch root
- [x] `/api/prompts/*` + `/api/partner/v1/prompts`
- [x] Telegram deck: list → select → 📸 → ✅ → card + video delivered; ⭐; 📣; `/promptperf`; once-a-day push
- [x] Job beat asleep behind `TOWER_MODE` — nothing deleted
- [x] 616 tests green (59 new)
- [ ] **Ashok verifies live**: first `/prompts` deck on the phone, first rendered video, first Instagram post — the pivot is not "done" until he accepts the real experience
