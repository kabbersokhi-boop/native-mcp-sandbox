#include "native_mcp/foundation.hpp"
#include "native_mcp/server.hpp"

#include <iostream>
#include <string_view>

namespace {

void print_usage(std::ostream& output) {
  output << "Usage: native-mcp-sandbox [--help | --version | --self-check]\n"
         << "       native-mcp-sandbox\n"
         << "\n"
         << "With no arguments, run the Phase 1 MCP server over stdin/stdout.\n"
         << "Diagnostics are written only to stderr. No analysis tools are exposed.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
  if (argc == 1) {
    return native_mcp::run_stdio(std::cin, std::cout, std::cerr);
  }

  if (argc != 2) {
    print_usage(std::cerr);
    return 64;
  }

  const std::string_view argument{argv[1]};
  if (argument == "--help") {
    print_usage(std::cout);
    return 0;
  }

  if (argument == "--version") {
    std::cout << native_mcp::project_name() << ' '
              << native_mcp::project_version() << '\n';
    return 0;
  }

  if (argument == "--self-check") {
    const auto budget = native_mcp::conservative_budget();
    if (!native_mcp::is_budget_valid(budget)) {
      std::cerr << "self-check failed: invalid default resource budget\n";
      return 1;
    }
    std::cout << "self-check passed: " << native_mcp::budget_summary(budget)
              << '\n';
    return 0;
  }

  std::cerr << "unknown option: " << argument << '\n';
  print_usage(std::cerr);
  return 64;
}
