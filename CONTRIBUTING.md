# Contributing

Thank you for helping improve Native MCP Sandbox.

## Before opening a change

For substantial protocol, dependency, tool, or sandbox changes, open an issue first
and describe the use case, trust-boundary impact, and simpler alternatives considered.

Keep pull requests focused. Do not combine formatting, dependency updates, and
behavior changes unless they are inseparable.

## Local verification

Run the development and sanitizer builds before requesting review:

```bash
cmake --preset dev
cmake --build --preset dev
ctest --preset dev

cmake --preset sanitizers
cmake --build --preset sanitizers
ctest --preset sanitizers
```

The presets intentionally use two compilation jobs to remain usable on modest
machines.

## Engineering rules

- Use C++20 and RAII for resource ownership.
- Prefer bounded data structures and streaming algorithms.
- Treat protocol input, paths, file contents, and process IDs as untrusted.
- Keep stdout exclusively for protocol messages in server mode.
- Never add arbitrary shell execution as an MCP tool.
- Add tests for invalid inputs and denied operations, not only happy paths.
- Document security assumptions and limitations precisely.
- Avoid dependencies without an architecture decision record.

## Commit and pull-request guidance

Use imperative, specific commit subjects such as:

```text
Validate resource budget upper bounds
```

Pull-request descriptions should state what changed, why it changed, how it was
tested, and what security or resource assumptions were affected.
