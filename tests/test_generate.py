"""Unit tests for the Inspyry generate.py client.

Network is fully mocked — these tests never touch the real API. Run with:

    python3 -m unittest discover -s tests
"""

import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

# Load scripts/generate.py as a module without requiring it to be a package.
_GEN_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "generate.py"
_spec = importlib.util.spec_from_file_location("generate", _GEN_PATH)
generate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate)


def _bytes(obj):
    return json.dumps(obj).encode()


class FakeHttp:
    """Returns/raises a scripted sequence of responses, recording each request."""

    def __init__(self, sequence):
        self._seq = list(sequence)
        self.requests = []

    @property
    def calls(self):
        return len(self.requests)

    def __call__(self, req):
        self.requests.append(req)
        item = self._seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(sequence, **kwargs):
    client = generate.InspyryClient("ik_test", **kwargs)
    client._http = FakeHttp(sequence)
    return client


OK = {"id": "gen_1", "svg": "<svg viewBox='0 0 1 1'></svg>", "svg_url": "https://x/y",
      "credits_used": 1, "credits_left": 9, "license": "commercial"}


class HelperTests(unittest.TestCase):
    def test_extract_error(self):
        self.assertEqual(generate._extract_error(_bytes({"error": "nope", "code": "invalid_request"})),
                         ("nope", "invalid_request"))
        self.assertEqual(generate._extract_error(b"not json"), ("", ""))

    def test_parse_retry_after(self):
        self.assertEqual(generate._parse_retry_after("3"), 3.0)
        self.assertIsNone(generate._parse_retry_after(None))
        self.assertIsNone(generate._parse_retry_after("soon"))

    def test_write_svg_adds_extension_and_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            saved = generate._write_svg("<svg></svg>", os.path.join(d, "nested", "logo"))
            self.assertTrue(saved.endswith(".svg"))
            self.assertTrue(os.path.exists(saved))

    def test_palette_parsing(self):
        self.assertEqual(generate._palette("neon"), "neon")
        self.assertEqual(generate._palette("#112233, #aabbcc"), ["#112233", "#aabbcc"])
        with self.assertRaises(Exception):
            generate._palette("#12")


class ApiErrorTests(unittest.TestCase):
    def test_exit_code_mapping(self):
        E = generate.ApiError
        self.assertEqual(E(401, "x").exit_code, generate.EXIT_AUTH)
        self.assertEqual(E(402, "x").exit_code, generate.EXIT_CREDITS)
        self.assertEqual(E(422, "x").exit_code, generate.EXIT_FAILED)
        self.assertEqual(E(502, "x").exit_code, generate.EXIT_FAILED)
        self.assertEqual(E(500, "x").exit_code, generate.EXIT_ERROR)


class ClientTests(unittest.TestCase):
    def test_balance(self):
        client = make_client([_bytes({"kind": "api_key", "credits": 7})])
        self.assertEqual(client.balance()["credits"], 7)
        self.assertTrue(client._http.requests[0].full_url.endswith("/v1/balance"))

    def test_generate_posts_prompt_and_controls(self):
        client = make_client([_bytes(OK)])
        job = client.generate("a fox", style="stencil", colours=1, shape=None)
        req = client._http.requests[0]
        self.assertTrue(req.full_url.endswith("/v1/vectors"))
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(json.loads(req.data), {"prompt": "a fox", "style": "stencil", "colours": 1})
        self.assertEqual(req.get_header("Authorization"), "Bearer ik_test")
        self.assertIn("<svg", job["svg"])

    def test_missing_svg_raises(self):
        client = make_client([_bytes({"id": "g", "svg": ""})])
        with self.assertRaises(generate.GenerationError):
            client.generate("prompt here")

    def test_retries_on_502_then_succeeds(self):
        client = make_client([generate.ApiError(502, "temp", error_code="generation_failed"),
                              _bytes(OK)])
        with mock.patch.object(generate.time, "sleep"):
            client.generate("prompt here")
        self.assertEqual(client._http.calls, 2)

    def test_quota_exceeded_not_retried(self):
        client = make_client([generate.ApiError(429, "used up", error_code="quota_exceeded")])
        with mock.patch.object(generate.time, "sleep"):
            with self.assertRaises(generate.ApiError):
                client.generate("prompt here")
        self.assertEqual(client._http.calls, 1)

    def test_post_not_replayed_on_network_error(self):
        client = make_client([generate.NetworkError("boom"), _bytes(OK)])
        with mock.patch.object(generate.time, "sleep"):
            with self.assertRaises(generate.NetworkError):
                client.generate("prompt here")
        self.assertEqual(client._http.calls, 1)

    def test_get_retries_network_error_then_gives_up(self):
        client = make_client([generate.NetworkError("boom")] * 5, max_retries=2)
        with mock.patch.object(generate.time, "sleep"):
            with self.assertRaises(generate.NetworkError):
                client.balance()
        self.assertEqual(client._http.calls, 3)

    def test_non_retryable_status_raises_immediately(self):
        client = make_client([generate.ApiError(402, "no credits", error_code="payment_required")])
        with self.assertRaises(generate.ApiError) as ctx:
            client.generate("prompt here")
        self.assertEqual(ctx.exception.code, 402)


class CliTests(unittest.TestCase):
    ENV = {"INSPYRY_API_KEY": "ik_test"}

    def test_missing_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(generate.SkillError):
                generate.run(["a valid prompt"])

    def test_prompt_required(self):
        with mock.patch.dict(os.environ, self.ENV):
            with self.assertRaises(generate.UsageError):
                generate.run([])

    def test_prompt_too_long(self):
        with mock.patch.dict(os.environ, self.ENV):
            with self.assertRaises(generate.UsageError):
                generate.run(["x" * 401])

    def test_run_generate_writes_file_with_controls(self):
        fake = FakeHttp([_bytes(OK)])
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "icon.svg")
            with mock.patch.dict(os.environ, self.ENV):
                with mock.patch.object(generate.InspyryClient, "_http", fake):
                    code = generate.run([
                        "a flat fox icon", out, "-q", "--style", "stencil", "--colours", "1",
                        "--palette", "earthy", "--background", "#ffffff",
                        "--outline", "#000000", "--outline-width", "3",
                    ])
            self.assertEqual(code, generate.EXIT_OK)
            self.assertTrue(os.path.exists(out))
        sent = json.loads(fake.requests[0].data)
        self.assertEqual(sent["style"], "stencil")
        self.assertEqual(sent["colours"], 1)
        self.assertEqual(sent["palette"], "earthy")
        self.assertEqual(sent["background"], {"kind": "solid", "colour": "#ffffff"})
        self.assertEqual(sent["outline"], {"colour": "#000000", "width": 3.0})

    def test_balance_flag(self):
        fake = FakeHttp([_bytes({"credits": 3, "free_left": 1, "free_limit": 2})])
        with mock.patch.dict(os.environ, self.ENV):
            with mock.patch.object(generate.InspyryClient, "_http", fake):
                self.assertEqual(generate.run(["--balance"]), generate.EXIT_OK)

    def test_legacy_token_env_still_works(self):
        with mock.patch.dict(os.environ, {"INSPYRY_API_TOKEN": "ik_old"}, clear=True):
            args = generate._build_parser().parse_args(["x"])
            self.assertEqual(generate._resolve_token(args), "ik_old")


if __name__ == "__main__":
    unittest.main()
