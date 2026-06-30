from dataclasses import dataclass
from importlib import resources
from pathlib import Path

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


class DexService:
    def __init__(self, app):
        self.app = app
        self.provider = LocalPlaceholderProvider()
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
