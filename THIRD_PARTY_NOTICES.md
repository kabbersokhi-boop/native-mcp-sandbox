# Third-Party Notices

## nlohmann/json

Native MCP Sandbox depends on nlohmann/json 3.11 or newer, supplied
by the host operating system. Dependency source is not vendored in this repository.

- Project: JSON for Modern C++
- Website: https://github.com/nlohmann/json
- Copyright: Niels Lohmann and contributors
- License: MIT License

The full license is provided by the installed package and upstream project. This notice
does not modify the Apache-2.0 license for Native MCP Sandbox source.

## LLVM libFuzzer

Optional coverage-guided fuzz targets use libFuzzer as supplied by the installed Clang/LLVM
toolchain. No libFuzzer source or runtime binary is vendored or distributed by this
repository. The deterministic fuzz-smoke executable does not require libFuzzer.

- Project: LLVM compiler-rt libFuzzer
- Website: https://llvm.org/docs/LibFuzzer.html
- License: Apache License 2.0 with LLVM exceptions

The ELF and procfs implementations use Linux and standard C/C++ constants and system
calls from operating-system headers. They add no libelf, procps, container runtime, or
binary-analysis runtime dependency.
