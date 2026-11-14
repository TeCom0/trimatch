"""Gemini vision extractor (plan-step4-gemini-extraction.md). Free tier, synthetic docs only.

uv run --project backend python -m trimatch.extract.gemini --list-models
uv run --project backend python -m trimatch.extract.gemini data/synthetic/e2e/<file>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import yaml

from trimatch.config import CONFIG_DIR, REPO_ROOT
from trimatch.extract.gemini_schema import RDoc, to_document
from trimatch.odoo_adapter import load_dotenv
from trimatch.schema import DeliveryNote, Invoice

SYNTHETIC_ROOT = (REPO_ROOT / "data" / "synthetic").resolve()
CACHE_ROOT = REPO_ROOT / "data" / "cache" / "gemini"
PROMPT = (Path(__file__).parent / "prompt_fr.md").read_text(encoding="utf-8")
MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


class QuotaExhausted(RuntimeError):
    """The daily free-tier budget for this model is used up. Re-run tomorrow (cache resumes)."""


class NotADocument(ValueError):
    pass


def prompt_hash() -> str:
    schema = json.dumps(RDoc.model_json_schema(), sort_keys=True)
    return hashlib.sha256((PROMPT + schema).encode()).hexdigest()[:12]


def load_extract_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "extract.yaml").read_text(encoding="utf-8"))


def check_path(path: Path) -> Path:
    """Only generated documents may be sent to the free tier (Google may use the data)."""
    p = path.resolve()
    if not p.is_relative_to(SYNTHETIC_ROOT):
        raise PermissionError(
            f"refusing to send {path} to Gemini: only files under "
            f"{SYNTHETIC_ROOT} (synthetic documents) are allowed"
        )
    if p.suffix.lower() not in MIME:
        raise ValueError(f"unsupported file type: {p.suffix}")
    return p


class GeminiExtractor:
    name = "gemini"

    def __init__(self, model: str | None = None, use_cache: bool = True):
        cfg = load_extract_config()
        self.model = model or cfg["model"]
        limits = cfg["limits"].get(self.model, cfg["default_limits"])
        self.rpm, self.rpd = int(limits["rpm"]), int(limits["rpd"])
        self.temperature = float(cfg["temperature"])
        self.max_retries = int(cfg["max_retries"])
        self.use_cache = use_cache
        self.prompt_hash = prompt_hash()
        self.cache_dir = CACHE_ROOT / self.model / self.prompt_hash
        self.calls = 0
        self._last_call = 0.0
        self._client = None

    # --- plumbing -------------------------------------------------------------------------

    def client(self):
        if self._client is None:
            from google import genai

            load_dotenv()
            key = os.environ.get("GEMINI_API_KEY", "").strip()
            if not key:
                raise RuntimeError("GEMINI_API_KEY is not set in .env")
            self._client = genai.Client(api_key=key)
        return self._client

    def _usage_file(self) -> Path:
        return CACHE_ROOT / "usage" / f"{date.today().isoformat()}_{self.model}.json"

    def _used_today(self) -> int:
        f = self._usage_file()
        return json.loads(f.read_text())["requests"] if f.is_file() else 0

    def _count_request(self) -> None:
        f = self._usage_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"requests": self._used_today() + 1}))

    def _throttle(self) -> None:
        wait = 60.0 / self.rpm - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    # --- extraction -----------------------------------------------------------------------

    def raw(self, path: Path) -> dict:
        """Cached raw response for a file: {"parsed", "text", "usage", "model", ...}."""
        p = check_path(path)
        data = p.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        cache = self.cache_dir / f"{sha}.json"
        if self.use_cache and cache.is_file():
            return json.loads(cache.read_text(encoding="utf-8"))

        from google.genai import errors, types

        if self._used_today() >= self.rpd:
            raise QuotaExhausted(
                f"{self.model}: daily budget of {self.rpd} requests used "
                f"(config/extract.yaml); the cache resumes tomorrow"
            )
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            response_mime_type="application/json",
            response_schema=RDoc,
        )
        contents = [types.Part.from_bytes(data=data, mime_type=MIME[p.suffix.lower()]), PROMPT]
        for attempt in range(self.max_retries + 1):
            self._throttle()
            self._count_request()
            t0 = time.perf_counter()
            try:
                resp = self.client().models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                break
            except errors.APIError as exc:
                daily = exc.code == 429 and "PerDay" in str(exc)
                if daily:
                    raise QuotaExhausted(
                        f"{self.model}: Google reports the daily quota is used up"
                    ) from exc
                if exc.code in (429, 500, 503) and attempt < self.max_retries:
                    time.sleep(min(60, 5 * 2**attempt))
                    continue
                raise
        latency = time.perf_counter() - t0
        self.calls += 1
        usage = resp.usage_metadata
        record = {
            "file": p.relative_to(REPO_ROOT).as_posix(),
            "sha256": sha,
            "model": self.model,
            "model_version": getattr(resp, "model_version", None),
            "prompt_hash": self.prompt_hash,
            "latency_s": round(latency, 2),
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_token_count", None),
                "output_tokens": getattr(usage, "candidates_token_count", None),
                "thinking_tokens": getattr(usage, "thoughts_token_count", None),
                "total_tokens": getattr(usage, "total_token_count", None),
            },
            "text": resp.text,
        }
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
        return record

    def extract(self, path: Path) -> DeliveryNote | Invoice:
        record = self.raw(path)
        doc = to_document(RDoc.model_validate_json(record["text"]))
        if doc is None:
            raise NotADocument(f"{path.name}: Gemini says this is neither an invoice nor a BL")
        return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trimatch.extract.gemini")
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--model")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)
    ex = GeminiExtractor(model=args.model, use_cache=not args.no_cache)
    if args.list_models:
        for m in ex.client().models.list():
            if "generateContent" in (getattr(m, "supported_actions", None) or []):
                print(m.name.removeprefix("models/"), "|", m.display_name)
        return 0
    for f in args.files:
        doc = ex.extract(f)
        print(doc.model_dump_json(indent=1, exclude_none=True))
    print(f"API calls: {ex.calls} (model {ex.model}, prompt {ex.prompt_hash})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
