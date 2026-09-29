"""The vision model: one call per image returns every metadata field as JSON.

Two backends with the same prompt and schema: a local Qwen3-VL through Ollama (default; nothing leaves the PC)
and Claude through the Anthropic API. Answers are cached per picture, prompt and context, so a re-run costs
nothing and an edited brief only redoes the images it affects."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from smp import machine, store

log = logging.getLogger(__name__)
PROMPT_VERSION = "3"
LANGUAGES = {"en": "English", "sv": "Swedish"}


class ImageMetadata(BaseModel):
    title: str = Field(description="3-8 words naming what the image shows. No ending period.")
    caption: str = Field(description="1-3 sentences: what the image shows, then the context from the brief that "
                                     "applies to it.")
    alt_text: str = Field(description="Alt text for screen readers: what is visible, 1-2 sentences, under 250 "
                                      "characters.")
    keywords: list[str] = Field(description="6-15 lowercase keywords.")
    minors_visible: bool = Field(description="Children or young teenagers are visible.")
    content_warning: str = Field(description="Short note if the image shows something distressing or private "
                                             "(human remains, injury, grief, confidential work information), "
                                             "otherwise an empty string.")


SYSTEM = """You write metadata for a photographer's archive of finished images: photos, phone pictures, \
screenshots and slides. The metadata is used for search, for alt text on social media and the web, and by an \
assistant that plans social media posts.

With each image you get a brief from the photographer about the set or project, facts from the file, and \
sometimes text the photographer already wrote for this image.

Rules:
- Statements about what the image shows come only from the image itself.
- Context (project, place names, events, purpose, organisations) comes only from the brief, the file facts \
or the photographer's own text. Use it only where it plausibly applies to this image. Never invent details, \
dates, names or numbers.
- The photographer's own text for this image is true: keep its facts and never contradict it.
- Never name people, even when the brief or the photographer's text names them. Describe them generically, \
for example "a hiker in a red jacket" or "two children". Never state or guess anyone's ethnicity, religion, \
health, disability, sexual orientation, political views, legal status or how people are related.
- Plain, factual language. No hype, no hashtags, no emoji, no em dashes.
- The alt text describes only what is visible, without "image of" or "photo of", and quotes short visible \
text exactly. It gives no background the image doesn't show.
- Keywords: subjects, setting, activity, landscape and place names from the brief or file facts. No people's \
names, no words like "photo" or "image".
- Write every text field in {language}. Keywords too."""


def build_user(facts: list[str], brief_context: str, own_text: dict[str, object]) -> str:
    parts = ["File facts:\n" + "\n".join(f"- {f}" for f in facts)]
    parts.append("Brief from the photographer:\n" + (brief_context.strip() or "(no brief for this folder: "
                                                       "describe only what is visible)"))
    own = [f"- {k}: {', '.join(v) if isinstance(v, list) else v}" for k, v in own_text.items() if v]
    if own:
        parts.append("Text the photographer already wrote for this image:\n" + "\n".join(own))
    parts.append("Write the metadata for this image as JSON.")
    return "\n\n".join(parts)


def clean(meta: dict) -> dict:
    def text(s) -> str:
        s = " ".join(str(s or "").split())
        return s.replace(" — ", ", ").replace("—", "-").replace(" – ", ", ").strip()

    out = dict(meta)
    for k in ("title", "caption", "alt_text", "content_warning"):
        out[k] = text(out.get(k))
    out["title"] = out["title"].rstrip(".")
    seen, kws = set(), []
    for k in out.get("keywords") or []:
        k = text(k).lower().strip(" #.")
        if k and k not in seen:
            seen.add(k)
            kws.append(k)
    out["keywords"] = kws[:20]
    if out["content_warning"].lower().strip(".") in ("none", "no", "n/a", "na", "nothing"):
        out["content_warning"] = ""
    return out


class VLMError(RuntimeError):
    pass


# ---- backends ------------------------------------------------------------------------------------------------

_ollama_http: httpx.Client | None = None


def _http() -> httpx.Client:
    """One connection pool for every Ollama call (status checks run every second or two while downloading)."""
    global _ollama_http
    if _ollama_http is None:
        _ollama_http = httpx.Client(timeout=600, trust_env=False)
    return _ollama_http


class OllamaBackend:
    name = "ollama"

    def __init__(self, s: dict):
        self.url = s["ollama_url"].rstrip("/")
        self.chosen = s.get("ollama_model") or ""       # empty: the best one for this GPU
        self.model = self.chosen
        self.exe = s.get("ollama_exe") or ""
        self.models_dir = s.get("ollama_models_dir") or ""
        self.image_px = int(s.get("ollama_image_px") or 1024)
        self.http = _http()

    def alive(self) -> bool:
        try:
            return self.http.get(f"{self.url}/api/version", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def installed(self) -> list[str]:
        try:
            return [m.get("name") for m in self.http.get(f"{self.url}/api/tags", timeout=10).json().get("models", [])]
        except (httpx.HTTPError, ValueError):
            return []

    def resolve(self) -> str:
        """The model to use: the chosen one, or the best installed one that fits the GPU, or the one to download."""
        self.model = self.chosen or machine.pick_model(self.installed())
        return self.model

    def has_model(self) -> bool:
        names = self.installed()
        return self.model in names or f"{self.model}:latest" in names

    def start(self) -> None:
        if self.alive():
            return
        if not self.exe or not os.path.exists(self.exe):
            raise VLMError("Ollama isn't installed. Run the installer again, install Ollama from ollama.com, "
                           "or switch to the Claude API")
        u = urlparse(self.url)
        if u.hostname not in ("127.0.0.1", "localhost"):
            raise VLMError(f"{self.url} isn't on this computer, so SMP can't start it")
        env = dict(os.environ, OLLAMA_HOST=f"127.0.0.1:{u.port or 11434}", OLLAMA_NO_CLOUD="1",
                   OLLAMA_FLASH_ATTENTION="1", OLLAMA_KV_CACHE_TYPE="q8_0", OLLAMA_KEEP_ALIVE="30m")
        if self.models_dir:
            os.makedirs(self.models_dir, exist_ok=True)
            env["OLLAMA_MODELS"] = self.models_dir
        kw = {"creationflags": 0x08000000 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen([self.exe, "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, **kw)
        deadline = time.time() + 60
        while time.time() < deadline and not self.alive():
            time.sleep(0.5)
        if not self.alive():
            raise VLMError("Ollama didn't start")

    def ensure(self) -> None:
        self.start()
        self.resolve()
        if not self.has_model():
            raise VLMError(f"The vision model {self.model} isn't downloaded yet: open Setup to download it")

    def pull(self, progress) -> None:
        """Download self.model, calling progress(status, done_bytes, total_bytes) as it goes."""
        self.start()
        with self.http.stream("POST", f"{self.url}/api/pull", json={"model": self.model, "stream": True},
                              timeout=None) as r:
            if r.status_code != 200:
                raise VLMError(f"Ollama {r.status_code} while downloading {self.model}")
            for line in r.iter_lines():
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("error"):
                    raise VLMError(f"Download failed: {msg['error']}")
                progress(msg.get("status", ""), int(msg.get("completed") or 0), int(msg.get("total") or 0))
        if not self.has_model():
            raise VLMError(f"{self.model} still isn't installed after the download")

    def _chat(self, system: str, user: str, images: list[str], schema: dict | None) -> str:
        body = {"model": self.model, "stream": False, "keep_alive": "30m",
                "options": {"temperature": 0, "num_ctx": 16384},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user, "images": images}]}
        if schema:
            body["format"] = schema
        r = self.http.post(f"{self.url}/api/chat", json=body)
        if r.status_code != 200:
            raise VLMError(f"Ollama {r.status_code}: {r.text[:300]}")
        return (r.json().get("message") or {}).get("content", "")

    def describe(self, system: str, user: str, image_b64: str) -> dict:
        content = self._chat(system, user, [image_b64], ImageMetadata.model_json_schema())
        try:
            return ImageMetadata.model_validate_json(_json_part(content)).model_dump()
        except ValueError as e:
            raise VLMError(f"unreadable answer from {self.model}: {e}") from e

    def write(self, system: str, user: str, images_b64: list[str]) -> str:
        return self._chat(system, user, images_b64, None).strip()


class ClaudeBackend:
    name = "claude"

    def __init__(self, s: dict):
        import anthropic

        self.anthropic = anthropic
        self.model = s["claude_model"]
        self.effort = s.get("claude_effort") or "medium"
        self.image_px = int(s.get("claude_image_px") or 1568)
        self.api_key = s.get("claude_api_key") or ""
        self.client = None

    def ensure(self) -> None:
        # a key saved in Setup, else whatever the SDK finds (ANTHROPIC_API_KEY, an `ant auth login` profile);
        # whether it's valid shows on the first call
        try:
            self.client = self.anthropic.Anthropic(api_key=self.api_key) if self.api_key else self.anthropic.Anthropic()
        except self.anthropic.AnthropicError as e:
            raise VLMError("Claude: no API key. Add one in Setup, or set ANTHROPIC_API_KEY") from e

    # Refusals are re-run on Anthropic's recommended fallback model instead of failing the image.
    _fallback = {"extra_headers": {"anthropic-beta": "server-side-fallback-2026-07-01"},
                 "extra_body": {"fallbacks": "default"}}

    def _content(self, user: str, images_b64: list[str]) -> list[dict]:
        return [*({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}
                  for b in images_b64), {"type": "text", "text": user}]

    def _call(self, fn):
        a = self.anthropic
        try:
            r = fn()
        except a.AuthenticationError as e:
            raise VLMError("Claude: no valid API key. Add one in Setup, or set ANTHROPIC_API_KEY") from e
        except a.RateLimitError as e:
            raise VLMError("Claude: rate limited, try again in a minute") from e
        except a.APIStatusError as e:
            raise VLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except a.APIConnectionError as e:
            raise VLMError("Claude: can't reach the API") from e
        if r.stop_reason == "refusal":
            raise VLMError("Claude declined to describe this image")
        return r

    def describe(self, system: str, user: str, image_b64: str) -> dict:
        r = self._call(lambda: self.client.messages.parse(
            model=self.model, max_tokens=16000, system=system, output_format=ImageMetadata,
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": self._content(user, [image_b64])}], **self._fallback))
        if r.parsed_output is None:
            raise VLMError("Claude returned no metadata")
        return r.parsed_output.model_dump()

    def write(self, system: str, user: str, images_b64: list[str]) -> str:
        r = self._call(lambda: self.client.messages.create(
            model=self.model, max_tokens=16000, system=system, output_config={"effort": self.effort},
            messages=[{"role": "user", "content": self._content(user, images_b64)}], **self._fallback))
        return "".join(b.text for b in r.content if b.type == "text").strip()


def backend(s: dict, name: str | None = None):
    return ClaudeBackend(s) if (name or s.get("backend")) == "claude" else OllamaBackend(s)


def _json_part(content: str) -> str:
    content = content.strip()
    if content.startswith("{"):
        return content
    m = re.search(r"\{.*\}", content, re.S)
    return m.group(0) if m else content


# ---- calls ---------------------------------------------------------------------------------------------------

def describe(be, pixel_id: str, image_b64_fn, facts: list[str], brief_context: str, own_text: dict,
             language: str) -> tuple[dict, bool]:
    """(metadata, from_cache). image_b64_fn is only called when the answer isn't cached."""
    system = SYSTEM.format(language=LANGUAGES.get(language, "English"))
    user = build_user(facts, brief_context, own_text)
    key = hashlib.sha1(json.dumps([PROMPT_VERSION, be.name, be.model, pixel_id, system, user],
                                  ensure_ascii=False).encode("utf-8")).hexdigest()
    hit = store.cache_get(key)
    if hit is not None:
        return clean(hit), True
    meta = be.describe(system, user, image_b64_fn(be.image_px))
    store.cache_put(key, meta, be.model)
    return clean(meta), False


DRAFT_SYSTEM = """You help a photographer write a short brief for a folder of finished images. The brief tells \
an assistant what the set is about, so it can write accurate captions later.

Write 3-6 plain sentences in {language}: what the set or project is, where and when (only if the folder \
names, file facts or existing captions say so), what kind of images it holds, and anything worth knowing for \
captions. Base it only on what you are given and what the sample images show. Put [check] after anything you \
are unsure of. Don't name people. No headings, no lists, no em dashes."""


def draft_brief(be, folder_path: str, facts: list[str], captions: list[str], images_b64: list[str],
                language: str) -> str:
    user = [f"Folder: {folder_path}", "File facts from sample images:\n" + "\n".join(f"- {f}" for f in facts)]
    if captions:
        user.append("Captions already in some of the files:\n" + "\n".join(f"- {c}" for c in captions))
    user.append("Write the brief.")
    text = be.write(DRAFT_SYSTEM.format(language=LANGUAGES.get(language, "English")), "\n\n".join(user),
                    images_b64)
    return clean({"caption": text})["caption"]
