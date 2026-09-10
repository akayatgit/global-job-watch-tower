# Prompt Tower — "Jobs are now prompts" (pivot 2026-09-09)

| Field | Value |
|---|---|
| **Ruling** | Ashok, 2026-09-09: *"Jobs are now prompts. Do what I say. We don't need jobs."* |
| **Product** | Daily top-10 **AI video prompts for D2C product videos** (Veo / Kling / Sora), scored by Hermes, posted on Instagram for authority, sold later as prompt + video packs |
| **Authority channel** | Instagram, reference format: `Comment "PERFUME" for prompts` → hero video → **Prompt** text → `@handle` |
| **Owner surface** | **VIGIL admin** at `http://127.0.0.1:8001` is the collection cockpit (Tower · Prompts · Scores · Sources · Activity · Live · Health). Telegram is delivery + approve-to-video, not the monitor. |

| **Learning loop** | RAG of proven winners (rated ≥4 or strong engagement) → few-shot anchors + baseline for tomorrow's scoring → outliers flagged 🔥 |
| **Render** | Replicate image→video (`REPLICATE_VIDEO_MODEL`, default `kwaivgi/kling-v2.1`) → MP4 + Instagram card stored in the AvatarPitch asset root, served at `/api/partner/v1/assets/{key}` |
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
| Shortlist | `app/prompts/pipeline.py::build_shortlist` | Top `PROMPT_SHORTLIST_SIZE` (10) with `final_score ≥ PROMPT_MIN_SCORE` (55), collected in the last 48h, outliers first, **≤3 per source** (manual exempt). Idempotent per UTC day; `force` rebuilds. |
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

Guests never see any of it: `pt:` taps and prompt commands are gated on the real owner check; a guest's photo is ignored exactly as before.

### 3a. The reel — the post is a video, not a picture (2026-09-10)

Ashok: "wherever the image is you need to place the video … this entire template should come out as a video … the prompt scrolls … storyboard: six frames in the same aspect ratio next to each other in the other half." `app/prompts/post_reel.py` composes a 1080×1920 MP4 with the system `ffmpeg` (no new Python package — the ThinkPad deploy does not `pip install`):

```
Comment "SKINCARE" for prompts        ← bold, shrinks 64→30 pt until it fits the width
[ AI clip plays here, rounded ]       ← the card's hero box (900×820), cover-fit, no letterbox
Storyboard          | Prompt
[6 stills, grid]    | prompt text scrolling over the clip's duration
@jobmaster.agency
```

- **Storyboard** (left half): six stills at the mid-points of six equal slices, in the clip's own aspect ratio; the grid (3×2 for 9:16, 2×3 for 16:9) is the largest that fits the half-column (`storyboard_layout`).
- **Prompt** (right half): the stored prompt **verbatim, never truncated**, rendered as one tall strip; the visible window holds for the first 12 % of the clip, slides linearly so the last line arrives at the bottom by 88 %, then holds. Short prompts sit still.
- Frame rate = the clip's (capped at 30), duration = the clip's, **audio copied** when the clip has a track (Veo). ffmpeg decodes already cover-fitted to the hero box; Pillow composites; ffmpeg encodes H.264 yuv420p `+faststart` for iPhone playback.
- Stored as `prompts/<day>/reel-<id>-<rand>.mp4` next to the raw clip; `prompt_renders.reel_key / reel_url`. A composition failure sets `reel_error` and keeps the clip — the render is still `done`.
- Deploy logs a loud `WARNING` when `ffmpeg`/`ffprobe` are missing (`sudo apt install -y ffmpeg`).

## 4. API

Owner surface (local tower, `/api/prompts`):

| Route | Purpose |
|---|---|
| `GET /today?day=&full=1` | Day's shortlist (rank, scores, provenance; `full=1` = whole text) |
| `GET /stats` | Tower numbers + winners baseline |
| `GET /{id}` | One prompt, full text |
| `POST /scan {force, inline}` | Run the pipeline (Celery by default; `inline` for dev/tests) |
| `POST /ingest {text, author, source_url}` | Manual add + immediate score (422 when it isn't a prompt) |
| `POST /{id}/rate {rating 1–5}` · `POST /{id}/performance {likes…}` · `POST /{id}/posted` | Feedback → RAG |
| `POST /{id}/render {image_base64, chat_id, content_type}` | Store image, render card, queue video → render row |
| `GET /renders/{id}` | `queued | running | done | failed`, `video_url` (raw clip), `reel_url` (post asset) or `reel_error`, `card_image_url` (preview) |

Partner surface (AvatarPitch, bearer `PARTNER_API_TOKEN`): **`GET /api/partner/v1/prompts?day=`** — the day's top-10 with full text, scores, provenance and any finished `video_url` (raw clip) / `reel_url` (post asset) / `card_image_url`. Rows verbatim; the tower owns scoring, AvatarPitch renders/presents.

## 5. Data model (migrations `b7c3e9a12d45` → `c8d4f0b23e56`)

- `video_prompts` — text, fingerprint (unique), source/source_url/author/source_posted_at, model_hint, category, heuristic_score, ai_detail/ai_flow/ai_score/ai_reasons, final_score, baseline_mean/std, is_outlier, embedding (JSON), status (`new | shortlisted | posted | rejected`), rating, performance (JSON), performance_score, posted_at, exemplar.
- `prompt_shortlists` — (day, rank) unique → prompt_id.
- `prompt_renders` — prompt_id, chat_id, product_image_key, card_image_key, video_key, video_url, **reel_key, reel_url, reel_error** (migration `c8d4f0b23e56`), model, status, error, timestamps.

Guest/alert/broadcast SQLite state is untouched; the deck's pending states live in the same `bot_state` table (`prompt_selected:`, `prompt_await_image:`, `pending_prompt_photo:`, `prompt_daily_sent:<day>`).

## 6. Configuration (`job_engine/.env`)

| Key | Default | Meaning |
|---|---|---|
| `TOWER_MODE` | `prompts` | `prompts` = job beat asleep · `jobs` = legacy collection |
| `PROMPT_PIPELINE_UTC_HOUR` / `_MINUTE` | `3` / `30` | Daily run (09:00 IST) |
| `PROMPT_REDDIT_SUBS` | `aivideo,PromptEngineering,VeoAI,KlingAI,Sora,runwayml,AIVideoPrompts` | Public listings. **JSON is 403-blocked** from typical server IPs — collector tries `.json` then falls back to Atom `.rss`. A 403 switches the rest of the run to RSS only; a **429** stops touching Reddit for that run (remaining subs reported as *skipped*, not failed). |
| `PROMPT_REDDIT_PAUSE_S` | `8` | Seconds between subreddit fetches (+ a ≤3 s breather before an RSS retry). Seven subs in a two-second burst earned HTTP 429 on 2026-09-10. |
| `PROMPT_WEB_URLS` | Six D2C ad-prompt handbooks: LichAmnesia *awesome-ad-video-prompts*, prompt-architects Veo 3 structure, veo3ai.io product-ads guide, ugcvids.ai Veo 3.1 product ads, cclank Kling + Veo READMEs | Public pages to mine (product-focused first). Blank `PROMPT_WEB_URLS=` in `.env` still uses this default. Probe 2026-09-10: 115 blocks → 75 real prompts kept, 40 prose/TOC/FAQ blocks dropped. |
| `PROMPT_INSTAGRAM_TAGS` | empty (off) | Hashtags via the logged-in stealth Chrome profile |
| `PROMPT_SOURCE_LIMIT` | `40` | Per-source fetch cap |
| `PROMPT_SHORTLIST_SIZE` / `PROMPT_MIN_SCORE` | `10` / `55` | Deck size, eligibility floor |
| `PROMPT_EMBED_MODEL` | `nomic-embed-text` | `ollama pull nomic-embed-text` on the ThinkPad |
| `REPLICATE_VIDEO_MODEL` | `kwaivgi/kling-v2.1` | Also handled: `google/veo-3*`, `bytedance/seedance*`, `minimax/*`, `wan-video/*` |
| `PROMPT_VIDEO_DURATION_S` | `10` | Kling 5/10 · Veo 8 |
| `PROMPT_ASSET_PREFIX` | `prompts` | Under `PARTNER_ASSETS_DIR` (48h GC applies — download/post within 2 days) |

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
