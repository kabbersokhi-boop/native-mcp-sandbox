#include "native_mcp/elf_analysis.hpp"

#include <elf.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace native_mcp {
namespace {

[[nodiscard]] ElfAnalysisError error(const ElfAnalysisErrorCode code,
                                     std::string message) {
  return ElfAnalysisError{.code = code, .message = std::move(message)};
}

[[nodiscard]] bool checked_add(const std::uint64_t left,
                               const std::uint64_t right,
                               std::uint64_t& result) noexcept {
  if (right > std::numeric_limits<std::uint64_t>::max() - left) {
    return false;
  }
  result = left + right;
  return true;
}

[[nodiscard]] bool checked_multiply(const std::uint64_t left,
                                    const std::uint64_t right,
                                    std::uint64_t& result) noexcept {
  if (left != 0U && right > std::numeric_limits<std::uint64_t>::max() / left) {
    return false;
  }
  result = left * right;
  return true;
}

class Reader final {
 public:
  Reader(const ReadOnlyFile& file, const std::size_t metadata_limit)
      : file_(file),
        file_limit_(std::min(file.observed_size(), file.max_read_bytes())),
        metadata_limit_(metadata_limit) {}

  [[nodiscard]] bool read(const std::uint64_t offset, const std::size_t size,
                          std::vector<unsigned char>& output,
                          ElfAnalysisError& failure) {
    std::uint64_t end = 0U;
    if (!checked_add(offset, static_cast<std::uint64_t>(size), end) ||
        end > file_limit_) {
      failure = error(ElfAnalysisErrorCode::kInvalidFormat,
                      "ELF metadata points outside the approved file range");
      return false;
    }
    if (size > metadata_limit_ - std::min(bytes_read_, metadata_limit_)) {
      failure = error(ElfAnalysisErrorCode::kMetadataTooLarge,
                      "ELF metadata exceeds the inspection byte budget");
      return false;
    }
    output.assign(size, 0U);
    std::size_t total = 0U;
    while (total < size) {
      const ssize_t count = ::pread(
          file_.fd(), output.data() + total, size - total,
          static_cast<off_t>(offset + static_cast<std::uint64_t>(total)));
      if (count < 0) {
        if (errno == EINTR) {
          continue;
        }
        failure = error(ElfAnalysisErrorCode::kReadFailed,
                        "failed while reading bounded ELF metadata");
        return false;
      }
      if (count == 0) {
        failure = error(ElfAnalysisErrorCode::kInvalidFormat,
                        "ELF metadata ended unexpectedly");
        return false;
      }
      total += static_cast<std::size_t>(count);
    }
    bytes_read_ += size;
    return true;
  }

  [[nodiscard]] std::uint64_t file_limit() const noexcept { return file_limit_; }
  [[nodiscard]] std::size_t bytes_read() const noexcept { return bytes_read_; }

 private:
  const ReadOnlyFile& file_;
  std::uint64_t file_limit_;
  std::size_t metadata_limit_;
  std::size_t bytes_read_ = 0U;
};

[[nodiscard]] std::uint16_t read_u16(const unsigned char* data,
                                     const bool little) noexcept {
  if (little) {
    return static_cast<std::uint16_t>(data[0]) |
           static_cast<std::uint16_t>(static_cast<std::uint16_t>(data[1]) << 8U);
  }
  return static_cast<std::uint16_t>(data[1]) |
         static_cast<std::uint16_t>(static_cast<std::uint16_t>(data[0]) << 8U);
}

[[nodiscard]] std::uint32_t read_u32(const unsigned char* data,
                                     const bool little) noexcept {
  std::uint32_t value = 0U;
  if (little) {
    for (std::size_t index = 0U; index < 4U; ++index) {
      value |= static_cast<std::uint32_t>(data[index]) << (index * 8U);
    }
  } else {
    for (std::size_t index = 0U; index < 4U; ++index) {
      value = (value << 8U) | static_cast<std::uint32_t>(data[index]);
    }
  }
  return value;
}

[[nodiscard]] std::uint64_t read_u64(const unsigned char* data,
                                     const bool little) noexcept {
  std::uint64_t value = 0U;
  if (little) {
    for (std::size_t index = 0U; index < 8U; ++index) {
      value |= static_cast<std::uint64_t>(data[index]) << (index * 8U);
    }
  } else {
    for (std::size_t index = 0U; index < 8U; ++index) {
      value = (value << 8U) | static_cast<std::uint64_t>(data[index]);
    }
  }
  return value;
}

[[nodiscard]] std::string hex_value(const std::uint64_t value) {
  std::ostringstream stream;
  stream << "0x" << std::hex << std::uppercase << value;
  return stream.str();
}

[[nodiscard]] std::string bytes_to_hex(
    const unsigned char* data, const std::size_t size) {
  static constexpr std::array<char, 16> kHex{
      '0', '1', '2', '3', '4', '5', '6', '7',
      '8', '9', 'A', 'B', 'C', 'D', 'E', 'F'};
  std::string output;
  output.reserve(size * 2U);
  for (std::size_t index = 0U; index < size; ++index) {
    const unsigned char value = data[index];
    output.push_back(kHex[(value >> 4U) & 0x0FU]);
    output.push_back(kHex[value & 0x0FU]);
  }
  return output;
}

[[nodiscard]] std::string escape_bytes(const unsigned char* data,
                                       const std::size_t size) {
  static constexpr std::array<char, 16> kHex{
      '0', '1', '2', '3', '4', '5', '6', '7',
      '8', '9', 'A', 'B', 'C', 'D', 'E', 'F'};
  std::string output;
  output.reserve(size);
  for (std::size_t index = 0U; index < size; ++index) {
    const unsigned char value = data[index];
    if (value >= 0x20U && value <= 0x7EU && value != '\\') {
      output.push_back(static_cast<char>(value));
    } else if (value == '\\') {
      output += "\\\\";
    } else {
      output += "\\x";
      output.push_back(kHex[(value >> 4U) & 0x0FU]);
      output.push_back(kHex[value & 0x0FU]);
    }
  }
  return output;
}

[[nodiscard]] std::string file_type_name(const std::uint16_t type) {
  switch (type) {
    case ET_NONE:
      return "none";
    case ET_REL:
      return "relocatable";
    case ET_EXEC:
      return "executable";
    case ET_DYN:
      return "shared_object";
    case ET_CORE:
      return "core";
    default:
      return "unknown";
  }
}

[[nodiscard]] std::string machine_name(const std::uint16_t machine) {
  switch (machine) {
    case EM_NONE:
      return "none";
    case EM_386:
      return "x86";
    case EM_X86_64:
      return "x86_64";
    case EM_ARM:
      return "arm";
    case EM_AARCH64:
      return "aarch64";
    case EM_MIPS:
      return "mips";
#ifdef EM_RISCV
    case EM_RISCV:
      return "riscv";
#endif
    case EM_PPC:
      return "powerpc";
    case EM_PPC64:
      return "powerpc64";
    case EM_S390:
      return "s390";
    default:
      return "unknown";
  }
}

[[nodiscard]] std::string os_abi_name(const std::uint8_t abi) {
  switch (abi) {
    case ELFOSABI_NONE:
      return "system_v";
    case ELFOSABI_LINUX:
      return "linux";
    case ELFOSABI_FREEBSD:
      return "freebsd";
    case ELFOSABI_NETBSD:
      return "netbsd";
    case ELFOSABI_SOLARIS:
      return "solaris";
    default:
      return "unknown";
  }
}

[[nodiscard]] std::string segment_type_name(const std::uint32_t type) {
  switch (type) {
    case PT_NULL:
      return "null";
    case PT_LOAD:
      return "load";
    case PT_DYNAMIC:
      return "dynamic";
    case PT_INTERP:
      return "interpreter";
    case PT_NOTE:
      return "note";
    case PT_PHDR:
      return "program_headers";
    case PT_TLS:
      return "tls";
#ifdef PT_GNU_EH_FRAME
    case PT_GNU_EH_FRAME:
      return "gnu_eh_frame";
#endif
#ifdef PT_GNU_STACK
    case PT_GNU_STACK:
      return "gnu_stack";
#endif
#ifdef PT_GNU_RELRO
    case PT_GNU_RELRO:
      return "gnu_relro";
#endif
    default:
      return "other";
  }
}

[[nodiscard]] std::string segment_flags(const std::uint32_t flags) {
  std::string output;
  output.push_back((flags & PF_R) != 0U ? 'R' : '-');
  output.push_back((flags & PF_W) != 0U ? 'W' : '-');
  output.push_back((flags & PF_X) != 0U ? 'X' : '-');
  return output;
}

struct ProgramHeader final {
  std::uint32_t type;
  std::uint32_t flags;
  std::uint64_t offset;
  std::uint64_t virtual_address;
  std::uint64_t file_size;
  std::uint64_t memory_size;
};

[[nodiscard]] bool range_inside(const std::uint64_t offset,
                                const std::uint64_t size,
                                const std::uint64_t limit) noexcept {
  std::uint64_t end = 0U;
  return checked_add(offset, size, end) && end <= limit;
}

[[nodiscard]] std::optional<std::uint64_t> virtual_to_file(
    const std::vector<ProgramHeader>& headers, const std::uint64_t address,
    const std::uint64_t size) {
  for (const ProgramHeader& header : headers) {
    if (header.type != PT_LOAD || address < header.virtual_address) {
      continue;
    }
    const std::uint64_t delta = address - header.virtual_address;
    if (delta > header.file_size || size > header.file_size - delta) {
      continue;
    }
    std::uint64_t result = 0U;
    if (checked_add(header.offset, delta, result)) {
      return result;
    }
  }
  return std::nullopt;
}

[[nodiscard]] bool same_snapshot(const struct stat& before,
                                 const struct stat& after) noexcept {
  return before.st_dev == after.st_dev && before.st_ino == after.st_ino &&
         before.st_mode == after.st_mode && before.st_size == after.st_size &&
         before.st_mtim.tv_sec == after.st_mtim.tv_sec &&
         before.st_mtim.tv_nsec == after.st_mtim.tv_nsec &&
         before.st_ctim.tv_sec == after.st_ctim.tv_sec &&
         before.st_ctim.tv_nsec == after.st_ctim.tv_nsec;
}

[[nodiscard]] bool parse_notes(Reader& reader,
                               const std::vector<ProgramHeader>& headers,
                               const bool little,
                               const ElfInspectionLimits& limits,
                               std::optional<std::string>& build_id,
                               ElfAnalysisError& failure) {
  std::size_t note_bytes = 0U;
  for (const ProgramHeader& header : headers) {
    if (header.type != PT_NOTE || header.file_size == 0U) {
      continue;
    }
    if (header.file_size > limits.max_note_bytes -
                               std::min(note_bytes, limits.max_note_bytes)) {
      failure = error(ElfAnalysisErrorCode::kMetadataTooLarge,
                      "ELF note data exceeds the inspection limit");
      return false;
    }
    note_bytes += static_cast<std::size_t>(header.file_size);
    std::vector<unsigned char> bytes;
    if (!reader.read(header.offset, static_cast<std::size_t>(header.file_size),
                     bytes, failure)) {
      return false;
    }
    std::size_t position = 0U;
    while (position < bytes.size()) {
      if (bytes.size() - position < 12U) {
        failure = error(ElfAnalysisErrorCode::kInvalidFormat,
                        "ELF note header is truncated");
        return false;
      }
      const std::uint32_t name_size = read_u32(bytes.data() + position, little);
      const std::uint32_t description_size =
          read_u32(bytes.data() + position + 4U, little);
      const std::uint32_t type = read_u32(bytes.data() + position + 8U, little);
      position += 12U;
      const auto align4 = [](const std::uint64_t value) -> std::uint64_t {
        return (value + 3U) & ~std::uint64_t{3U};
      };
      const std::uint64_t aligned_name = align4(name_size);
      const std::uint64_t aligned_description = align4(description_size);
      std::uint64_t next = 0U;
      if (!checked_add(static_cast<std::uint64_t>(position), aligned_name, next) ||
          !checked_add(next, aligned_description, next) || next > bytes.size()) {
        failure = error(ElfAnalysisErrorCode::kInvalidFormat,
                        "ELF note payload is out of range");
        return false;
      }
      const unsigned char* name = bytes.data() + position;
      const unsigned char* description =
          bytes.data() + position + static_cast<std::size_t>(aligned_name);
      if (!build_id.has_value() && type == NT_GNU_BUILD_ID && name_size == 4U &&
          name[0] == 'G' && name[1] == 'N' && name[2] == 'U' && name[3] == 0U) {
        if (description_size > limits.max_build_id_bytes) {
          failure = error(ElfAnalysisErrorCode::kMetadataTooLarge,
                          "GNU build ID exceeds the inspection limit");
          return false;
        }
        build_id = bytes_to_hex(description, description_size);
      }
      position = static_cast<std::size_t>(next);
    }
  }
  return true;
}

}  // namespace

ElfAnalyzer::ElfAnalyzer(const ElfInspectionLimits limits) : limits_(limits) {}

ElfInspectionOutcome ElfAnalyzer::inspect(const ReadOnlyFile& file) const {
  struct stat before {};
  if (::fstat(file.fd(), &before) != 0 || before.st_size < 0) {
    return {.result = std::nullopt,
            .error = error(ElfAnalysisErrorCode::kReadFailed,
                           "failed to snapshot the approved ELF file")};
  }
  Reader reader{file, limits_.max_metadata_bytes};
  ElfAnalysisError failure =
      error(ElfAnalysisErrorCode::kInvalidFormat, "invalid ELF file");
  std::vector<unsigned char> identification;
  if (!reader.read(0U, EI_NIDENT, identification, failure)) {
    return {.result = std::nullopt, .error = std::move(failure)};
  }
  if (identification[EI_MAG0] != ELFMAG0 || identification[EI_MAG1] != ELFMAG1 ||
      identification[EI_MAG2] != ELFMAG2 || identification[EI_MAG3] != ELFMAG3) {
    return {.result = std::nullopt,
            .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                           "file does not contain the ELF magic value")};
  }
  const unsigned char elf_class = identification[EI_CLASS];
  const bool is_64 = elf_class == ELFCLASS64;
  if (!is_64 && elf_class != ELFCLASS32) {
    return {.result = std::nullopt,
            .error = error(ElfAnalysisErrorCode::kUnsupportedFeature,
                           "ELF class is not 32-bit or 64-bit")};
  }
  const unsigned char data_encoding = identification[EI_DATA];
  const bool little = data_encoding == ELFDATA2LSB;
  if (!little && data_encoding != ELFDATA2MSB) {
    return {.result = std::nullopt,
            .error = error(ElfAnalysisErrorCode::kUnsupportedFeature,
                           "ELF byte order is unsupported")};
  }
  if (identification[EI_VERSION] != EV_CURRENT) {
    return {.result = std::nullopt,
            .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                           "ELF identification version is invalid")};
  }

  const std::size_t complete_header_size = is_64 ? 64U : 52U;
  std::vector<unsigned char> header;
  if (!reader.read(0U, complete_header_size, header, failure)) {
    return {.result = std::nullopt, .error = std::move(failure)};
  }

  const std::uint16_t type = read_u16(header.data() + 16U, little);
  const std::uint16_t machine = read_u16(header.data() + 18U, little);
  const std::uint32_t version = read_u32(header.data() + 20U, little);
  if (version != EV_CURRENT) {
    return {.result = std::nullopt,
            .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                           "ELF header version is invalid")};
  }
  const std::uint64_t entry =
      is_64 ? read_u64(header.data() + 24U, little)
            : read_u32(header.data() + 24U, little);
  const std::uint64_t program_offset =
      is_64 ? read_u64(header.data() + 32U, little)
            : read_u32(header.data() + 28U, little);
  const std::uint16_t header_size =
      read_u16(header.data() + (is_64 ? 52U : 40U), little);
  const std::uint16_t program_entry_size =
      read_u16(header.data() + (is_64 ? 54U : 42U), little);
  const std::uint16_t program_count =
      read_u16(header.data() + (is_64 ? 56U : 44U), little);
  const std::uint16_t expected_header_size = is_64 ? 64U : 52U;
  const std::uint16_t expected_program_size = is_64 ? 56U : 32U;
  if (header_size != expected_header_size) {
    return {.result = std::nullopt,
            .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                           "ELF header size is invalid")};
  }
  if (program_count == PN_XNUM) {
    return {.result = std::nullopt,
            .error = error(ElfAnalysisErrorCode::kUnsupportedFeature,
                           "extended ELF program-header numbering is not supported")};
  }
  if (program_count > limits_.max_program_headers) {
    return {.result = std::nullopt,
            .error = error(ElfAnalysisErrorCode::kMetadataTooLarge,
                           "ELF program-header count exceeds the inspection limit")};
  }
  if (program_count > 0U && program_entry_size != expected_program_size) {
    return {.result = std::nullopt,
            .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                           "ELF program-header entry size is invalid")};
  }
  std::uint64_t table_size = 0U;
  if (!checked_multiply(program_count, program_entry_size, table_size) ||
      !range_inside(program_offset, table_size, reader.file_limit())) {
    return {.result = std::nullopt,
            .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                           "ELF program-header table is out of range")};
  }

  std::vector<ProgramHeader> program_headers;
  program_headers.reserve(program_count);
  std::vector<unsigned char> raw_program;
  for (std::size_t index = 0U; index < program_count; ++index) {
    const std::uint64_t offset =
        program_offset + static_cast<std::uint64_t>(index) * program_entry_size;
    if (!reader.read(offset, program_entry_size, raw_program, failure)) {
      return {.result = std::nullopt, .error = std::move(failure)};
    }
    ProgramHeader parsed{};
    parsed.type = read_u32(raw_program.data(), little);
    if (is_64) {
      parsed.flags = read_u32(raw_program.data() + 4U, little);
      parsed.offset = read_u64(raw_program.data() + 8U, little);
      parsed.virtual_address = read_u64(raw_program.data() + 16U, little);
      parsed.file_size = read_u64(raw_program.data() + 32U, little);
      parsed.memory_size = read_u64(raw_program.data() + 40U, little);
    } else {
      parsed.offset = read_u32(raw_program.data() + 4U, little);
      parsed.virtual_address = read_u32(raw_program.data() + 8U, little);
      parsed.file_size = read_u32(raw_program.data() + 16U, little);
      parsed.memory_size = read_u32(raw_program.data() + 20U, little);
      parsed.flags = read_u32(raw_program.data() + 24U, little);
    }
    if (parsed.file_size > 0U &&
        !range_inside(parsed.offset, parsed.file_size, reader.file_limit())) {
      return {.result = std::nullopt,
              .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                             "ELF segment points outside the approved file range")};
    }
    if (parsed.type == PT_LOAD && parsed.memory_size < parsed.file_size) {
      return {.result = std::nullopt,
              .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                             "ELF load segment memory size is smaller than its file size")};
    }
    program_headers.push_back(parsed);
  }

  ElfInspectionResult result;
  result.elf_class = is_64 ? "ELF64" : "ELF32";
  result.endianness = little ? "little" : "big";
  result.file_type = file_type_name(type);
  result.file_type_number = type;
  result.machine = machine_name(machine);
  result.machine_number = machine;
  result.os_abi = os_abi_name(identification[EI_OSABI]);
  result.os_abi_number = identification[EI_OSABI];
  result.entry_point = hex_value(entry);
  result.program_header_count = program_count;
  result.position_independent = type == ET_DYN;

  bool have_stack = false;
  bool executable_stack = false;
  bool have_relro = false;
  std::optional<ProgramHeader> dynamic_segment;
  std::vector<ProgramHeader> note_segments;
  for (const ProgramHeader& program : program_headers) {
    if (result.segments.size() < limits_.max_segment_summaries) {
      result.segments.push_back(ElfSegmentSummary{
          .type = segment_type_name(program.type),
          .flags = segment_flags(program.flags),
          .file_offset = program.offset,
          .file_size = program.file_size,
          .memory_size = program.memory_size,
          .virtual_address = hex_value(program.virtual_address),
      });
    } else {
      result.segment_summaries_truncated = true;
    }
    if (program.type == PT_LOAD && (program.flags & PF_W) != 0U &&
        (program.flags & PF_X) != 0U) {
      result.writable_executable_load_segment = true;
    }
    if (program.type == PT_INTERP) {
      if (result.interpreter.has_value()) {
        return {.result = std::nullopt,
                .error = error(ElfAnalysisErrorCode::kUnsupportedFeature,
                               "multiple ELF interpreter segments are unsupported")};
      }
      if (program.file_size == 0U ||
          program.file_size > limits_.max_interpreter_bytes) {
        return {.result = std::nullopt,
                .error = error(ElfAnalysisErrorCode::kMetadataTooLarge,
                               "ELF interpreter string exceeds the inspection limit")};
      }
      std::vector<unsigned char> interpreter;
      if (!reader.read(program.offset, static_cast<std::size_t>(program.file_size),
                       interpreter, failure)) {
        return {.result = std::nullopt, .error = std::move(failure)};
      }
      const auto terminator =
          std::find(interpreter.begin(), interpreter.end(), 0U);
      if (terminator == interpreter.end()) {
        return {.result = std::nullopt,
                .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                               "ELF interpreter string is not terminated")};
      }
      result.interpreter = escape_bytes(
          interpreter.data(), static_cast<std::size_t>(terminator - interpreter.begin()));
    }
    if (program.type == PT_DYNAMIC) {
      if (dynamic_segment.has_value()) {
        return {.result = std::nullopt,
                .error = error(ElfAnalysisErrorCode::kUnsupportedFeature,
                               "multiple ELF dynamic segments are unsupported")};
      }
      dynamic_segment = program;
    }
    if (program.type == PT_NOTE) {
      note_segments.push_back(program);
    }
#ifdef PT_GNU_STACK
    if (program.type == PT_GNU_STACK) {
      have_stack = true;
      executable_stack = (program.flags & PF_X) != 0U;
    }
#endif
#ifdef PT_GNU_RELRO
    if (program.type == PT_GNU_RELRO) {
      have_relro = true;
    }
#endif
  }
  result.stack_policy =
      !have_stack ? "unspecified"
                  : (executable_stack ? "executable" : "non_executable");
  result.pie_executable = type == ET_DYN && result.interpreter.has_value();

  bool bind_now = false;
  std::optional<std::uint64_t> string_table_address;
  std::optional<std::uint64_t> string_table_size;
  std::vector<std::uint64_t> needed_offsets;
  if (dynamic_segment.has_value() && dynamic_segment->file_size > 0U) {
    const std::size_t entry_size = is_64 ? 16U : 8U;
    if (dynamic_segment->file_size % entry_size != 0U ||
        dynamic_segment->file_size / entry_size > limits_.max_dynamic_entries) {
      return {.result = std::nullopt,
              .error = error(ElfAnalysisErrorCode::kMetadataTooLarge,
                             "ELF dynamic table exceeds the inspection limit")};
    }
    std::vector<unsigned char> dynamic_bytes;
    if (!reader.read(dynamic_segment->offset,
                     static_cast<std::size_t>(dynamic_segment->file_size),
                     dynamic_bytes, failure)) {
      return {.result = std::nullopt, .error = std::move(failure)};
    }
    const std::size_t count = dynamic_bytes.size() / entry_size;
    bool dynamic_terminated = false;
    for (std::size_t index = 0U; index < count; ++index) {
      const unsigned char* current = dynamic_bytes.data() + index * entry_size;
      const std::uint64_t tag =
          is_64 ? read_u64(current, little) : read_u32(current, little);
      const std::uint64_t value =
          is_64 ? read_u64(current + 8U, little)
                : read_u32(current + 4U, little);
      if (tag == DT_NULL) {
        dynamic_terminated = true;
        break;
      }
      if (tag == DT_STRTAB) {
        string_table_address = value;
      } else if (tag == DT_STRSZ) {
        string_table_size = value;
      } else if (tag == DT_NEEDED) {
        needed_offsets.push_back(value);
      } else if (tag == DT_BIND_NOW) {
        bind_now = true;
      } else if (tag == DT_FLAGS && (value & DF_BIND_NOW) != 0U) {
        bind_now = true;
      }
#ifdef DF_1_NOW
      else if (tag == DT_FLAGS_1 && (value & DF_1_NOW) != 0U) {
        bind_now = true;
      }
#endif
    }
    if (!dynamic_terminated) {
      return {.result = std::nullopt,
              .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                             "ELF dynamic table is not terminated")};
    }
  }

  if (!needed_offsets.empty()) {
    if (!string_table_address.has_value() || !string_table_size.has_value() ||
        *string_table_size > limits_.max_dynamic_string_bytes) {
      return {.result = std::nullopt,
              .error = error(ElfAnalysisErrorCode::kMetadataTooLarge,
                             "ELF dynamic string table is missing or too large")};
    }
    const auto string_file_offset = virtual_to_file(
        program_headers, *string_table_address, *string_table_size);
    if (!string_file_offset.has_value()) {
      return {.result = std::nullopt,
              .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                             "ELF dynamic string table is not backed by a load segment")};
    }
    std::vector<unsigned char> strings;
    if (!reader.read(*string_file_offset,
                     static_cast<std::size_t>(*string_table_size), strings,
                     failure)) {
      return {.result = std::nullopt, .error = std::move(failure)};
    }
    for (const std::uint64_t needed : needed_offsets) {
      if (result.needed_libraries.size() >= limits_.max_needed_libraries) {
        result.needed_libraries_truncated = true;
        break;
      }
      if (needed >= strings.size()) {
        return {.result = std::nullopt,
                .error = error(ElfAnalysisErrorCode::kInvalidFormat,
                               "ELF needed-library offset is outside the string table")};
      }
      const std::size_t start = static_cast<std::size_t>(needed);
      std::size_t end = start;
      while (end < strings.size() && strings[end] != 0U &&
             end - start <= limits_.max_library_name_bytes) {
        ++end;
      }
      if (end >= strings.size() || strings[end] != 0U ||
          end - start > limits_.max_library_name_bytes) {
        return {.result = std::nullopt,
                .error = error(ElfAnalysisErrorCode::kMetadataTooLarge,
                               "ELF needed-library name is invalid or too long")};
      }
      result.needed_libraries.push_back(
          escape_bytes(strings.data() + start, end - start));
    }
  }

  if (!parse_notes(reader, note_segments, little, limits_, result.build_id,
                   failure)) {
    return {.result = std::nullopt, .error = std::move(failure)};
  }
  result.relro = !have_relro ? "none" : (bind_now ? "full" : "partial");
  struct stat after {};
  result.file_changed_during_read =
      ::fstat(file.fd(), &after) != 0 || !same_snapshot(before, after);
  result.metadata_bytes_read = reader.bytes_read();
  return {.result = std::move(result), .error = std::nullopt};
}

const ElfInspectionLimits& ElfAnalyzer::limits() const noexcept {
  return limits_;
}

std::string_view elf_analysis_error_name(
    const ElfAnalysisErrorCode code) noexcept {
  switch (code) {
    case ElfAnalysisErrorCode::kInvalidFormat:
      return "invalid_elf";
    case ElfAnalysisErrorCode::kUnsupportedFeature:
      return "unsupported_elf_feature";
    case ElfAnalysisErrorCode::kMetadataTooLarge:
      return "elf_metadata_too_large";
    case ElfAnalysisErrorCode::kReadFailed:
      return "elf_read_failed";
  }
  return "unknown";
}

}  // namespace native_mcp
