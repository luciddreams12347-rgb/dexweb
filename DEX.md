# DEX Central AI Service

DEX is the central intelligence service for DexWeb. It accepts prompts/messages through one reusable service, loads a configurable system prompt, and returns structured responses. The current provider is a local placeholder so no API keys or external secrets are required.

## Files Created

- `dexweb/features/dex/__init__.py`: DEX feature package marker.
- `dexweb/features/dex/default_system_prompt.txt`: packaged default DEX system prompt.
- `dexweb/features/dex/service.py`: centralized DEX service, prompt loading/saving/import/export/reset, provider placeholder, structured response contract.
- `tests/test_dex_service.py`: service and admin integration tests.
- `DEX.md`: this documentation.

## Files Modified

- `dexweb/config.py`: added `DEX_SYSTEM_PROMPT_PATH`, `DEX_PROVIDER`, and `DEX_MODEL`.
- `dexweb/features/admin/routes.py`: added DEX prompt save/import/export/reset handling inside the existing admin system.
- `dexweb/templates/admin.html`: added DEX controls to the existing admin page.
- `.env.example`: documented the optional DEX environment variables.
- `README.md`: links to DEX documentation and describes the feature at a high level.

## How DEX Works

Future features should use:

```python
from dexweb.features.dex.service import get_dex_service

response = get_dex_service().process(
    prompt="Summarize this document",
    messages=[],
    context={"source": "future-document-feature"},
    user="username",
)
```

The response is a dictionary with:

- `ok`: request success flag.
- `service`: always `DEX`.
- `provider`: active provider name.
- `model`: configured model name.
- `content`: provider output.
- `request`: normalized prompt/messages/context/user input.
- `metadata`: prompt source and future-provider compatibility flags.

## System Prompt

The packaged default prompt lives at:

```text
dexweb/features/dex/default_system_prompt.txt
```

Admins can edit the active prompt from the existing admin panel. Edited prompts are saved to:

1. `DEX_SYSTEM_PROMPT_PATH`, if configured.
2. Otherwise, `instance/dex_system_prompt.txt`.

If no saved prompt exists, DEX uses the packaged default.

## Admin DEX Controls

Open `/admin_login`, sign in with the existing admin password, then open `/admin`.

Admins can:

- View the current system prompt.
- Edit and save the prompt.
- Import a `.txt` prompt file.
- Export/download the active prompt from `/admin/dex/system-prompt.txt`.
- Reset DEX without restarting Flask.

Reset reloads configuration, reloads the active prompt, and clears temporary runtime state.

## Environment Variables

- `DEX_SYSTEM_PROMPT_PATH`: optional writable file path for the active prompt.
- `DEX_PROVIDER`: future provider selection. Current value is `local-placeholder`.
- `DEX_MODEL`: future model name. Empty is fine for `local-placeholder`.

Do not store AI API keys in code. Add future provider keys as environment variables only.

## Adding Future AI Providers

Add a provider class that implements the same shape as `LocalPlaceholderProvider` in `dexweb/features/dex/service.py`:

```python
class NewProvider:
    name = "new-provider"

    def generate(self, request, system_prompt):
        return "provider response"
```

Then choose the provider based on `current_app.config["DEX_PROVIDER"]`. Keep provider-specific API keys in environment variables and load them through `dexweb/config.py`.

## Future Feature Integration

DEX is intended to support future features such as:

- Knowledge bases
- Document uploads
- Document generation
- User memory
- Archive retrieval
- Administrative AI tools

Those features should call `get_dex_service().process(...)` instead of creating separate AI clients.
