#!/usr/bin/env python3
"""Supervise real stdio peers, including peers that stop reading."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time
import unittest


SERVER = Path()
LIMIT_SECONDS = 5.0
OUTPUT_LIMIT = 4 * 1024 * 1024


def line(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode() + b"\n"


def initialize() -> bytes:
    return line(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "liveness-test", "version": "1"},
            },
        }
    ) + line({"jsonrpc": "2.0", "method": "notifications/initialized"})


class Peer:
    def __init__(self, arguments: tuple[str, ...] = ()):
        self.process = subprocess.Popen(
            [str(SERVER), *arguments],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.streams = (self.process.stdin, self.process.stdout, self.process.stderr)
        for stream in self.streams:
            assert stream is not None
            os.set_blocking(stream.fileno(), False)
            fcntl.fcntl(stream, fcntl.F_SETPIPE_SZ, 4096)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=2)
        for stream in self.streams:
            if stream is not None and not stream.closed:
                stream.close()

    def exchange(
        self,
        payload: bytes,
        *,
        drain_stdout: bool = True,
        drain_stderr: bool = True,
        close_input: bool = True,
        read_size: int = 4096,
    ) -> tuple[int | None, bytes, bytes]:
        output = bytearray()
        diagnostics = bytearray()
        sent = 0
        deadline = time.monotonic() + LIMIT_SECONDS
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdin, selectors.EVENT_WRITE, "input")
            if drain_stdout and not self.process.stdout.closed:
                selector.register(self.process.stdout, selectors.EVENT_READ, output)
            if drain_stderr and not self.process.stderr.closed:
                selector.register(self.process.stderr, selectors.EVENT_READ, diagnostics)
            while time.monotonic() < deadline:
                for key, _ in selector.select(0.02):
                    if key.data == "input":
                        try:
                            sent += os.write(key.fd, payload[sent : sent + 4096])
                        except BrokenPipeError:
                            sent = len(payload)
                        except BlockingIOError:
                            continue
                        if sent == len(payload):
                            selector.unregister(key.fileobj)
                            if close_input:
                                key.fileobj.close()
                    else:
                        try:
                            chunk = os.read(key.fd, read_size)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            key.data.extend(chunk)
                            if len(key.data) > OUTPUT_LIMIT:
                                raise AssertionError("peer output exceeded the harness bound")
                if self.process.poll() is not None:
                    pending_readers = any(
                        key.data != "input" for key in selector.get_map().values()
                    )
                    if not pending_readers:
                        break
        return self.process.poll(), bytes(output), bytes(diagnostics)


class TransportLivenessTests(unittest.TestCase):
    def test_stalled_stdout_with_open_input(self):
        payload = b"".join(
            line({"jsonrpc": "2.0", "id": index, "method": "ping"}) for index in range(1000)
        )
        with Peer() as peer:
            status, _, _ = peer.exchange(payload, drain_stdout=False, close_input=False)
            self.assertEqual(status, 74, "an unread stdout must terminate with EX_IOERR")

    def test_stalled_stderr(self):
        payload = line({"method": "invalid-notification"}) * 1000
        with Peer() as peer:
            status, _, _ = peer.exchange(payload, drain_stderr=False)
            self.assertEqual(status, 74, "an unread diagnostic pipe must not hang the server")

    def test_closed_stdout(self):
        with Peer() as peer:
            peer.process.stdout.close()
            status, _, _ = peer.exchange(line({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
            self.assertEqual(status, 74, "EPIPE must be handled, not delivered as fatal SIGPIPE")

    def test_slow_reader_preserves_complete_responses(self):
        payload = b"".join(
            line({"jsonrpc": "2.0", "id": index, "method": "ping"}) for index in range(400)
        )
        with Peer() as peer:
            status, output, diagnostics = peer.exchange(payload, read_size=127)
            self.assertEqual(status, 0)
            self.assertFalse(diagnostics)
            responses = [json.loads(value) for value in output.splitlines()]
            self.assertEqual([value["id"] for value in responses], list(range(400)))

    def test_partial_input_and_eof(self):
        with Peer() as peer:
            status, output, _ = peer.exchange(b'{"jsonrpc":"2.0","id":7,"method":"ping"}')
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output)["id"], 7)

    def test_worker_output_failure_wakes_idle_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "large.log").write_text(("ERROR " + "x" * 400 + "\n") * 50)
            policy = root / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "roots": [{"name": "evidence", "path": str(root), "maxFileBytes": 65536}],
                    }
                )
            )
            payload = initialize() + line(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "logs.search",
                        "arguments": {
                            "root": "evidence",
                            "path": "large.log",
                            "query": "ERROR",
                            "maxMatches": 50,
                        },
                    },
                }
            )
            with Peer(("--policy-config", str(policy))) as peer:
                status, _, diagnostics = peer.exchange(
                    payload, drain_stdout=False, close_input=False
                )
                self.assertEqual(status, 74, diagnostics.decode(errors="replace"))

    def test_eof_with_pending_large_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "large.log").write_text(("ERROR " + "x" * 400 + "\n") * 50)
            policy = root / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "roots": [{"name": "evidence", "path": str(root), "maxFileBytes": 65536}],
                    }
                )
            )
            payload = initialize() + line(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "logs.search",
                        "arguments": {
                            "root": "evidence",
                            "path": "large.log",
                            "query": "ERROR",
                            "maxMatches": 50,
                        },
                    },
                }
            )
            with Peer(("--policy-config", str(policy))) as peer:
                status, _, diagnostics = peer.exchange(payload, drain_stdout=False)
                self.assertEqual(status, 74, diagnostics.decode(errors="replace"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, type=Path)
    arguments, remaining = parser.parse_known_args()
    SERVER = arguments.server.resolve()
    unittest.main(argv=[__file__, *remaining])
