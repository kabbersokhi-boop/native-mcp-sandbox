#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cerrno>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace {

namespace fs = std::filesystem;
using Json = nlohmann::json;

void fail(const std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void expect(const bool condition, const std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

void close_fd(const int fd) {
  if (fd >= 0) {
    (void)::close(fd);
  }
}

void write_all(const int fd, const std::string& data) {
  std::size_t written = 0U;
  while (written < data.size()) {
    const std::size_t remaining = data.size() - written;
    const ssize_t count = ::write(fd, data.data() + written, remaining);
    if (count < 0) {
      if (errno == EINTR) {
        continue;
      }
      fail("failed to write child stdin");
    }
    written += static_cast<std::size_t>(count);
  }
}

std::string read_all(const int fd) {
  std::string output;
  char buffer[4096];
  for (;;) {
    const ssize_t count = ::read(fd, buffer, sizeof(buffer));
    if (count == 0) {
      break;
    }
    if (count < 0) {
      if (errno == EINTR) {
        continue;
      }
      fail("failed to read child output");
    }
    output.append(buffer, static_cast<std::size_t>(count));
  }
  return output;
}

struct ProcessOutput final {
  std::string standard_output;
  std::string standard_error;
};

ProcessOutput run_server(const std::string& executable,
                         const std::vector<std::string>& arguments,
                         const std::string& input) {
  int stdin_pipe[2]{-1, -1};
  int stdout_pipe[2]{-1, -1};
  int stderr_pipe[2]{-1, -1};
  expect(::pipe(stdin_pipe) == 0, "failed to create stdin pipe");
  expect(::pipe(stdout_pipe) == 0, "failed to create stdout pipe");
  expect(::pipe(stderr_pipe) == 0, "failed to create stderr pipe");

  const pid_t child = ::fork();
  expect(child >= 0, "failed to fork");
  if (child == 0) {
    if (::dup2(stdin_pipe[0], STDIN_FILENO) < 0 ||
        ::dup2(stdout_pipe[1], STDOUT_FILENO) < 0 ||
        ::dup2(stderr_pipe[1], STDERR_FILENO) < 0) {
      _exit(126);
    }
    close_fd(stdin_pipe[0]);
    close_fd(stdin_pipe[1]);
    close_fd(stdout_pipe[0]);
    close_fd(stdout_pipe[1]);
    close_fd(stderr_pipe[0]);
    close_fd(stderr_pipe[1]);

    std::vector<char*> argv;
    argv.reserve(arguments.size() + 2U);
    argv.push_back(const_cast<char*>(executable.c_str()));
    for (const std::string& argument : arguments) {
      argv.push_back(const_cast<char*>(argument.c_str()));
    }
    argv.push_back(nullptr);
    ::execv(executable.c_str(), argv.data());
    _exit(127);
  }

  close_fd(stdin_pipe[0]);
  close_fd(stdout_pipe[1]);
  close_fd(stderr_pipe[1]);
  write_all(stdin_pipe[1], input);
  close_fd(stdin_pipe[1]);

  ProcessOutput output{.standard_output = read_all(stdout_pipe[0]),
                       .standard_error = read_all(stderr_pipe[0])};
  close_fd(stdout_pipe[0]);
  close_fd(stderr_pipe[0]);

  int status = 0;
  expect(::waitpid(child, &status, 0) == child, "failed to wait for child");
  expect(WIFEXITED(status) && WEXITSTATUS(status) == 0,
         "server must exit successfully on EOF");
  return output;
}

std::vector<Json> parse_lines(const std::string& output) {
  std::vector<Json> messages;
  std::istringstream stream{output};
  std::string line;
  while (std::getline(stream, line)) {
    expect(!line.empty(), "protocol output must not contain blank lines");
    messages.push_back(Json::parse(line));
  }
  return messages;
}

class TempDirectory final {
 public:
  TempDirectory() {
    std::string pattern = "/tmp/native-mcp-stdio-XXXXXX";
    pattern.push_back('\0');
    char* created = ::mkdtemp(pattern.data());
    expect(created != nullptr, "failed to create temporary directory");
    path_ = created;
  }
  ~TempDirectory() {
    std::error_code ignored;
    fs::remove_all(path_, ignored);
  }
  TempDirectory(const TempDirectory&) = delete;
  TempDirectory& operator=(const TempDirectory&) = delete;
  [[nodiscard]] const fs::path& path() const noexcept { return path_; }

 private:
  fs::path path_;
};

void test_unconfigured_server(const std::string& executable) {
  const std::string input =
      "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"ping\"}\r\n"
      "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"integration-client\",\"version\":\"1.0\"}}}\n"
      "{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n"
      "{\"jsonrpc\":\"2.0\",\"method\":\"unsupported/notification\"}\n"
      "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/list\"}\n";
  const ProcessOutput output = run_server(executable, {}, input);
  const std::string expected =
      "{\"id\":1,\"jsonrpc\":\"2.0\",\"result\":{}}\n"
      "{\"id\":2,\"jsonrpc\":\"2.0\",\"result\":{\"capabilities\":{\"tools\":{}},\"protocolVersion\":\"2025-11-25\",\"serverInfo\":{\"name\":\"native-mcp-sandbox\",\"version\":\"0.4.0\"}}}\n"
      "{\"id\":3,\"jsonrpc\":\"2.0\",\"result\":{\"tools\":[]}}\n";
  expect(output.standard_output == expected,
         "unconfigured stdout must remain deterministic and tool-free");
  expect(output.standard_error.find("ignored unsupported notification") !=
             std::string::npos,
         "unsupported notification must be diagnosed on stderr");
  expect(output.standard_error.find("integration-client") == std::string::npos,
         "stderr must not echo untrusted request content");
}

void test_configured_log_tools(const std::string& executable) {
  TempDirectory directory;
  const fs::path log_path = directory.path() / "app.log";
  {
    std::ofstream log{log_path, std::ios::binary};
    log << "boot ok\nERROR first\nquiet\nerror second\n";
  }
  const fs::path config_path = directory.path() / "policy.json";
  {
    std::ofstream config{config_path, std::ios::binary};
    config << "{\"version\":1,\"roots\":[{\"name\":\"logs\",\"path\":\""
           << directory.path().string()
           << "\",\"maxFileBytes\":1048576}]}";
  }

  const std::string input =
      "{\"jsonrpc\":\"2.0\",\"id\":10,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"tool-client\",\"version\":\"1\"}}}\n"
      "{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n"
      "{\"jsonrpc\":\"2.0\",\"id\":11,\"method\":\"tools/list\"}\n"
      "{\"jsonrpc\":\"2.0\",\"id\":12,\"method\":\"tools/call\",\"params\":{\"name\":\"logs.search\",\"arguments\":{\"root\":\"logs\",\"path\":\"app.log\",\"query\":\"error\",\"caseSensitive\":false,\"maxMatches\":5}}}\n"
      "{\"jsonrpc\":\"2.0\",\"id\":13,\"method\":\"tools/call\",\"params\":{\"name\":\"logs.tail\",\"arguments\":{\"root\":\"logs\",\"path\":\"app.log\",\"maxLines\":2}}}\n";
  const ProcessOutput output = run_server(
      executable,
      {"--policy-config", config_path.string(),
       "--allow-legacy-descriptor-walk"},
      input);
  const std::vector<Json> messages = parse_lines(output.standard_output);
  expect(messages.size() == 4U, "configured transcript must return four responses");
  expect(messages[0]["result"]["serverInfo"]["version"] == "0.4.0",
         "configured initialize must report the Phase 3 version");
  const Json& tools = messages[1]["result"]["tools"];
  expect(tools.is_array() && tools.size() == 2U &&
             tools[0]["name"] == "logs.search" &&
             tools[1]["name"] == "logs.tail",
         "configured server must advertise only the two Phase 3 tools");
  expect(messages[2]["result"]["isError"] == false &&
             messages[2]["result"]["structuredContent"]["matches"].size() == 2U,
         "logs.search must run through the real configured process");
  expect(messages[3]["result"]["isError"] == false &&
             messages[3]["result"]["structuredContent"]["lines"].size() == 2U &&
             messages[3]["result"]["structuredContent"]["lines"][1]["preview"] ==
                 "error second",
         "logs.tail must return the final requested lines");
  expect(output.standard_error.find("legacy descriptor walk enabled") !=
             std::string::npos,
         "explicit legacy startup must disclose its weaker containment");
  expect(output.standard_error.find("tool-client") == std::string::npos &&
             output.standard_error.find("error second") == std::string::npos,
         "configured diagnostics must not echo client or log contents");
}

}  // namespace

int main(int argc, char* argv[]) {
  expect(argc == 2, "expected server executable path");
  const std::string executable{argv[1]};
  test_unconfigured_server(executable);
  test_configured_log_tools(executable);
  std::cout << "All stdio integration tests passed\n";
  return EXIT_SUCCESS;
}
