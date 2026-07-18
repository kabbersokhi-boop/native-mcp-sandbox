#pragma once

#include "native_mcp/file_policy.hpp"
#include "native_mcp/operation.hpp"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace native_mcp {

enum class ElfAnalysisErrorCode {
  kInvalidFormat,
  kUnsupportedFeature,
  kMetadataTooLarge,
  kReadFailed,
  kCancelled,
  kDeadlineExceeded,
};

struct ElfAnalysisError final {
  ElfAnalysisErrorCode code;
  std::string message;
};

struct ElfInspectionLimits final {
  std::size_t max_program_headers = 256U;
  std::size_t max_program_header_entry_bytes = 256U;
  std::size_t max_segment_summaries = 64U;
  std::size_t max_interpreter_bytes = 4096U;
  std::size_t max_dynamic_entries = 4096U;
  std::size_t max_dynamic_string_bytes = 256U * 1024U;
  std::size_t max_needed_libraries = 64U;
  std::size_t max_library_name_bytes = 256U;
  std::size_t max_note_bytes = 256U * 1024U;
  std::size_t max_build_id_bytes = 64U;
  std::size_t max_metadata_bytes = 1024U * 1024U;
};

struct ElfSegmentSummary final {
  std::string type;
  std::string flags;
  std::uint64_t file_offset;
  std::uint64_t file_size;
  std::uint64_t memory_size;
  std::string virtual_address;
};

struct ElfInspectionResult final {
  std::string elf_class;
  std::string endianness;
  std::string file_type;
  std::uint16_t file_type_number;
  std::string machine;
  std::uint16_t machine_number;
  std::string os_abi;
  std::uint8_t os_abi_number;
  std::string entry_point;
  std::size_t program_header_count;
  std::optional<std::string> interpreter;
  std::vector<std::string> needed_libraries;
  bool needed_libraries_truncated = false;
  std::optional<std::string> build_id;
  std::string stack_policy;
  std::string relro;
  bool position_independent = false;
  bool pie_executable = false;
  bool writable_executable_load_segment = false;
  bool file_changed_during_read = false;
  std::size_t metadata_bytes_read = 0U;
  std::vector<ElfSegmentSummary> segments;
  bool segment_summaries_truncated = false;
};

struct ElfInspectionOutcome final {
  std::optional<ElfInspectionResult> result;
  std::optional<ElfAnalysisError> error;
};

class ElfAnalyzer final {
 public:
  explicit ElfAnalyzer(ElfInspectionLimits limits = {});

  [[nodiscard]] ElfInspectionOutcome inspect(
      const ReadOnlyFile& file, OperationContext context = {}) const;
  [[nodiscard]] const ElfInspectionLimits& limits() const noexcept;

 private:
  ElfInspectionLimits limits_;
};

[[nodiscard]] std::string_view elf_analysis_error_name(
    ElfAnalysisErrorCode code) noexcept;

}  // namespace native_mcp
