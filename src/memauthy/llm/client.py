"""JSON-mode LLM clients: a local Ollama client and a persistent cache.

* :class:`OllamaClient` talks to a **local** Ollama server (``/api/chat``) with explicit, seeded,
  deterministic options. It refuses non-local URLs so that no paid or remote API is used by
  accident (ADR-0005).
* :class:`CachedClient` memoizes responses on disk (JSONL, keyed by model + prompt version +
  messages), which makes long runs resumable and deduplicates identical blocks across samples.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DEFAULT_OLLAMA_URL = "http://localhost:11434"


@dataclass(frozen=True)
class LLMResponse:
    data: dict[str, Any] | None  # parsed JSON object, None if the output was not valid JSON
    raw: str
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    cached: bool = False
    error: str | None = None


@dataclass
class UsageStats:
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    errors: int = 0

    def add(self, r: LLMResponse) -> None:
        if r.cached:
            self.cache_hits += 1
            return
        self.calls += 1
        self.input_tokens += r.input_tokens
        self.output_tokens += r.output_tokens
        self.seconds += r.seconds
        self.errors += r.error is not None


class JSONLLMClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str) -> LLMResponse: ...


@dataclass
class OllamaClient:
    """Deterministic JSON chat completion against a local Ollama server."""

    model: str
    base_url: str = field(
        default_factory=lambda: os.environ.get("MEMAUTHY_OLLAMA_URL", DEFAULT_OLLAMA_URL)
    )
    temperature: float = 0.0
    seed: int = 20261120
    num_predict: int = 160
    timeout: float = 300.0

    def __post_init__(self) -> None:
        host = urlparse(self.base_url).hostname
        if host not in LOCAL_HOSTS:
            raise ValueError(f"OllamaClient only talks to a local server, got {self.base_url!r}")

    def complete_json(self, system: str, user: str) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": "json",
            "stream": False,
            "think": False,
            "options": {
                "temperature": self.temperature,
                "seed": self.seed,
                "num_predict": self.num_predict,
            },
        }
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return LLMResponse(None, "", seconds=time.perf_counter() - start, error=repr(exc))
        seconds = time.perf_counter() - start
        raw = payload.get("message", {}).get("content", "")
        try:
            data = json.loads(raw)
            data = data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            data = None
        return LLMResponse(
            data,
            raw,
            input_tokens=int(payload.get("prompt_eval_count") or 0),
            output_tokens=int(payload.get("eval_count") or 0),
            seconds=seconds,
            error=None if data is not None else "invalid JSON output",
        )


@dataclass
class CachedClient:
    """Disk-backed memoization. Errors are not cached, so failed calls are retried next run."""

    inner: JSONLLMClient
    cache_path: Path
    prompt_version: str
    stats: UsageStats = field(default_factory=UsageStats)
    _cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.cache_path = Path(self.cache_path)
        if self.cache_path.is_file():
            for line in self.cache_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self._cache[entry["key"]] = entry

    @property
    def model(self) -> str:
        return self.inner.model

    def key(self, system: str, user: str) -> str:
        payload = json.dumps([self.inner.model, self.prompt_version, system, user])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def complete_json(self, system: str, user: str) -> LLMResponse:
        k = self.key(system, user)
        hit = self._cache.get(k)
        if hit is not None:
            r = LLMResponse(hit["data"], hit["raw"], cached=True)
            self.stats.add(r)
            return r
        r = self.inner.complete_json(system, user)
        self.stats.add(r)
        if r.error is None:
            entry = {
                "key": k,
                "model": self.inner.model,
                "prompt_version": self.prompt_version,
                "data": r.data,
                "raw": r.raw,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "seconds": round(r.seconds, 4),
            }
            with self._lock:
                self._cache[k] = entry
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                with self.cache_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return r
