---
name: inspyry-vector-generator
description: Generate flat-color vector graphics (SVG) from a text prompt via the Inspyry API. Use when the user wants to create a logo, icon, mascot, character, badge, emblem, sticker, or wordmark as a scalable SVG (not a photo or raster). Handles auth, the single-request generate flow, style controls, and saving the SVG. Also works over the Inspyry MCP server.
---

# Inspyry Vector Generator

Generate clean, **flat-color vector (SVG)** artwork from a text prompt using the
Inspyry API / MCP server. Output is editable, scalable SVG — ideal for logos, icons,
mascots, badges, and wordmarks.

## When to use this skill

Use it when the user asks to **create/generate/make** a vector, SVG, logo, icon,
mascot, character, emblem, badge, sticker, or wordmark. Produce an `.svg` file.

Do **not** use it for: photos, 3D renders, paintings, raster images (PNG/JPG),
UI screenshots, or multi-paragraph text layouts — the engine only produces
flat-color vector art.

## Prerequisites

1. **API key** (`ik_…`). Buy credits, then create a key on the
   [account page](https://inspyry.com/account). Provide it via the
   `INSPYRY_API_KEY` env var (the older `INSPYRY_API_TOKEN` is still read).
   A key uses credits and **includes the commercial licence**.
2. **No key?** The website and the **MCP server** give a small free daily
   allowance (shared per network, **personal use only**). The REST API itself
   requires a key, and the web bot check blocks command-line tools.

Never hard-code or echo the key. If it isn't set, ask the user for it (or
suggest the keyless MCP server for a quick try).

## Two ways to use Inspyry

### A. MCP server (preferred if the host supports MCP)

Streamable HTTP at `https://inspyry.com/mcp`, tools `generate_vector` and
`get_balance`. Claude Code:

```bash
claude mcp add --transport http inspyry https://inspyry.com/mcp \
  --header "Authorization: Bearer ik_your_key"
```

Other clients: `{"mcpServers": {"inspyry": {"url": "https://inspyry.com/mcp",
"headers": {"Authorization": "Bearer ik_your_key"}}}}`. Omit the header for the
free personal-use allowance. `generate_vector` returns the SVG **as text** — write it
to a `.svg` file yourself. Errors come back as tool errors with the REST codes.

### B. Bundled CLI (stdlib only, Python 3.8+)

```bash
export INSPYRY_API_KEY=ik_xxx
python3 scripts/generate.py "a sitting fox" fox.svg --style flat-sticker --colours 4 --palette earthy
python3 scripts/generate.py "a laser-cut mushroom" -o m.svg --style stencil --colours 1
python3 scripts/generate.py --balance
```

Prints the saved path (or `--json`: `{id,path,bytes,svg_url,license,credits_used,
credits_left,free_left,warnings}`). Retries 429/5xx with backoff; a timed-out
generation is **never replayed** (it could be charged twice).

| Flag | Purpose |
| --- | --- |
| `-o, --output PATH` | output path (also the 2nd positional arg) |
| `--balance` | print credits / free uses left and exit |
| `--style --shape --composition --line-weight --shading --view --mood --detail` | enum controls (below) |
| `--colours N` | 1–16 colours; `1` = single-colour stencil |
| `--palette P` | preset name or comma-separated `#rrggbb` |
| `--background #hex` | solid background (default transparent) |
| `--outline #hex [--outline-width N]` | outline-only artwork |
| `--avoid TEXT` · `--aspect N` · `--margin N` · `--flip horizontal\|vertical` | exclusions, canvas ratio (0.1–10), padding (0–0.5), mirror |
| `--key KEY` · `--base-url URL` · `--timeout N` · `--max-retries N` · `-q` · `--json` | plumbing |

Exit codes: `0` ok · `2` usage · `3` auth (401) · `4` credits (402) · `5`
generation failed/filtered (422/502) · `6` timed out · `7` network · `1` other.

## Controls

All optional except `prompt`. Enums are validated server-side (`400` on bad value).

- **style** (default `flat-sticker`): flat-sticker, stencil, line-art, graffiti,
  tattoo, comic, manga, cartoon, esports-mascot, retro, art-deco, art-nouveau,
  vaporwave, cyberpunk, woodcut, engraving, stained-glass, papercut, halftone,
  doodle, ukiyoe, folk-art, tribal, celtic, filigree, pixel, low-poly, isometric,
  minimal-icon, monoline, geometric, kawaii, nautical, western, tiki
- **shape**: free, circle, rounded-square, shield, die-cut, wreath, hexagon,
  cameo, banner, speech-bubble, mandala
- **composition**: single, set, pattern, border · **lineWeight**: thin, medium,
  bold · **shading**: flat, cel, hatch, halftone · **view**: front, side,
  three-quarter · **mood**: playful, serious, elegant, aggressive ·
  **detail**: low, medium (default), high
- **colours** 1–16 · **palette**: pastel, neon, earthy, duotone, retro-cmyk,
  monochrome, sunset, ocean, or `["#rrggbb", …]`
- **background** `{"kind":"transparent"}` | `{"kind":"solid","colour":"#rrggbb"}` ·
  **outline** `{"colour":"#rrggbb","width":n}` · **aspect** · **margin** ·
  **flip** · **avoid** (≤200 chars)

Quick picks: logo/icon → `minimal-icon`/`monoline`/`geometric`; mascot →
`esports-mascot`/`cartoon`; sticker → `flat-sticker` + `die-cut`; cut file →
`stencil` + `colours 1`; badge → `shield`/`cameo`/`wreath` shape.

## What it can generate

**Great for:** logos & brand marks · UI/app icons & glyphs · character & mascot
illustrations · badges, crests, emblems · stickers & poster-style art · bold
lettering / wordmarks.

**Also suited to:** laser/vinyl cut files (`--colours 1 --style stencil`) ·
stickers and print-on-demand art.

**Not supported:** photorealism / 3D · smooth gradients (flattened to solid
colors) · busy scenes with full backgrounds · photographic texture · long text.

## How to prompt (this strongly affects quality)

- **Lead with the subject.** One clear, centered subject first, then its most
  distinctive traits. Avoid scenes/crowds/landscapes.
- **Prefer the controls over prose** for style, colour count, palette, shape,
  detail and background (see below); use the prompt for the subject. Exact
  colours in prose ("deep maroon and gold") still work.
- **For text, quote it exactly** and keep it short:
  `the word "INSPYRY" in a bold sans-serif font`.
- **Ornate detail is fine** (embroidery, filigree, jewellery) — or set
  `detail: high`.
- **Don't fight the medium.** Omit "photorealistic", "3D", "gradient",
  "realistic lighting". Pick a `style` instead of describing one in the prompt.
  Use `avoid` for things to leave out.
- **Prompt is max 400 chars.**

Good example prompts:
- `a minimalist flat-design fox icon, simple geometric shapes, orange white and dark brown, no gradients`
- `a coffee cup with steam, bold outlines, flat colors, modern logo style`
- `elegant north indian bride, deep maroon and gold bridal lehenga, intricate zardozi embroidery, vector illustration`
- `the word "INSPYRY" in a clean bold sans-serif font, solid black`
- `a steampunk octopus mascot, brass goggles, bold shapes, flat vector design`

## REST API reference

Base URL: `https://inspyry.com` (**no** `/api` prefix; the old async `/api/v1/generations`
flow is no longer used) · `Authorization: Bearer ik_…` ·
Spec: `GET /openapi.json`. Generation is **synchronous**: one request, one SVG.

### POST /v1/vectors — generate
Body: `{"prompt": "…", "style": "stencil", "colours": 1, …controls}`. Returns `200`:
```json
{ "id": "gen_…", "svg": "<svg …>", "svg_url": "https://inspyry.com/v1/vectors/gen_…/svg",
  "prompt": "<enhanced prompt>", "attempts": 1, "credits_used": 1, "credits_left": 9,
  "free_left": 0, "license": "commercial", "warnings": [] }
```
`license` is `commercial` with a key, `personal` for free/anonymous use. Surface
`warnings` to the user.

### GET /v1/vectors/{id}/svg — re-download
Permanent link (`svg_url`) to the SVG file; `404 not_found` if unknown.

### GET /v1/balance
`{ "kind": "device|api_key", "credits": 42, "free_left": 2, "free_limit": 3 }`.
(Also: `GET /v1/prices`, `POST /v1/checkout` for a credit pack, `GET /v1/account`.)

### Errors
Envelope `{ "error": "message", "code": "machine_code" }`. Failed or filtered
generations are **never charged**.

| Status | `code` | Meaning / action |
| --- | --- | --- |
| 400 | invalid_request | Bad control value or prompt — fix and resend |
| 401 | invalid_api_key | Key wrong or rotated — ask user for a new one |
| 402 | payment_required | No credits — buy a pack at inspyry.com/pricing |
| 422 | quality_failed / blocked_prompt | Failed quality check or prompt filtered — simplify/rephrase |
| 429 | quota_exceeded / attempt_limit / rate_limited | Free allowance (or daily attempts) used up — use a key or retry later |
| 502 | generation_failed | Temporary — retry |
| 503 | capacity_reached / free_capacity_reached | Daily capacity used up — retry later |

### Raw curl (if not using the helper)

```bash
curl -s https://inspyry.com/v1/vectors \
  -H "Authorization: Bearer $INSPYRY_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompt":"a laser-cut mushroom","style":"stencil","colours":1}' | jq -r .svg > out.svg
```

## Workflow for the agent

1. Prefer the Inspyry MCP tools if connected; otherwise confirm `INSPYRY_API_KEY`
   is set (ask for it if not).
2. Turn the user's idea into a single-subject prompt (≤400 chars) and choose
   `style`, `colours`, `palette`, `shape`, etc. from the controls above. Keep
   their intent.
3. Generate (`generate_vector`, or `scripts/generate.py "<prompt>" out.svg …`)
   and save the `.svg`.
4. Report the saved path, the `license` and `credits_left`. On `402` point to
   pricing; on `422` rephrase/simplify and retry (not charged); on `429` say the
   free allowance is spent and suggest a key.
