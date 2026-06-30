import http.client
import json
import logging
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Base class for Ollama client failures."""


class OllamaConnectionError(OllamaError):
    """Ollama could not be reached (DNS, tunnel, offline, refused)."""


class OllamaResponseError(OllamaError):
    """Ollama returned an invalid or incomplete response."""


class OllamaTimeoutError(OllamaError):
    """Ollama generation exceeded the configured timeout."""


class OllamaCancelledError(OllamaError):
    """The caller cancelled the request before completion."""


_RETRYABLE_REASONS = frozenset(
    {
        "timed out",
        "connection refused",
        "connection reset",
        "broken pipe",
        "name or service not known",
        "temporary failure in name resolution",
        "network is unreachable",
        "no route to host",
    }
)


def _reason_text(exc):
    if isinstance(exc, socket.timeout):
        return "timed out"
    if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
        return str(exc).lower()
    if isinstance(exc, URLError) and exc.reason is not None:
        return str(exc.reason).lower()
    if isinstance(exc, OSError):
        return str(exc).lower()
    return str(exc).lower()


def _is_retryable(exc):
    reason = _reason_text(exc)
    return any(fragment in reason for fragment in _RETRYABLE_REASONS)


def _parse_base_url(base_url):
    parsed = urlparse(base_url.rstrip("/"))
    if parsed.scheme not in {"http", "https"}:
        raise OllamaConnectionError(f"Unsupported Ollama URL scheme: {parsed.scheme or 'missing'}")
    host = parsed.hostname
    if not host:
        raise OllamaConnectionError(f"Invalid Ollama URL: {base_url}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path_prefix = parsed.path.rstrip("/")
    return parsed.scheme, host, port, path_prefix


def _chat_with_http_client(scheme, host, port, path, payload, connect_timeout, generation_timeout, cancel_check):
    if cancel_check and cancel_check():
        raise OllamaCancelledError("Ollama request cancelled before send.")

    connection_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    conn = connection_cls(host, port, timeout=connect_timeout)
    try:
        conn.request("POST", path, body=payload, headers={"Content-Type": "application/json"})
        if cancel_check and cancel_check():
            raise OllamaCancelledError("Ollama request cancelled after connect.")

        if conn.sock is not None:
            conn.sock.settimeout(generation_timeout)

        response = conn.getresponse()
        raw = response.read()
        if response.status >= 400:
            detail = raw.decode("utf-8", errors="replace")
            raise OllamaResponseError(f"Ollama request failed ({response.status}): {detail}")

        if cancel_check and cancel_check():
            raise OllamaCancelledError("Ollama request cancelled after response.")

        if not raw:
            raise OllamaResponseError("Ollama returned an empty response body.")

        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise OllamaResponseError("Ollama returned invalid JSON.") from exc

        message = body.get("message") or {}
        content = message.get("content")
        if content is None:
            raise OllamaResponseError("Ollama response did not include message content.")
        return content
    except socket.timeout as exc:
        if generation_timeout is not None:
            raise OllamaTimeoutError(f"Ollama generation exceeded {generation_timeout}s timeout.") from exc
        raise OllamaConnectionError(f"Ollama connection timed out after {connect_timeout}s.") from exc
    except OllamaError:
        raise
    except (http.client.HTTPException, OSError) as exc:
        if _is_retryable(exc):
            raise OllamaConnectionError(f"Could not reach Ollama at {scheme}://{host}:{port}: {exc}") from exc
        raise OllamaResponseError(f"Ollama request failed: {exc}") from exc
    finally:
        conn.close()


def generate_chat(
    base_url,
    model,
    messages,
    *,
    connect_timeout=10,
    generation_timeout=None,
    max_retries=2,
    retry_backoff=1.0,
    cancel_check=None,
    logger_obj=None,
):
    """Send a non-streaming chat request to Ollama with defensive network handling."""
    log = logger_obj or logger
    scheme, host, port, path_prefix = _parse_base_url(base_url)
    path = f"{path_prefix}/api/chat" if path_prefix else "/api/chat"
    payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode("utf-8")
    attempts = max_retries + 1
    last_error = None

    for attempt in range(1, attempts + 1):
        if cancel_check and cancel_check():
            raise OllamaCancelledError("Ollama request cancelled before attempt.")
        try:
            log.info(
                "Ollama chat attempt %s/%s model=%s connect_timeout=%s generation_timeout=%s",
                attempt,
                attempts,
                model,
                connect_timeout,
                generation_timeout,
            )
            return _chat_with_http_client(
                scheme,
                host,
                port,
                path,
                payload,
                connect_timeout,
                generation_timeout,
                cancel_check,
            )
        except OllamaCancelledError:
            raise
        except (OllamaConnectionError, OllamaTimeoutError) as exc:
            last_error = exc
            log.warning("Ollama attempt %s/%s failed: %s", attempt, attempts, exc)
            if attempt >= attempts or not _is_retryable(exc):
                raise
            time.sleep(retry_backoff * attempt)
        except OllamaResponseError as exc:
            log.error("Ollama response error: %s", exc)
            raise

    raise last_error or OllamaConnectionError("Ollama request failed after retries.")


def probe_connection(base_url, connect_timeout=10):
    """Quick connectivity check without waiting for model generation."""
    scheme, host, port, path_prefix = _parse_base_url(base_url)
    path = f"{path_prefix}/api/tags" if path_prefix else "/api/tags"
    url = f"{scheme}://{host}:{port}{path}"
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=connect_timeout) as response:
            response.read(1)
    except HTTPError as exc:
        if exc.code < 500:
            return True
        raise OllamaConnectionError(f"Ollama health check failed ({exc.code}).") from exc
    except (URLError, socket.timeout, OSError) as exc:
        raise OllamaConnectionError(f"Could not reach Ollama at {base_url}: {exc}") from exc
    return True
