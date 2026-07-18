#include "native_mcp/elf_analysis.hpp"

#include <elf.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <string_view>
#include <vector>

namespace {

namespace fs = std::filesystem;

void fail(const std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void expect(const bool condition, const std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

class TempDirectory final {
 public:
  TempDirectory() {
    std::string pattern = "/tmp/native-mcp-elf-XXXXXX";
    pattern.push_back('\0');
    char* created = ::mkdtemp(pattern.data());
    expect(created != nullptr, "failed to create temporary directory");
    path_ = created;
  }
  ~TempDirectory() {
    std::error_code ignored;
    fs::remove_all(path_, ignored);
  }
  [[nodiscard]] const fs::path& path() const noexcept { return path_; }

 private:
  fs::path path_;
};

void put16(std::vector<unsigned char>& bytes, const std::size_t offset,
           const std::uint16_t value, const bool little = true) {
  for (std::size_t index = 0U; index < 2U; ++index) {
    const std::size_t shift = little ? index : 1U - index;
    bytes[offset + index] =
        static_cast<unsigned char>((value >> (shift * 8U)) & 0xFFU);
  }
}

void put32(std::vector<unsigned char>& bytes, const std::size_t offset,
           const std::uint32_t value, const bool little = true) {
  for (std::size_t index = 0U; index < 4U; ++index) {
    const std::size_t shift = little ? index : 3U - index;
    bytes[offset + index] =
        static_cast<unsigned char>((value >> (shift * 8U)) & 0xFFU);
  }
}

void put64(std::vector<unsigned char>& bytes, const std::size_t offset,
           const std::uint64_t value, const bool little = true) {
  for (std::size_t index = 0U; index < 8U; ++index) {
    const std::size_t shift = little ? index : 7U - index;
    bytes[offset + index] =
        static_cast<unsigned char>((value >> (shift * 8U)) & 0xFFU);
  }
}

void put_program64(std::vector<unsigned char>& bytes, const std::size_t index,
                   const std::uint32_t type, const std::uint32_t flags,
                   const std::uint64_t offset, const std::uint64_t virtual_address,
                   const std::uint64_t file_size, const std::uint64_t memory_size) {
  const std::size_t base = 64U + index * 56U;
  put32(bytes, base, type);
  put32(bytes, base + 4U, flags);
  put64(bytes, base + 8U, offset);
  put64(bytes, base + 16U, virtual_address);
  put64(bytes, base + 24U, virtual_address);
  put64(bytes, base + 32U, file_size);
  put64(bytes, base + 40U, memory_size);
  put64(bytes, base + 48U, 8U);
}

std::vector<unsigned char> make_elf64() {
  constexpr std::uint64_t kBase = 0x400000U;
  std::vector<unsigned char> bytes(1024U, 0U);
  bytes[EI_MAG0] = ELFMAG0;
  bytes[EI_MAG1] = ELFMAG1;
  bytes[EI_MAG2] = ELFMAG2;
  bytes[EI_MAG3] = ELFMAG3;
  bytes[EI_CLASS] = ELFCLASS64;
  bytes[EI_DATA] = ELFDATA2LSB;
  bytes[EI_VERSION] = EV_CURRENT;
  bytes[EI_OSABI] = ELFOSABI_LINUX;
  put16(bytes, 16U, ET_DYN);
  put16(bytes, 18U, EM_X86_64);
  put32(bytes, 20U, EV_CURRENT);
  put64(bytes, 24U, 0x401000U);
  put64(bytes, 32U, 64U);
  put16(bytes, 52U, 64U);
  put16(bytes, 54U, 56U);
  put16(bytes, 56U, 6U);
  put16(bytes, 58U, 64U);

  put_program64(bytes, 0U, PT_LOAD, PF_R | PF_X, 0U, kBase,
                bytes.size(), bytes.size());
  const std::string interpreter = "/lib64/ld-linux-x86-64.so.2";
  put_program64(bytes, 1U, PT_INTERP, PF_R, 400U, kBase + 400U,
                interpreter.size() + 1U, interpreter.size() + 1U);
  put_program64(bytes, 2U, PT_DYNAMIC, PF_R | PF_W, 512U, kBase + 512U,
                80U, 80U);
  put_program64(bytes, 3U, PT_NOTE, PF_R, 700U, kBase + 700U, 20U, 20U);
  put_program64(bytes, 4U, PT_GNU_STACK, PF_R | PF_W, 0U, 0U, 0U, 0U);
  put_program64(bytes, 5U, PT_GNU_RELRO, PF_R, 800U, kBase + 800U, 16U, 16U);

  std::copy(interpreter.begin(), interpreter.end(), bytes.begin() + 400U);
  bytes[400U + interpreter.size()] = 0U;

  const auto dynamic = [&](const std::size_t index, const std::uint64_t tag,
                           const std::uint64_t value) {
    put64(bytes, 512U + index * 16U, tag);
    put64(bytes, 520U + index * 16U, value);
  };
  dynamic(0U, DT_STRTAB, kBase + 640U);
  dynamic(1U, DT_STRSZ, 16U);
  dynamic(2U, DT_NEEDED, 1U);
  dynamic(3U, DT_BIND_NOW, 0U);
  dynamic(4U, DT_NULL, 0U);
  const std::string strings{"\0libc.so.6\0", 11U};
  std::copy(strings.begin(), strings.end(), bytes.begin() + 640U);

  put32(bytes, 700U, 4U);
  put32(bytes, 704U, 4U);
  put32(bytes, 708U, NT_GNU_BUILD_ID);
  bytes[712U] = 'G';
  bytes[713U] = 'N';
  bytes[714U] = 'U';
  bytes[715U] = 0U;
  bytes[716U] = 0x12U;
  bytes[717U] = 0x34U;
  bytes[718U] = 0x56U;
  bytes[719U] = 0x78U;
  return bytes;
}

std::vector<unsigned char> make_elf32_big_endian() {
  std::vector<unsigned char> bytes(52U, 0U);
  bytes[EI_MAG0] = ELFMAG0;
  bytes[EI_MAG1] = ELFMAG1;
  bytes[EI_MAG2] = ELFMAG2;
  bytes[EI_MAG3] = ELFMAG3;
  bytes[EI_CLASS] = ELFCLASS32;
  bytes[EI_DATA] = ELFDATA2MSB;
  bytes[EI_VERSION] = EV_CURRENT;
  bytes[EI_OSABI] = ELFOSABI_NONE;
  put16(bytes, 16U, ET_REL, false);
  put16(bytes, 18U, EM_ARM, false);
  put32(bytes, 20U, EV_CURRENT, false);
  put32(bytes, 24U, 0x10203040U, false);
  put16(bytes, 40U, 52U, false);
  put16(bytes, 42U, 32U, false);
  put16(bytes, 44U, 0U, false);
  put16(bytes, 46U, 40U, false);
  return bytes;
}

native_mcp::ReadOnlyFile open_fixture(const fs::path& path,
                                      const std::vector<unsigned char>& bytes) {
  std::ofstream output(path, std::ios::binary);
  output.write(reinterpret_cast<const char*>(bytes.data()),
               static_cast<std::streamsize>(bytes.size()));
  output.close();
  expect(::chmod(path.c_str(), 0600) == 0,
         "fixture should not need executable permission");
  const int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
  expect(fd >= 0, "failed to open ELF fixture");
  return native_mcp::ReadOnlyFile{native_mcp::UniqueFd{fd}, bytes.size(),
                                  bytes.size()};
}

void test_elf64_metadata() {
  TempDirectory directory;
  auto file = open_fixture(directory.path() / "sample.elf", make_elf64());
  native_mcp::ElfAnalyzer analyzer;
  const auto inspected = analyzer.inspect(file);
  if (!inspected.result.has_value()) {
    std::cerr << "ELF error: " << inspected.error->message << '\n';
  }
  expect(inspected.result.has_value(), "valid ELF64 metadata must parse");
  const auto& result = *inspected.result;
  expect(result.elf_class == "ELF64" && result.endianness == "little",
         "ELF identity must be reported");
  expect(result.machine == "x86_64" && result.file_type == "shared_object",
         "machine and type must be reported");
  expect(result.interpreter.has_value() &&
             *result.interpreter == "/lib64/ld-linux-x86-64.so.2",
         "interpreter must be read from the bounded segment");
  expect(result.needed_libraries.size() == 1U &&
             result.needed_libraries[0] == "libc.so.6",
         "DT_NEEDED names must be resolved through a load segment");
  expect(result.build_id.has_value() && *result.build_id == "12345678",
         "GNU build ID must be decoded");
  expect(result.stack_policy == "non_executable" && result.relro == "full",
         "stack and RELRO hardening signals must be derived");
  expect(result.position_independent && result.pie_executable &&
             !result.writable_executable_load_segment,
         "PIE and writable-executable segment signals must be reported");
  expect(result.program_header_count == 6U && result.segments.size() == 6U,
         "bounded segment summaries must be returned");
  expect(result.metadata_bytes_read <= analyzer.limits().max_metadata_bytes,
         "metadata reads must stay inside the configured budget");
}

void test_elf32_big_endian() {
  TempDirectory directory;
  auto file = open_fixture(directory.path() / "sample32.elf",
                           make_elf32_big_endian());
  const auto inspected = native_mcp::ElfAnalyzer{}.inspect(file);
  expect(inspected.result.has_value(), "minimal big-endian ELF32 must parse");
  expect(inspected.result->elf_class == "ELF32" &&
             inspected.result->endianness == "big" &&
             inspected.result->machine == "arm" &&
             inspected.result->entry_point == "0x10203040",
         "ELF32 fields must respect byte order");
}

void test_invalid_and_bounded_inputs() {
  TempDirectory directory;
  std::vector<unsigned char> invalid(64U, 0U);
  auto file = open_fixture(directory.path() / "not-elf", invalid);
  auto inspected = native_mcp::ElfAnalyzer{}.inspect(file);
  expect(inspected.error.has_value() &&
             inspected.error->code == native_mcp::ElfAnalysisErrorCode::kInvalidFormat,
         "non-ELF files must be rejected");

  auto malformed = make_elf64();
  malformed[EI_CLASS] = ELFCLASSNONE;
  file = open_fixture(directory.path() / "invalid-class", malformed);
  inspected = native_mcp::ElfAnalyzer{}.inspect(file);
  expect(inspected.error.has_value() &&
             inspected.error->code ==
                 native_mcp::ElfAnalysisErrorCode::kUnsupportedFeature,
         "unsupported ELF classes must be rejected");

  malformed = make_elf64();
  malformed[EI_DATA] = ELFDATANONE;
  file = open_fixture(directory.path() / "invalid-byte-order", malformed);
  inspected = native_mcp::ElfAnalyzer{}.inspect(file);
  expect(inspected.error.has_value() &&
             inspected.error->code ==
                 native_mcp::ElfAnalysisErrorCode::kUnsupportedFeature,
         "unsupported ELF byte orders must be rejected");

  malformed = make_elf64();
  put64(malformed, 32U, 1000U);
  file = open_fixture(directory.path() / "bad-table", malformed);
  inspected = native_mcp::ElfAnalyzer{}.inspect(file);
  expect(inspected.error.has_value(),
         "out-of-range program-header tables must be rejected");

  malformed = make_elf64();
  put64(malformed, 64U + 8U, 1000U);
  file = open_fixture(directory.path() / "bad-segment", malformed);
  inspected = native_mcp::ElfAnalyzer{}.inspect(file);
  expect(inspected.error.has_value(),
         "out-of-range program segments must be rejected");

  malformed = make_elf64();
  put16(malformed, 56U, PN_XNUM);
  file = open_fixture(directory.path() / "extended", malformed);
  inspected = native_mcp::ElfAnalyzer{}.inspect(file);
  expect(inspected.error.has_value() &&
             inspected.error->code ==
                 native_mcp::ElfAnalysisErrorCode::kUnsupportedFeature,
         "unsupported extended numbering must fail explicitly");

  malformed = make_elf64();
  put16(malformed, 52U, 65U);
  file = open_fixture(directory.path() / "bad-header-size", malformed);
  inspected = native_mcp::ElfAnalyzer{}.inspect(file);
  expect(inspected.error.has_value() &&
             inspected.error->code == native_mcp::ElfAnalysisErrorCode::kInvalidFormat,
         "nonstandard ELF header sizes must be rejected");

  malformed = make_elf64();
  put16(malformed, 54U, 57U);
  file = open_fixture(directory.path() / "bad-program-entry-size", malformed);
  inspected = native_mcp::ElfAnalyzer{}.inspect(file);
  expect(inspected.error.has_value() &&
             inspected.error->code == native_mcp::ElfAnalysisErrorCode::kInvalidFormat,
         "nonstandard program-header entry sizes must be rejected");

  malformed = make_elf64();
  put64(malformed, 512U + 4U * 16U, DT_NEEDED);
  file = open_fixture(directory.path() / "unterminated-dynamic", malformed);
  inspected = native_mcp::ElfAnalyzer{}.inspect(file);
  expect(inspected.error.has_value() &&
             inspected.error->code == native_mcp::ElfAnalysisErrorCode::kInvalidFormat,
         "unterminated dynamic tables must be rejected");

  native_mcp::ElfInspectionLimits dynamic_limit;
  dynamic_limit.max_dynamic_entries = 4U;
  file = open_fixture(directory.path() / "dynamic-count", make_elf64());
  inspected = native_mcp::ElfAnalyzer{dynamic_limit}.inspect(file);
  expect(inspected.error.has_value() &&
             inspected.error->code ==
                 native_mcp::ElfAnalysisErrorCode::kMetadataTooLarge,
         "dynamic entry counts must be bounded before allocation");

  native_mcp::ElfInspectionLimits string_limit;
  string_limit.max_dynamic_string_bytes = 8U;
  file = open_fixture(directory.path() / "dynamic-strings", make_elf64());
  inspected = native_mcp::ElfAnalyzer{string_limit}.inspect(file);
  expect(inspected.error.has_value() &&
             inspected.error->code ==
                 native_mcp::ElfAnalysisErrorCode::kMetadataTooLarge,
         "dynamic string tables must be bounded before allocation");

  native_mcp::ElfInspectionLimits note_limit;
  note_limit.max_note_bytes = 19U;
  file = open_fixture(directory.path() / "notes", make_elf64());
  inspected = native_mcp::ElfAnalyzer{note_limit}.inspect(file);
  expect(inspected.error.has_value() &&
             inspected.error->code ==
                 native_mcp::ElfAnalysisErrorCode::kMetadataTooLarge,
         "note data must be bounded before allocation");

  native_mcp::ElfInspectionLimits tiny;
  tiny.max_metadata_bytes = 32U;
  file = open_fixture(directory.path() / "budget", make_elf64());
  inspected = native_mcp::ElfAnalyzer{tiny}.inspect(file);
  expect(inspected.error.has_value() &&
             inspected.error->code ==
                 native_mcp::ElfAnalysisErrorCode::kMetadataTooLarge,
         "metadata byte budgets must be enforced before allocation");
}

void test_security_signals_and_output_bounds() {
  TempDirectory directory;
  auto bytes = make_elf64();
  put32(bytes, 64U + 4U, PF_R | PF_W | PF_X);
  auto file = open_fixture(directory.path() / "writable-executable.elf", bytes);
  native_mcp::ElfInspectionLimits limits;
  limits.max_segment_summaries = 2U;
  const auto inspected = native_mcp::ElfAnalyzer{limits}.inspect(file);
  expect(inspected.result.has_value(), "bounded W+X fixture must remain parseable");
  expect(inspected.result->writable_executable_load_segment,
         "writable executable load segments must be disclosed");
  expect(inspected.result->segments.size() == 2U &&
             inspected.result->segment_summaries_truncated,
         "segment output must stop at the configured result limit");
}

void test_real_process_image() {
  const int fd = ::open("/proc/self/exe", O_RDONLY | O_CLOEXEC);
  if (fd < 0) {
    return;
  }
  struct stat metadata {};
  expect(::fstat(fd, &metadata) == 0 && metadata.st_size > 0,
         "process image metadata must be readable");
  native_mcp::ReadOnlyFile file{native_mcp::UniqueFd{fd},
                                static_cast<std::uint64_t>(metadata.st_size),
                                static_cast<std::uint64_t>(metadata.st_size)};
  const auto inspected = native_mcp::ElfAnalyzer{}.inspect(file);
  if (!inspected.result.has_value()) {
    std::cerr << "real ELF error: " << inspected.error->message << '\n';
  }
  expect(inspected.result.has_value(),
         "the running Linux test executable must be inspectable");
  expect(inspected.result->program_header_count > 0U &&
             !inspected.result->machine.empty(),
         "real ELF inspection must return useful bounded metadata");
}

}  // namespace

int main() {
  test_elf64_metadata();
  test_elf32_big_endian();
  test_invalid_and_bounded_inputs();
  test_security_signals_and_output_bounds();
  test_real_process_image();
  std::cout << "All ELF analysis tests passed\n";
  return EXIT_SUCCESS;
}
