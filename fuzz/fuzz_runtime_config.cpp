#include "fuzz_support.hpp"

#include <cstddef>
#include <cstdint>
#include <span>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data,
                                       const std::size_t size) {
  native_mcp::fuzzing::exercise_runtime_config(
      std::span<const std::uint8_t>{data, size});
  return 0;
}
