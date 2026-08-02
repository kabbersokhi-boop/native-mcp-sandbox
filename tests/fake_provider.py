"""Deterministic loopback-only provider double used by Phase 10.1 tests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import time
from typing import ClassVar

from agent.native_mcp_agent.endpoint_policy import validate_fake_bind_host, validate_fake_loopback_endpoint


class FakeCase(str, Enum):
    FINAL = "final"
    ONE_CALL = "one_call"
    MULTIPLE_CALLS = "multiple_calls"
    MALFORMED_JSON = "malformed_json"
    DUPLICATE_KEYS = "duplicate_keys"
    TRUNCATED = "truncated"
    INVALID_CONTENT_TYPE = "invalid_content_type"
    MISSING_CONTENT_TYPE = "missing_content_type"
    OVERSIZED = "oversized"
    DELAYED = "delayed"
    READ_TIMEOUT = "read_timeout"
    CONNECTION_CLOSE = "connection_close"
    STATUS_400 = "status_400"
    STATUS_401 = "status_401"
    STATUS_403 = "status_403"
    STATUS_404 = "status_404"
    STATUS_408 = "status_408"
    STATUS_413 = "status_413"
    STATUS_422 = "status_422"
    STATUS_409 = "status_409"
    STATUS_429 = "status_429"
    STATUS_500 = "status_500"
    STATUS_502 = "status_502"
    STATUS_503 = "status_503"
    STATUS_504 = "status_504"
    RETRY_AFTER = "retry_after"
    RETRY_AFTER_INTEGER = "retry_after_integer"
    RETRY_AFTER_DECIMAL = "retry_after_decimal"
    MALFORMED_RETRY_AFTER = "malformed_retry_after"
    EXCESSIVE_RETRY_AFTER = "excessive_retry_after"
    REDIRECT = "redirect"
    REDIRECT_301 = "redirect_301"
    REDIRECT_302 = "redirect_302"
    REDIRECT_303 = "redirect_303"
    REDIRECT_307 = "redirect_307"
    REDIRECT_308 = "redirect_308"
    RETRY_SUCCESS = "retry_success"
    MALFORMED_LENGTH = "malformed_length"
    NEGATIVE_LENGTH = "negative_length"
    OVERSIZED_DECLARED_LENGTH = "oversized_declared_length"
    UNEXPECTED_FIELDS = "unexpected_fields"
    MIXED = "mixed"
    DUPLICATE_CALL_IDS = "duplicate_call_ids"
    MALFORMED_ARGUMENTS = "malformed_arguments"
    EXCESSIVE_PROPOSALS = "excessive_proposals"


@dataclass
class FakeProviderServer:
    case: FakeCase
    host: str = "127.0.0.1"
    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None
    request_count: int = 0
    request_bodies: list[bytes] | None = None
    request_headers: list[dict[str, str]] | None = None

    def __enter__(self) -> "FakeProviderServer":
        validate_fake_bind_host(self.host)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "Phase10Fake/1"
            sys_version = ""

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length)
                owner.request_count += 1
                if owner.request_bodies is None:
                    owner.request_bodies = []
                owner.request_bodies.append(body)
                if owner.request_headers is None:
                    owner.request_headers = []
                owner.request_headers.append({key.lower(): value for key, value in self.headers.items()})
                status, response, content_type, declared, delay, close = owner.script()
                if delay:
                    time.sleep(delay)
                if close:
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self.connection.close()
                    return
                self.send_response(status)
                if content_type is not None:
                    self.send_header("Content-Type", content_type)
                if owner.case == FakeCase.RETRY_AFTER:
                    self.send_header("Retry-After", "0")
                elif owner.case == FakeCase.RETRY_AFTER_INTEGER and owner.request_count == 1:
                    self.send_header("Retry-After", "1")
                elif owner.case == FakeCase.RETRY_AFTER_DECIMAL and owner.request_count == 1:
                    self.send_header("Retry-After", "0.5")
                elif owner.case == FakeCase.MALFORMED_RETRY_AFTER:
                    self.send_header("Retry-After", "not-a-delay")
                elif owner.case == FakeCase.EXCESSIVE_RETRY_AFTER:
                    self.send_header("Retry-After", "99")
                if owner.case in {FakeCase.REDIRECT, FakeCase.REDIRECT_301, FakeCase.REDIRECT_302, FakeCase.REDIRECT_303, FakeCase.REDIRECT_307, FakeCase.REDIRECT_308}:
                    self.send_header("Location", "https://provider.invalid/redirect")
                self.send_header("Content-Length", str(declared if declared is not None else len(response)))
                self.end_headers()
                try:
                    self.wfile.write(response)
                    self.wfile.flush()
                except BrokenPipeError:
                    pass
                if declared is not None and declared != len(response):
                    self.close_connection = True

        self.request_bodies = []
        self.request_headers = []
        self._server = ThreadingHTTPServer((self.host, 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="phase10-fake-provider", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None

    @property
    def endpoint(self) -> str:
        if self._server is None:
            raise RuntimeError("fake provider is not running")
        return f"http://{self.host}:{self._server.server_port}/v1/chat/completions"

    def validated_endpoint(self):
        return validate_fake_loopback_endpoint(self.endpoint, allow_loopback_http=True)

    def script(self) -> tuple[int, bytes, str | None, int | None, float, bool]:
        case = self.case
        final = b'{"message":{"role":"assistant","content":"synthetic guidance"}}'
        one = b'{"toolCalls":[{"id":"call-1","name":"logs.search","arguments":"{\\"query\\":\\"ERROR\\"}"}]}'
        multiple = b'{"toolCalls":[{"id":"call-1","name":"logs.search","arguments":"{\\"query\\":\\"ERROR\\"}"},{"id":"call-2","name":"logs.tail","arguments":"{\\"lines\\":3}"}]}'
        if case == FakeCase.FINAL:
            return 200, final, "application/json", None, 0.0, False
        if case == FakeCase.ONE_CALL:
            return 200, one, "application/json", None, 0.0, False
        if case == FakeCase.MULTIPLE_CALLS:
            return 200, multiple, "application/json", None, 0.0, False
        if case == FakeCase.MALFORMED_JSON:
            return 200, b"{", "application/json", None, 0.0, False
        if case == FakeCase.DUPLICATE_KEYS:
            return 200, b'{"message":{"role":"assistant","content":"a"},"message":{"role":"assistant","content":"b"}}', "application/json", None, 0.0, False
        if case == FakeCase.TRUNCATED:
            return 200, final[:-3], "application/json", len(final), 0.0, False
        if case == FakeCase.INVALID_CONTENT_TYPE:
            return 200, final, "text/plain", None, 0.0, False
        if case == FakeCase.MISSING_CONTENT_TYPE:
            return 200, final, None, None, 0.0, False
        if case == FakeCase.OVERSIZED:
            return 200, b"x" * 70_000, "application/json", None, 0.0, False
        if case == FakeCase.DELAYED:
            return 200, final, "application/json", None, 0.15, False
        if case == FakeCase.READ_TIMEOUT:
            return 200, final, "application/json", None, 1.0, False
        if case == FakeCase.CONNECTION_CLOSE:
            return 200, b"", "application/json", None, 0.0, True
        if case == FakeCase.RETRY_SUCCESS:
            if self.request_count == 1:
                return 503, b'{"error":"bounded"}', "application/json", None, 0.0, False
            return 200, final, "application/json", None, 0.0, False
        if case in {FakeCase.RETRY_AFTER_INTEGER, FakeCase.RETRY_AFTER_DECIMAL}:
            if self.request_count == 1:
                return 429, b'{"error":"bounded"}', "application/json", None, 0.0, False
            return 200, final, "application/json", None, 0.0, False
        if case == FakeCase.MALFORMED_LENGTH:
            return 200, final, "application/json", "not-a-length", 0.0, False
        if case == FakeCase.NEGATIVE_LENGTH:
            return 200, final, "application/json", -1, 0.0, False
        if case == FakeCase.OVERSIZED_DECLARED_LENGTH:
            return 200, final, "application/json", 999999, 0.0, False
        status_cases = {
            FakeCase.STATUS_400: 400, FakeCase.STATUS_401: 401, FakeCase.STATUS_403: 403,
            FakeCase.STATUS_404: 404, FakeCase.STATUS_408: 408, FakeCase.STATUS_413: 413,
            FakeCase.STATUS_422: 422, FakeCase.STATUS_409: 409, FakeCase.STATUS_429: 429, FakeCase.STATUS_500: 500,
            FakeCase.STATUS_502: 502, FakeCase.STATUS_503: 503, FakeCase.STATUS_504: 504,
        }
        if case in status_cases:
            return status_cases[case], b'{"error":"bounded"}', "application/json", None, 0.0, False
        if case in {FakeCase.RETRY_AFTER, FakeCase.MALFORMED_RETRY_AFTER, FakeCase.EXCESSIVE_RETRY_AFTER}:
            return 429, b'{"error":"bounded"}', "application/json", None, 0.0, False
        redirect_cases = {
            FakeCase.REDIRECT: 302, FakeCase.REDIRECT_301: 301, FakeCase.REDIRECT_302: 302,
            FakeCase.REDIRECT_303: 303, FakeCase.REDIRECT_307: 307, FakeCase.REDIRECT_308: 308,
        }
        if case in redirect_cases:
            return redirect_cases[case], b"", "text/plain", None, 0.0, False
        if case == FakeCase.UNEXPECTED_FIELDS:
            return 200, b'{"message":{"role":"assistant","content":"a"},"extra":1}', "application/json", None, 0.0, False
        if case == FakeCase.MIXED:
            return 200, b'{"message":{"role":"assistant","content":"a"},"toolCalls":[]}', "application/json", None, 0.0, False
        if case == FakeCase.DUPLICATE_CALL_IDS:
            return 200, b'{"toolCalls":[{"id":"same","name":"logs.search","arguments":"{}"},{"id":"same","name":"logs.search","arguments":"{}"}]}', "application/json", None, 0.0, False
        if case == FakeCase.MALFORMED_ARGUMENTS:
            return 200, b'{"toolCalls":[{"id":"call-1","name":"logs.search","arguments":"{"}]}', "application/json", None, 0.0, False
        if case == FakeCase.EXCESSIVE_PROPOSALS:
            calls = b",".join(b'{"id":"call-%d","name":"logs.search","arguments":"{}"}' % index for index in range(17))
            return 200, b'{"toolCalls":[' + calls + b"]}", "application/json", None, 0.0, False
        return 500, b"", "application/json", None, 0.0, False
