# VIGIL City View — MapLibre hiring map

**Current (2026-08-03):** City mode is MapLibre GL JS — real India geography,
OpenFreeMap basemap, 3D building extrusions, company overlays from skyline
APIs. R3F CityGlobe + NightCity are retired from the live path (recover via
`milestone/pre-maplibre-city`).

Implementation: `job_engine/vigil/src/scene/CityMap.tsx`

---

## Archive — Editorial miniature notes (pre-MapLibre)

Kept below for history. Not the live renderer.

---

## Master prompt (use this to steer future passes)

Present a clear **45° top-down isometric miniature 3D** hiring campus of
`[CITY]` (or a multi-city Jobs skyline). Soft, refined textures with
**realistic PBR materials**, gentle lifelike lighting and soft contact
shadows. Atmosphere = **well-lit daylight studio** — soft pale sky, bright
key sun, calm grey negative space (Aximoris calm + editorial cards).

**Composition (editorial, title-dominant)**
- Clean, minimal frame. Soft solid / soft-gradient background — not a busy
  starfield HUD.
- **City name is the first visual focal point**: large, centered, soft slate
  on daylight, may lightly overlap tower tops. No glass pill, no neon, no
  corner badges.
- Hiring cards appear **only on hover/focus** — content-sized (width/height
  hug text + roles; no fixed empty plate). Geometry first.
- Generous space between towers + rounded pedestal pad (breathing room).
- Roads + moving vehicles prove scale without HUD noise.
- Surrounding fabric = soft matte clay daylight blocks, not neon silhouettes.

**Materials & light**
- Bright daylight key from above; cool fill; soft contact shadows.
- Floor plates = quiet white slabs inside soft ice glass.
- Soft vignette only — no heavy film/night grain.

**Palette**
- Background: Soft pale blue-gray daylight studio
- Title: Soft slate (#1e293b)
- Cards: Cream glass, slate type, soft status dots — dynamic size
- Towers: Ice glass + white floors; cool blue accents only
- Fabric: Light grey/white matte clay

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
