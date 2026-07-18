#include <cerrno>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <string_view>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

namespace {

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
    const auto remaining = data.size() - written;
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

}  // namespace

int main(int argc, char* argv[]) {
  expect(argc == 2, "expected server executable path");

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
    ::execl(argv[1], argv[1], static_cast<char*>(nullptr));
    _exit(127);
  }

  close_fd(stdin_pipe[0]);
  close_fd(stdout_pipe[1]);
  close_fd(stderr_pipe[1]);

  const std::string input =
      "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"ping\"}\r\n"
      "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"integration-client\",\"version\":\"1.0\"}}}\n"
      "{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n"
      "{\"jsonrpc\":\"2.0\",\"method\":\"unsupported/notification\"}\n"
      "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/list\"}\n";
  write_all(stdin_pipe[1], input);
  close_fd(stdin_pipe[1]);

  const std::string standard_output = read_all(stdout_pipe[0]);
  const std::string standard_error = read_all(stderr_pipe[0]);
  close_fd(stdout_pipe[0]);
  close_fd(stderr_pipe[0]);

  int status = 0;
  expect(::waitpid(child, &status, 0) == child, "failed to wait for child");
  expect(WIFEXITED(status) && WEXITSTATUS(status) == 0,
         "server must exit successfully on EOF");

  const std::string expected_output =
      "{\"id\":1,\"jsonrpc\":\"2.0\",\"result\":{}}\n"
      "{\"id\":2,\"jsonrpc\":\"2.0\",\"result\":{\"capabilities\":{\"tools\":{}},\"protocolVersion\":\"2025-11-25\",\"serverInfo\":{\"name\":\"native-mcp-sandbox\",\"version\":\"0.3.0\"}}}\n"
      "{\"id\":3,\"jsonrpc\":\"2.0\",\"result\":{\"tools\":[]}}\n";
  expect(standard_output == expected_output,
         "stdout must contain only deterministic JSON-RPC response lines");
  expect(standard_error.find("ignored unsupported notification") !=
             std::string::npos,
         "unsupported notification must be diagnosed on stderr");
  expect(standard_error.find("integration-client") == std::string::npos,
         "stderr must not echo untrusted request content");

  std::cout << "All stdio integration tests passed\n";
  return EXIT_SUCCESS;
}
