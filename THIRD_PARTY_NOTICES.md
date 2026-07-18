# Third-Party Notices

## nlohmann/json

Native MCP Sandbox Phases 1 through 6 depend on nlohmann/json 3.11 or newer, supplied
by the host operating system. Dependency source is not vendored in this repository.

- Project: JSON for Modern C++
- Website: https://github.com/nlohmann/json
- Copyright: Niels Lohmann and contributors
- License: MIT License

The full license is provided by the installed package and upstream project. This notice
does not modify the Apache-2.0 license for Native MCP Sandbox source.

The ELF and procfs implementations use Linux and standard C/C++ constants and system
calls from operating-system headers. They add no libelf, procps, or binary-analysis
runtime dependency.
