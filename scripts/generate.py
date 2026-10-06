#!/usr/bin/env python3
"""Generate a flat-color vector SVG from a text prompt via the Inspyry API.

A single-file, dependency-free client for the Inspyry public API. One request
returns the finished SVG (``POST /v1/vectors``); the client saves it, retries
transient failures with exponential backoff, and exits with meaningful status
codes.

Examples
--------
    export INSPYRY_API_KEY=ik_xxx
    python3 generate.py "a sitting fox" fox.svg --style flat-sticker --colours 4
    python3 generate.py "a laser-cut mushroom" -o m.svg --style stencil --colours 1
    python3 generate.py --balance            # just print credits / free uses left
    python3 generate.py "bold lightning bolt" -o out/bolt.svg --json

Exit codes
----------
    0  success
    2  usage error (bad arguments / prompt too short)
    3  authentication error (missing or invalid API key, HTTP 401)
    4  insufficient credits (HTTP 402)
    5  generation failed (422 quality_failed / blocked_prompt, 502 generation_failed)
    6  timed out waiting for the generation
    7  network error reaching the API
    1  any other error

Requires Python 3.8+ and only the standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

DEFAULT_BASE_URL = "https://inspyry.com"
USER_AGENT = "inspyry-vector-generator/2.0 (+https://inspyry.com)"
MAX_PROMPT_LEN = 400
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# 429 with these codes means the allowance is spent for now; retrying is futile.
NO_RETRY_CODES = {"quota_exceeded", "attempt_limit"}

# Enumerated controls, mirrored from https://inspyry.com/openapi.json.
STYLES = [
    "flat-sticker", "stencil", "line-art", "graffiti", "tattoo", "comic", "manga",
    "cartoon", "esports-mascot", "retro", "art-deco", "art-nouveau", "vaporwave",
    "cyberpunk", "woodcut", "engraving", "stained-glass", "papercut", "halftone",
    "doodle", "ukiyoe", "folk-art", "tribal", "celtic", "filigree", "pixel",
    "low-poly", "isometric", "minimal-icon", "monoline", "geometric", "kawaii",
    "nautical", "western", "tiki",
]
SHAPES = ["free", "circle", "rounded-square", "shield", "die-cut", "wreath",
          "hexagon", "cameo", "banner", "speech-bubble", "mandala"]
COMPOSITIONS = ["single", "set", "pattern", "border"]
LINE_WEIGHTS = ["thin", "medium", "bold"]
SHADINGS = ["flat", "cel", "hatch", "halftone"]
VIEWS = ["front", "side", "three-quarter"]
MOODS = ["playful", "serious", "elegant", "aggressive"]
DETAILS = ["low", "medium", "high"]
PALETTES = ["pastel", "neon", "earthy", "duotone", "retro-cmyk", "monochrome",
            "sunset", "ocean"]
FLIPS = ["horizontal", "vertical"]

# Exit codes (see module docstring).
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_CREDITS = 4
EXIT_FAILED = 5
EXIT_TIMEOUT = 6
EXIT_NETWORK = 7
EXIT_ERROR = 1


# ─── Errors ──────────────────────────────────────────────────────────────────


class SkillError(Exception):
    """Base error carrying an intended process exit code."""

    exit_code = EXIT_ERROR


class UsageError(SkillError):
    exit_code = EXIT_USAGE


class GenerationError(SkillError):
    exit_code = EXIT_FAILED


class TimeoutExceeded(SkillError):
    exit_code = EXIT_TIMEOUT


class NetworkError(SkillError):
    exit_code = EXIT_NETWORK


class ApiError(SkillError):
    """An HTTP-level error from the API. ``code`` is the HTTP status and
    ``error_code`` the API's machine-readable code (e.g. ``payment_required``)."""

    def __init__(self, code: int, message: str, retry_after: Optional[float] = None,
                 error_code: str = ""):
        super().__init__(message or f"HTTP {code}")
        self.code = code
        self.message = message or f"HTTP {code}"
        self.retry_after = retry_after
        self.error_code = error_code

    @property
    def exit_code(self) -> int:  # type: ignore[override]
        if self.code in (422, 502):
            return EXIT_FAILED
        return {401: EXIT_AUTH, 402: EXIT_CREDITS}.get(self.code, EXIT_ERROR)


# ─── Client ──────────────────────────────────────────────────────────────────


def _extract_error(body: bytes) -> Tuple[str, str]:
    """Return ``(message, code)`` from an ``{"error", "code"}`` envelope."""
    try:
        data = json.loads(body.decode())
        return str(data.get("error", "")).strip(), str(data.get("code", "")).strip()
    except Exception:
        return "", ""


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


class InspyryClient:
    """Thin client over the Inspyry public API with retry + backoff."""

    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        http_timeout: float = 180.0,
        max_retries: int = 3,
        log=lambda _msg: None,
    ):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.http_timeout = http_timeout
        self.max_retries = max_retries
        self._log = log

    # -- transport -----------------------------------------------------------

    def _http(self, req: urllib.request.Request) -> bytes:
        """Perform one HTTP call. Raises ApiError / NetworkError; returns body."""
        try:
            with urllib.request.urlopen(req, timeout=self.http_timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:
                pass
            retry_after = None
            if exc.headers is not None:
                retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
            message, err_code = _extract_error(body)
            raise ApiError(exc.code, message or (exc.reason or ""), retry_after, err_code)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TimeoutExceeded(f"timed out after {self.http_timeout:.0f}s")
            raise NetworkError(f"could not reach {self.base_url}: {exc.reason}")
        except (TimeoutError, socket.timeout):
            raise TimeoutExceeded(f"timed out after {self.http_timeout:.0f}s")

    def _backoff(self, attempt: int) -> float:
        # Exponential backoff with full jitter, capped at 30s.
        return min(30.0, (2 ** attempt)) * (0.5 + random.random() / 2)

    def _send(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = json.dumps(body).encode() if body is not None else None
        attempt = 0
        while True:
            req = urllib.request.Request(self.base_url + path, data=payload, method=method)
            req.add_header("Authorization", f"Bearer {self.token}")
            req.add_header("User-Agent", USER_AGENT)
            req.add_header("Accept", "application/json")
            if payload is not None:
                req.add_header("Content-Type", "application/json")
            try:
                raw = self._http(req)
            except ApiError as exc:
                if (exc.code in RETRYABLE_STATUS and exc.error_code not in NO_RETRY_CODES
                        and attempt < self.max_retries):
                    delay = exc.retry_after if exc.retry_after is not None else self._backoff(attempt)
                    self._log(f"API returned {exc.code}; retrying in {delay:.1f}s "
                              f"(attempt {attempt + 1}/{self.max_retries})")
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise
            except NetworkError as exc:
                # A POST that timed out may still have been charged; never replay it.
                if method == "GET" and attempt < self.max_retries:
                    delay = self._backoff(attempt)
                    self._log(f"{exc}; retrying in {delay:.1f}s "
                              f"(attempt {attempt + 1}/{self.max_retries})")
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise
            if not raw:
                return {}
            try:
                return json.loads(raw.decode())
            except (ValueError, UnicodeDecodeError):
                raise ApiError(0, "the API returned a response that was not valid JSON")

    # -- endpoints -----------------------------------------------------------

    def balance(self) -> Dict[str, Any]:
        return self._send("GET", "/v1/balance")

    def generate(self, prompt: str, **controls: Any) -> Dict[str, Any]:
        """Generate an SVG in a single request. Returns the response dict."""
        body: Dict[str, Any] = {"prompt": prompt}
        body.update({k: v for k, v in controls.items() if v is not None})
        job = self._send("POST", "/v1/vectors", body)
        if "<svg" not in (job.get("svg") or "").lower():
            raise GenerationError("the API returned no SVG payload")
        return job


# ─── CLI ─────────────────────────────────────────────────────────────────────


def _hex(value: str) -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a #rrggbb colour")
    return value


def _palette(value: str):
    if value in PALETTES:
        return value
    parts = [c.strip() for c in value.split(",") if c.strip()]
    if parts:
        return [_hex(c) for c in parts]
    raise argparse.ArgumentTypeError(
        f"palette must be one of {', '.join(PALETTES)} or comma-separated #rrggbb colours"
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="generate.py",
        description="Generate a flat-color vector SVG from a text prompt via the Inspyry API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("prompt", nargs="?", help="what to draw (max %d chars)" % MAX_PROMPT_LEN)
    p.add_argument("output", nargs="?", help="output path (default: output.svg)")
    p.add_argument("-o", "--output", dest="output_flag", metavar="PATH",
                   help="output path (overrides the positional output)")
    p.add_argument("--token", "--key", dest="token",
                   help="API key (overrides $INSPYRY_API_KEY)")
    p.add_argument("--base-url", default=os.environ.get("INSPYRY_API_BASE", DEFAULT_BASE_URL),
                   help="API base URL (default: %(default)s)")
    p.add_argument("--balance", "--credits", dest="balance", action="store_true",
                   help="print credits / free uses left and exit (no generation)")
    p.add_argument("--timeout", type=float, default=180.0,
                   help="seconds to wait for the API (default: %(default)s)")
    p.add_argument("--max-retries", type=int, default=3,
                   help="retries for transient errors (default: %(default)s)")
    p.add_argument("--json", action="store_true",
                   help="emit a JSON result object on stdout")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="suppress progress messages on stderr")

    g = p.add_argument_group("generation controls (all optional)")
    g.add_argument("--style", choices=STYLES, metavar="STYLE",
                   help="art style, e.g. flat-sticker, stencil, line-art (see SKILL.md)")
    g.add_argument("--shape", choices=SHAPES)
    g.add_argument("--composition", choices=COMPOSITIONS)
    g.add_argument("--line-weight", dest="lineWeight", choices=LINE_WEIGHTS)
    g.add_argument("--shading", choices=SHADINGS)
    g.add_argument("--view", choices=VIEWS)
    g.add_argument("--mood", choices=MOODS)
    g.add_argument("--avoid", help="things to leave out (max 200 chars)")
    g.add_argument("--colours", "--colors", dest="colours", type=int, choices=range(1, 17),
                   metavar="1-16", help="number of colours; 1 makes a single-colour stencil")
    g.add_argument("--detail", choices=DETAILS)
    g.add_argument("--palette", type=_palette, metavar="PALETTE",
                   help="preset (%s) or comma-separated #rrggbb list" % ", ".join(PALETTES))
    g.add_argument("--background", type=_hex, metavar="#RRGGBB",
                   help="solid background colour (default: transparent)")
    g.add_argument("--outline", type=_hex, metavar="#RRGGBB",
                   help="outline-only artwork in this colour (see --outline-width)")
    g.add_argument("--outline-width", type=float, default=2.0, metavar="N",
                   help="outline width used with --outline (default: %(default)s)")
    g.add_argument("--aspect", type=float, help="width / height of the canvas (0.1-10)")
    g.add_argument("--margin", type=float, help="padding as a fraction of the canvas (0-0.5)")
    g.add_argument("--flip", choices=FLIPS)
    return p


def _controls(args: argparse.Namespace) -> Dict[str, Any]:
    c: Dict[str, Any] = {
        k: getattr(args, k)
        for k in ("style", "shape", "composition", "lineWeight", "shading", "view",
                  "mood", "avoid", "colours", "detail", "palette", "aspect", "margin", "flip")
        if getattr(args, k) is not None
    }
    if args.background:
        c["background"] = {"kind": "solid", "colour": args.background}
    if args.outline:
        c["outline"] = {"colour": args.outline, "width": args.outline_width}
    if "aspect" in c and not 0.1 <= c["aspect"] <= 10:
        raise UsageError("--aspect must be between 0.1 and 10.")
    if "margin" in c and not 0 <= c["margin"] <= 0.5:
        raise UsageError("--margin must be between 0 and 0.5.")
    if "avoid" in c and len(c["avoid"]) > 200:
        raise UsageError("--avoid must be at most 200 characters.")
    return c


def _resolve_token(args: argparse.Namespace) -> str:
    token = (args.token or os.environ.get("INSPYRY_API_KEY")
             or os.environ.get("INSPYRY_API_TOKEN") or "").strip()
    if not token:
        raise SkillError(
            "No API key. Set $INSPYRY_API_KEY or pass --key. "
            "Buy credits, then create a key at https://inspyry.com/account."
        )
    return token


def _write_svg(svg: str, out_path: str) -> str:
    if not out_path.lower().endswith(".svg"):
        out_path += ".svg"
    parent = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return out_path


def run(argv: Optional[list] = None) -> int:
    args = _build_parser().parse_args(argv)
    log = (lambda _m: None) if args.quiet else (lambda m: print(m, file=sys.stderr))

    token = _resolve_token(args)
    client = InspyryClient(
        token,
        base_url=args.base_url,
        http_timeout=args.timeout,
        max_retries=args.max_retries,
        log=log,
    )

    if args.balance:
        data = client.balance()
        if args.json:
            print(json.dumps(data))
        else:
            print(f"credits: {data.get('credits', '?')} · "
                  f"free left today: {data.get('free_left', '?')}/{data.get('free_limit', '?')}")
        return EXIT_OK

    prompt = (args.prompt or "").strip()
    if not prompt:
        raise UsageError('A prompt is required. Usage: generate.py "<prompt>" [output.svg]')
    if len(prompt) > MAX_PROMPT_LEN:
        raise UsageError(f"Prompt must be at most {MAX_PROMPT_LEN} characters.")
    controls = _controls(args)

    out_path = args.output_flag or args.output or "output.svg"
    log("generating …")
    job = client.generate(prompt, **controls)
    saved = _write_svg(job["svg"], out_path)
    for warning in job.get("warnings") or []:
        log(f"warning: {warning}")

    if args.json:
        print(json.dumps({
            "id": job.get("id"),
            "path": os.path.abspath(saved),
            "bytes": len(job["svg"].encode("utf-8")),
            "svg_url": job.get("svg_url"),
            "license": job.get("license"),
            "credits_used": job.get("credits_used"),
            "credits_left": job.get("credits_left"),
            "free_left": job.get("free_left"),
            "warnings": job.get("warnings", []),
        }))
    else:
        print(saved)
    return EXIT_OK


def main() -> None:
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
    except ApiError as exc:
        hint = {
            "invalid_api_key": " — check your API key (https://inspyry.com/account)",
            "payment_required": " — buy credits at https://inspyry.com/pricing",
            "quota_exceeded": " — free allowance used up for now; use an API key or retry later",
            "blocked_prompt": " — the prompt was filtered; rephrase it (not charged)",
            "quality_failed": " — result failed the quality check; simplify the prompt (not charged)",
        }.get(exc.error_code, "")
        print(f"error: API {exc.code}"
              f"{' ' + exc.error_code if exc.error_code else ''}: {exc.message}{hint}",
              file=sys.stderr)
        sys.exit(exc.exit_code)
    except SkillError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)


if __name__ == "__main__":
    main()
