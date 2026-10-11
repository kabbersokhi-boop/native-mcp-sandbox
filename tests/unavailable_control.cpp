#include <linux/filter.h>
#include <linux/seccomp.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

#include <cerrno>
#include <cstddef>
#include <iostream>
#include <string_view>

int main(int argc, char** argv) {
  if (argc < 3) {
    std::cerr << "usage: unavailable_control openat2|pidfd_open SERVER [ARGS...]\n";
    return 64;
  }
  const std::string_view control{argv[1]};
  if (control != "openat2" && control != "pidfd_open") {
    return 64;
  }
  const unsigned int denied = control == "openat2" ? SYS_openat2 : SYS_pidfd_open;
  sock_filter instructions[] = {
      BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(seccomp_data, nr)),
      BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, denied, 0, 1),
      BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | ENOSYS),
      BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
  };
  sock_fprog program{4, instructions};
  if (::prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0 ||
      ::prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program) != 0) {
    std::cerr << "test syscall filter unavailable\n";
    return 77;
  }
  ::execv(argv[2], &argv[2]);
  std::cerr << "test server exec failed\n";
  return 126;
}
