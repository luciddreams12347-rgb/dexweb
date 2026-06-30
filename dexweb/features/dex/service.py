import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from urllib import error, request

from flask import current_app


DEFAULT_PROMPT_RESOURCE = "default_system_prompt.txt"


@dataclass
class DexRequest:
    prompt: str
    messages: list | None = None
    context: dict | None = None
    user: str | None = None


class LocalPlaceholderProvider:
    name = "local-placeholder"

    def generate(self, request, system_prompt):
        return (
            "DEX received the request and returned a structured response. "
            "No external AI provider is configured yet."
        )


class OllamaProvider:
    name = "ollama"

    def __init__(self, app):
        self.app = app

    def generate(self, dex_request, system_prompt):
        base_url = self.app.config.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        model = self.app.config.get("DEX_MODEL") or "qwen2.5:7b"
        messages = [{"role": "system", "content": system_prompt}]

        for item in dex_request.messages or []:
            role = item.get("role")
            content = item.get("content")
            if role and content is not None:
                messages.append({"role": role, "content": content})

        user_content = dex_request.prompt or ""
        if dex_request.context:
            context_text = json.dumps(dex_request.context, sort_keys=True)
            user_content = f"{user_content}\n\nContext:\n{context_text}".strip()

        if user_content:
            messages.append({"role": "user", "content": user_content})

        payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode("utf-8")
        api_request = request.Request(
            f"{base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(api_request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama request failed ({exc.code}): {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach Ollama at {base_url}: {exc.reason}") from exc

        message = body.get("message") or {}
        content = message.get("content")
        if content is None:
            raise RuntimeError("Ollama response did not include message content.")
        return content


def _create_provider(app):
    provider_name = app.config.get("DEX_PROVIDER", "local-placeholder")
    if provider_name == "ollama":
        return OllamaProvider(app)
    return LocalPlaceholderProvider()


class DexService:
    def __init__(self, app):
        self.app = app
        self.provider = _create_provider(app)
        self.runtime_state = {}
        self._system_prompt = None

    def get_system_prompt(self):
        if self._system_prompt is None:
            self.reload()
        return self._system_prompt

    def save_system_prompt(self, prompt):
        prompt_path = self._prompt_path()
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        self._system_prompt = prompt

    def import_system_prompt(self, file_storage):
        raw = file_storage.read()
        prompt = raw.decode("utf-8-sig").strip()
        self.save_system_prompt(prompt)
        return prompt

    def export_system_prompt(self):
        return self.get_system_prompt()

    def reset(self):
        self.runtime_state.clear()
        self.provider = _create_provider(self.app)
        self.reload()

    def reload(self):
        prompt_path = self._prompt_path()
        if prompt_path.exists():
            self._system_prompt = prompt_path.read_text(encoding="utf-8")
        else:
            self._system_prompt = self._default_system_prompt()

    def process(self, prompt=None, messages=None, context=None, user=None):
        request = DexRequest(prompt=prompt or "", messages=messages or [], context=context or {}, user=user)
        system_prompt = self.get_system_prompt()
        content = self.provider.generate(request, system_prompt)
        return {
            "ok": True,
            "service": "DEX",
            "provider": self.provider.name,
            "model": current_app.config.get("DEX_MODEL", "none"),
            "content": content,
            "request": {
                "prompt": request.prompt,
                "messages": request.messages,
                "context": request.context,
                "user": request.user,
            },
            "metadata": {
                "system_prompt_source": str(self._prompt_path()) if self._prompt_path().exists() else "package-default",
                "supports_future_providers": True,
            },
        }

    def _prompt_path(self):
        configured = current_app.config.get("DEX_SYSTEM_PROMPT_PATH")
        if configured:
            return Path(configured)
        return Path(current_app.instance_path) / "dex_system_prompt.txt"

    def _default_system_prompt(self):
        package = "dexweb.features.dex"
        return resources.files(package).joinpath(DEFAULT_PROMPT_RESOURCE).read_text(encoding="utf-8")


def get_dex_service():
    if "dex_service" not in current_app.extensions:
        current_app.extensions["dex_service"] = DexService(current_app._get_current_object())
    return current_app.extensions["dex_service"]


def get_conversation(session):
    return session.setdefault("dex_messages", [])


def record_exchange(session, user_content, assistant_content):
    history = get_conversation(session)
    history.extend(
        [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]
    )
    session.modified = True


def clear_conversation(session):
    session.pop("dex_messages", None)
    session.modified = True
