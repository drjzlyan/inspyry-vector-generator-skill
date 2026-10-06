# Inspyry Vector Generator — agent skill

A portable **agent skill** that generates clean, **flat-color vector (SVG)**
artwork from a text prompt using the [Inspyry](https://inspyry.com) [REST API and MCP server](https://inspyry.com/docs).
Output is editable, scalable SVG — ideal for logos, icons, mascots, badges, and
wordmarks.

It's designed to plug into **any AI agent or LLM tool-calling setup**, not just
one vendor. The core is a dependency-free Python CLI
([`scripts/generate.py`](scripts/generate.py)) that makes one
`POST /v1/vectors` request, saves the SVG, retries transient failures with
exponential backoff, and exits with meaningful status codes — so any agent that can run a
shell command (or call the underlying [HTTP API](#use-from-any-agent)) can use
it. [`SKILL.md`](SKILL.md) is the model-readable manifest describing when and how
to invoke it.

## Use with any agent

The skill is intentionally vendor-neutral. Pick whichever integration fits your
agent:

- **[Claude Code](https://claude.com/claude-code) / Claude Agent SDK** — clone
  into the skills folder and it's discovered automatically:
  ```bash
  git clone git@github.com:dhiraj-salian/inspyry-vector-generator-skill.git \
    ~/.claude/skills/inspyry-vector-generator
  ```
- **Any other agent (Cursor, Cline, LangChain/LlamaIndex tools, OpenAI/Gemini
  function calling, custom loops)** — register the CLI as a tool. Give the model
  the contents of [`SKILL.md`](SKILL.md) as the tool description/system context,
  and have it shell out to:
  ```bash
  python3 scripts/generate.py "<prompt>" <output>.svg
  ```
  The `--json` flag returns a structured result (`{id,path,bytes,svg_url,license,credits_*,free_left,warnings}`)
  for easy parsing, and the [exit codes](#exit-codes) let the agent branch on
  failures (auth, credits, timeout, …) without scraping text.
- **MCP** — Inspyry hosts an MCP server (`generate_vector`, `get_balance`) at
  `https://inspyry.com/mcp`; works keyless (free personal-use allowance) or
  with your key:
  ```bash
  claude mcp add --transport http inspyry https://inspyry.com/mcp \
    --header "Authorization: Bearer ik_your_key"
  ```
- **No wrapper at all** — call the [HTTP API directly](#use-from-any-agent);
  the CLI is just a convenience over a handful of REST endpoints.

Whatever the host, behavior, prompting guidance, and the API are identical —
[`SKILL.md`](SKILL.md) is the single source of truth.

## Prerequisites

1. **API key** — buy credits, then create a key (`ik_…`) on your
   [account page](https://inspyry.com/account). Provide it via
   `INSPYRY_API_KEY` (or `--key`). A key includes the commercial licence.
   Without a key only the website and MCP server work (small free allowance,
   personal use only).
2. **Credits** — check with `--balance`. Failed or filtered generations are
   never charged.

## Usage

```bash
export INSPYRY_API_KEY=ik_xxx

# generate and save, with controls
python3 scripts/generate.py "a sitting fox" fox.svg --style flat-sticker --colours 4 --palette earthy

# single-colour cut file
python3 scripts/generate.py "a laser-cut mushroom" -o m.svg --style stencil --colours 1

# credits and free uses left
python3 scripts/generate.py --balance
```

### Options

Run `python3 scripts/generate.py --help` for the full list. Highlights:
`--style`, `--shape`, `--composition`, `--line-weight`, `--shading`, `--view`,
`--mood`, `--detail`, `--colours 1-16`, `--palette`, `--background`,
`--outline`, `--aspect`, `--margin`, `--flip`, `--avoid`, plus `--json`,
`--key`, `--base-url`, `--timeout`, `--max-retries`, `-q`. Enum values are listed
in [`SKILL.md`](SKILL.md).

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 2 | usage error (bad arguments / prompt too short) |
| 3 | authentication error (missing or invalid key) |
| 4 | insufficient credits |
| 5 | generation failed or filtered (422 / 502) |
| 6 | request timed out |
| 7 | network error reaching the API |
| 1 | any other error |

## Use from any agent

The CLI is a thin convenience over a small REST API, so an agent can skip it
entirely. Auth is a bearer key; generation is a single synchronous request:

```bash
curl -s https://inspyry.com/v1/vectors \
  -H "Authorization: Bearer $INSPYRY_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompt":"a laser-cut mushroom","style":"stencil","colours":1}' | jq -r .svg > out.svg
```

The OpenAPI spec is at <https://inspyry.com/openapi.json>; docs at
<https://inspyry.com/docs>. See [`SKILL.md`](SKILL.md) for controls and errors.

## Prompting tips

The engine produces **flat-color vector art** — lead with a single, centered
subject, use the style/colour/palette controls rather than prose, and quote any
text verbatim. Omit `photorealistic`, `3D`, and `gradient`. See
[`SKILL.md`](SKILL.md) for the full prompting guide and API reference.

## Development

The client uses only the Python standard library (3.8+). Tests are fully mocked
and never hit the network:

```bash
python3 -m unittest discover -s tests
```

CI runs the suite on every push (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## License

[MIT](LICENSE) © Dhiraj Salian
