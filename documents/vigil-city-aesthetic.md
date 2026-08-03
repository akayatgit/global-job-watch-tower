# VIGIL City View — Editorial Dusk Miniature

Master look for Jobs → City campus and single-metro districts.
Interaction stays unchanged; this file is the **visual bible**.

Synthesized 2026-08-03 from Ashok’s expert prompt mix (isometric miniature,
graduation memory poster, infrastructure singularity, weather editorial,
LEGO editorial) — kept what serves a govt-presentable hiring map; rejected
cartoon neon, gravity-well surrealism, and commercial template clutter.

---

## Master prompt (use this to steer future passes)

Present a clear **45° top-down isometric miniature 3D** hiring campus of
`[CITY]` (or a multi-city Jobs skyline). Soft, refined textures with
**realistic PBR materials**, gentle lifelike lighting and soft contact
shadows. Atmosphere = **evening dusk dissolving into a deep sea blue-gray /
deep ink studio void** — immersive weather mood without a weather widget.

**Composition (editorial, title-dominant)**
- Clean, minimal frame. Soft solid / soft-gradient background — not a busy
  starfield HUD.
- **City name is the first visual focal point**: large, centered, warm white
  or light blue-white, may lightly overlap the tops of towers. No glass
  pill, no neon yellow, no corner badges.
- Auxiliary hiring data lives in a small **lyric information area** — one
  frosted cream glass card per company (name · large count · quiet caption ·
  role rows). Do not scatter labels in the four corners.
- Roads + moving vehicles prove scale (transit/road system presence) without
  warping into spirals or gravity wells.
- Surrounding blocks are soft **cinematic silhouettes** that dissolve into
  fog/vignette at the edges — album-cover dusk, not game neon fabric.

**Materials & light**
- Soft studio key from a low warm sun; cool fill; subtle plastic/glass sheen
  on data towers (clear, not candy).
- Floor plates read as quiet white slabs inside soft ice-blue glass volumes.
- Film-soft grain and slight vignette in the atmosphere — nostalgic punch,
  airiness — never low-res mud or cartoon illustration.

**Palette**
- Background: Deep Ink / Deep Sea Blue-Gray dusk gradient
- Title: Warm White or Light Blue-White
- Cards: Warm off-white / cream glass, slate/navy type, soft status dots
- Towers: Ice glass + cream floors; accents stay cool blue family only
- Fabric: Near-black silhouettes with warm rim from the sunset, not rainbow

**Avoid**
- Neon cyberpunk HUD, fluorescent yellow role stickers, rainbow towers
- Text crammed in corners, QR codes, commercial logos
- Cartoon / toy / over-polished ad template feel
- Gravity-well disaster surrealism (roads stay a readable grid)

---

## What we took from each source prompt

| Source | Kept | Dropped |
|---|---|---|
| Isometric miniature city | 45° iso, PBR, soft light, weather-in-atmosphere, soft solid bg | Generic tourist landmarks for their own sake |
| Graduation memory poster | Title-dominant hierarchy, lyric info zone, dusk nostalgia, grain/vignette, airiness | Chinese brush title, photo collage layout, portrait 3:4 poster |
| Infrastructure singularity | Skyline + road/transit scale, hyperreal miniature, dark studio void | Spiral roads, event horizon, debris field |
| Weather editorial | Centered city title that may kiss building tops | Weather icon / temp chrome |
| LEGO editorial | Soft studio sheen, cream editorial calm, model fills frame | Literal studs / brick seams / saturated toy colors |

---

## Implementation map

| Surface | File / piece |
|---|---|
| Sky, fog, bloom | `NightCity` SunsetSky · `VigilCanvas` nightDistrict fog/bloom |
| Title | `makeCityFlag` — freestanding title, no pill |
| Cards | `makeTowerCard` / `paintGlassPlate` — cream lyric cards |
| Towers + fabric | `GlassTower` · `DummyBuilding` |
| Roads / cars | `Ground` · `Traffic` |
| Default angle | `SceneControls` city camera ≈ 45° iso |

Update this file whenever the city look shifts again.

---

## Reference: Aximoris Spline City (2026-08-03)

Sources Ashok shared:
- Live: https://my.spline.design/untitled-1c75a09a7f33d5999b7680c9dc0a7626/
- Clip: https://x.com/Aximoris/status/1743648652617302478/video/1  
  (Max / @Aximoris — “simple shapes + cloner → cute isometric 3D city”)

**Why it feels clean + interactive**
1. **Negative space** — city is a small precious miniature; ~half+ of frame is calm studio void
2. **Simple massing** — cubes/rects/cloners; readable silhouettes; no mesh spam
3. **Matte studio light** — soft key + soft shadows; clay/architectural-model calm
4. **Rounded baseplate** — one clear “object on a pedestal” campus pad
5. **Scale life** — tiny car / tree / helicopter; motion proves scale without HUD noise
6. **Labels off by default** — geometry first; data appears on intent (hover/focus)
7. **Orbit feels free** — drag/zoom is the product; chrome never fights the hand

**Apply to Watch Tower (keep dusk mood + hiring cards)**
- Stronger pedestal pad + more breathing room around clusters
- Hide cream lyric cards until hover/focus (title can stay)
- Softer matte PBR; less emissive wash
- Optional: one gentle “life” prop (heli/drone loop) for delight at govt demos
- Never import toy pastel rainbow — keep Editorial Dusk palette

**Do not** embed Spline runtime for production data campus — keep R3F + Postgres live.
