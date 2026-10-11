# Interview walkthrough

These are rehearsal prompts, not a claim of production adoption or hiring outcomes.

## Two minutes

1. **Problem (20 seconds):** an investigating agent needs bounded evidence, not a shell.
2. **Native boundary (25 seconds):** show root-relative file access, pidfd-backed aliases,
   four read-only tools and bounded workers. Explain why C++ owns these mechanisms.
3. **Demonstration (45 seconds):** show recovery, switch to incomplete evidence, then show
   native traversal denial separately from Python proposal rejection. Open an evidence ID.
4. **Engineering result (20 seconds):** explain the reproduced stalled-output hang, terminal
   write deadline and child-reaping regression tests.
5. **Limits (10 seconds):** scripted provider, synthetic evidence, no kernel sandbox claim.

## Ten-minute architecture discussion

- Trace a `logs.search` request from JSON preflight through admission, root descriptor,
  `openat2`, bounded scan, serialization and nonblocking output. Explain every owner.
- Explain path containment versus process privileges and why network-free code is not
  kernel-enforced network denial after compromise.
- Explain PID reuse, pidfd identity, and strict startup failure when controls are absent.
- Draw worker, pending and active request ownership. Explain cancellation versus completion,
  queue saturation, output failure and shutdown ordering.
- Explain why a partial JSON write terminates the connection instead of retrying a new message.
- Show the five-call transcript regression: separate provider collection limits from the
  bounded transcript event budget, and reserve a terminal exhaustion event.
- Open raw benchmark samples. Explain warm caches, process startup, native versus harness RSS,
  no outlier filtering, and the absence of a p99 or language superiority claim.
- State the largest unresolved limit: the native process is not isolated from its OS authority,
  and arbitrary blocking kernel operations are not bounded by a transport deadline.

Practice answering these without reading this document. If an ownership or failure path is
unclear, inspect its implementation and tests before representing it in an interview.

## Resume drafts

- Built a C++20/Linux MCP evidence server with descriptor-based file containment, pidfd-backed
  process identity, bounded scheduling and four read-only tools; validated the supported stdio
  workflow with an independently maintained, pinned MCP SDK.
- Reproduced stalled-peer transport failures and implemented deadline-bounded native output;
  added seven supervised regressions and a reproducible 100-sample performance study with
  raw latency, resource and source-provenance artifacts.

Use these only after verifying the corresponding candidate artifacts. Do not add adoption,
throughput improvements, production scale or hiring impact that has not been measured.
