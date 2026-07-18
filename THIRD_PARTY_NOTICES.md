# Third-Party Notices

## nlohmann/json

Native MCP Sandbox Phases 1 through 4 depend on nlohmann/json 3.11 or newer, supplied
by the host operating system. Dependency source is not vendored in this repository.

- Project: JSON for Modern C++
- Website: https://github.com/nlohmann/json
- Copyright: Niels Lohmann and contributors
- License: MIT License

The full license is provided by the installed package and upstream project. This
notice does not modify the Apache-2.0 license for Native MCP Sandbox source.

Phase 4's ELF parser uses Linux and standard C/C++ ELF constants from system headers;
it adds no libelf or binary-analysis runtime dependency.
