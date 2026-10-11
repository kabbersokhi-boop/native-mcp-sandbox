"""Bounded, test-only raw transport for native boundary experiments."""

from __future__ import annotations

import os
import selectors
import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Exchange:
    status: int
    stdout: bytes
    stderr: bytes
    elapsed_ns: int


def exchange(command: list[str], payload: bytes, *, timeout: float = 5,
             output_limit: int = 2 * 1024 * 1024) -> Exchange:
    if len(payload) > 2 * 1024 * 1024 or not 0 < timeout <= 60:
        raise ValueError("experiment exceeds input or time bound")
    started = time.monotonic_ns()
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env={"LANG": "C"}, bufsize=0)
    assert process.stdin and process.stdout and process.stderr
    streams = (process.stdin, process.stdout, process.stderr)
    output, diagnostics = bytearray(), bytearray()
    sent = 0
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for stream in streams:
                os.set_blocking(stream.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, None)
            selector.register(process.stdout, selectors.EVENT_READ, output)
            selector.register(process.stderr, selectors.EVENT_READ, diagnostics)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("native experiment exceeded its wall-clock budget")
                for key, _ in selector.select(min(remaining, 0.05)):
                    if key.data is None:
                        try:
                            sent += os.write(key.fd, payload[sent:sent + 4096])
                        except BrokenPipeError:
                            sent = len(payload)
                        except BlockingIOError:
                            continue
                        if sent == len(payload):
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                    else:
                        try:
                            chunk = os.read(key.fd, 4096)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            key.data.extend(chunk)
                            limit = output_limit if key.data is output else 65536
                            if len(key.data) > limit:
                                raise ValueError("native experiment exceeded output budget")
            status = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            return Exchange(status, bytes(output), bytes(diagnostics), time.monotonic_ns() - started)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)
        for stream in streams:
            if not stream.closed:
                stream.close()
