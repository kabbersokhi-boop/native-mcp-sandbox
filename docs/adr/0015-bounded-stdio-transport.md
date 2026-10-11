# ADR 0015: Bound protocol writes and stop failed connections

- Status: Accepted
- Date: 2026-09-19

## Context

The previous protocol writer held a mutex while it wrote and flushed a C++ output stream.
This serialized messages but did not bound a write to a full pipe. A worker could block while
the main thread waited for input or joined workers. Diagnostic output had the same problem.
A closed output pipe terminated the executable through SIGPIPE.

The supervised regression harness reproduced four hangs at the five-second observation limit
and one SIGPIPE exit on source `c195ed03aea5609cd58f8b90764c30a4172f4a0b`.
The harness killed and reaped each stalled child. The existing 21 CTest entries passed on that source.

## Decision

The executable owns its standard descriptors during the MCP session. It installs scoped
nonblocking descriptor modes and scoped SIGPIPE handling before starting workers. It restores
the original flags and signal disposition after all workers join. This entry point is for a
standalone process, not concurrent sessions sharing a process or open-file descriptions.

Small descriptor-backed stream buffers reuse the existing protocol loop and serialized writer.
Each complete response or diagnostic line is one bounded write operation. The default deadline
is two seconds on the steady clock. Partial writes advance a cursor. EINTR does not reset the
deadline. EAGAIN waits with poll. No background writer or additional output queue is required.

One atomic failure state is shared by input, output and diagnostics. The input reader checks
that state at least once per 50-millisecond poll and before admitting buffered input. Failure
is permanent. Subsequent writes fail without retrying or producing further protocol messages.
A partial message at failure ends the connection; it is never followed by a replacement error.

Output failure requests cooperative cancellation of all accepted calls and closes admission.
Stop requests occur outside the scheduler mutex. The existing non-worker shutdown owner joins
workers. Normal EOF preserves drain semantics. Failed connections return EX_IOERR (74).

## Limits

The write deadline covers writable pipes and sockets under normal Linux scheduling. O_NONBLOCK
does not make regular-file I/O or arbitrary kernel/filesystem operations hard real-time.
Cancellation remains cooperative. A failed diagnostic channel cannot reliably report its own
failure. Exit status is the authoritative transport failure signal.

The generic stream-based API remains useful for deterministic tests. It cannot enforce a
deadline on arbitrary third-party stream buffers. Use the native descriptor entry point for
the shipped executable.

## Verification

Run `ctest --preset dev -R 'protocol.transport_liveness|orchestration' --output-on-failure`.
The supervised process tests cover stalled stdout, stalled stderr, a closed output pipe,
an idle input reader after worker failure, EOF with pending output, small reader chunks and
a final input record without a newline. Scheduler tests cover cancellation of running and
queued work, admission closure, repeated stop, accounting and response suppression.
