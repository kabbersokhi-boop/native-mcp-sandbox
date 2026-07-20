#include "fuzz_support.hpp"

#include <algorithm>
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace {

class XorShift64 final {
 public:
  explicit XorShift64(std::uint64_t seed)
      : state_(seed == 0U ? 0x9E3779B97F4A7C15ULL : seed) {}

  [[nodiscard]] std::uint64_t next() noexcept {
    std::uint64_t value = state_;
    value ^= value << 13U;
    value ^= value >> 7U;
    value ^= value << 17U;
    state_ = value;
    return value;
  }

 private:
  std::uint64_t state_;
};

[[nodiscard]] std::vector<std::uint8_t> bytes(const std::string_view text) {
  return std::vector<std::uint8_t>{text.begin(), text.end()};
}

[[nodiscard]] std::vector<std::vector<std::uint8_t>> seeds() {
  std::vector<std::vector<std::uint8_t>> result;
  result.push_back({});
  result.push_back(bytes("null"));
  result.push_back(bytes("{}"));
  result.push_back(bytes(
      R"({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}})"));
  result.push_back(bytes(
      R"({"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":1,"reason":"obsolete"}})"));
  result.push_back(bytes(
      R"({"jsonrpc":"2.0","id":1,"id":2,"method":"ping"})"));
  result.push_back(bytes(
      R"({"version":1,"roots":[{"name":"evidence","path":"/tmp","maxFileBytes":4096}]})"));
  result.push_back(bytes(
      R"({"version":2,"roots":[],"processes":[{"name":"self","pid":"self"}]})"));
  result.push_back(bytes("checkout timeout\nplugin initialized\nworker restarted\n"));
  result.push_back(bytes(
      "123 (checkout-worker) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 "
      "17 18 4242 0\n"));
  result.push_back(bytes(
      "Name:\tcheckout-worker\nState:\tS (sleeping)\n"
      "Uid:\t1000\t1000\t1000\t1000\nThreads:\t2\nVmRSS:\t512 kB\n"));
  result.push_back(bytes("100 50 10 4 0 25 0\n"));
  result.push_back(bytes("Rss:\t1024 kB\nPss:\t512 kB\nLocked:\t0 kB\n"));
  result.push_back(std::vector<std::uint8_t>{
      0x7fU, 'E', 'L', 'F', 2U, 1U, 1U, 0U, 0U, 0U, 0U, 0U, 0U, 0U,
      0U, 0U, 2U, 0U, 0x3eU, 0U, 1U, 0U, 0U, 0U});
  return result;
}

void mutate(std::vector<std::uint8_t>& data, XorShift64& random) {
  constexpr std::size_t kMaximumSmokeBytes = 16U * 1024U;
  const std::uint64_t choice = random.next() % 6U;
  if (choice == 0U && !data.empty()) {
    const std::size_t index = static_cast<std::size_t>(random.next() % data.size());
    data[index] ^= static_cast<std::uint8_t>(1U << (random.next() % 8U));
    return;
  }
  if (choice == 1U && data.size() < kMaximumSmokeBytes) {
    const std::size_t index = data.empty()
                                  ? 0U
                                  : static_cast<std::size_t>(random.next() %
                                                              (data.size() + 1U));
    data.insert(data.begin() + static_cast<std::ptrdiff_t>(index),
                static_cast<std::uint8_t>(random.next()));
    return;
  }
  if (choice == 2U && !data.empty()) {
    const std::size_t index = static_cast<std::size_t>(random.next() % data.size());
    data.erase(data.begin() + static_cast<std::ptrdiff_t>(index));
    return;
  }
  if (choice == 3U && !data.empty()) {
    const std::size_t index = static_cast<std::size_t>(random.next() % data.size());
    data[index] = static_cast<std::uint8_t>(random.next());
    return;
  }
  if (choice == 4U && !data.empty() && data.size() < kMaximumSmokeBytes) {
    const std::size_t begin = static_cast<std::size_t>(random.next() % data.size());
    const std::size_t available = data.size() - begin;
    const std::size_t count =
        1U + static_cast<std::size_t>(random.next() % available);
    const std::size_t retained =
        std::min(count, kMaximumSmokeBytes - data.size());
    const std::vector<std::uint8_t> copy(
        data.begin() + static_cast<std::ptrdiff_t>(begin),
        data.begin() + static_cast<std::ptrdiff_t>(begin + retained));
    data.insert(data.end(), copy.begin(), copy.end());
    return;
  }
  if (data.size() < kMaximumSmokeBytes) {
    const std::size_t count =
        1U + static_cast<std::size_t>(random.next() % 32U);
    for (std::size_t index = 0U;
         index < count && data.size() < kMaximumSmokeBytes; ++index) {
      data.push_back(static_cast<std::uint8_t>(random.next()));
    }
  }
}

[[nodiscard]] bool parse_number(const std::string_view text,
                                std::uint64_t& output) {
  const char* const begin = text.data();
  const char* const end = begin + text.size();
  const auto parsed = std::from_chars(begin, end, output);
  return parsed.ec == std::errc{} && parsed.ptr == end;
}

}  // namespace

int main(int argc, char* argv[]) {
  std::uint64_t iterations = 2000U;
  std::uint64_t seed = 0xC0FFEE1234ULL;
  for (int index = 1; index < argc; ++index) {
    const std::string_view argument{argv[index]};
    if (argument == "--iterations" && index + 1 < argc) {
      if (!parse_number(argv[++index], iterations) || iterations == 0U ||
          iterations > 10'000'000U) {
        std::cerr << "invalid --iterations value\n";
        return EXIT_FAILURE;
      }
    } else if (argument == "--seed" && index + 1 < argc) {
      if (!parse_number(argv[++index], seed)) {
        std::cerr << "invalid --seed value\n";
        return EXIT_FAILURE;
      }
    } else {
      std::cerr << "usage: native_mcp_fuzz_smoke [--iterations N] [--seed N]\n";
      return EXIT_FAILURE;
    }
  }

  const auto corpus = seeds();
  XorShift64 random{seed};
  for (const auto& value : corpus) {
    const std::span<const std::uint8_t> input{value};
    native_mcp::fuzzing::exercise_json_and_protocol(input);
    native_mcp::fuzzing::exercise_runtime_config(input);
    native_mcp::fuzzing::exercise_elf(input);
    native_mcp::fuzzing::exercise_log(input);
    native_mcp::fuzzing::exercise_process(input);
  }

  for (std::uint64_t iteration = 0U; iteration < iterations; ++iteration) {
    std::vector<std::uint8_t> value =
        corpus[static_cast<std::size_t>(random.next() % corpus.size())];
    const std::size_t mutation_count =
        1U + static_cast<std::size_t>(random.next() % 8U);
    for (std::size_t mutation = 0U; mutation < mutation_count; ++mutation) {
      mutate(value, random);
    }
    const std::span<const std::uint8_t> input{value};
    native_mcp::fuzzing::exercise_json_and_protocol(input);
    native_mcp::fuzzing::exercise_runtime_config(input);
    if ((iteration & 1U) == 0U) {
      native_mcp::fuzzing::exercise_log(input);
    }
    if ((iteration & 3U) == 0U) {
      native_mcp::fuzzing::exercise_elf(input);
      native_mcp::fuzzing::exercise_process(input);
    }
  }

  std::cout << "deterministic fuzz smoke passed: iterations=" << iterations
            << " seed=" << seed << '\n';
  return EXIT_SUCCESS;
}
