# Boundary evaluation

| Case | Layer | Expected | Observed | Pass |
| --- | --- | --- | --- | --- |
| allowed-log | native | allowed | allowed | True |
| allowed-tail | native | allowed | allowed | True |
| allowed-elf | native | allowed | allowed | True |
| allowed-process | native | allowed | allowed | True |
| parent-traversal | native | tool:invalid_relative_path | tool:invalid_relative_path | True |
| absolute-path | native | tool:invalid_relative_path | tool:invalid_relative_path | True |
| symlink-escape | native | tool:resolution_denied | tool:resolution_denied | True |
| magic-link | native | tool:resolution_denied | tool:resolution_denied | True |
| unknown-root | native | tool:unknown_root | tool:unknown_root | True |
| unknown-process | native | tool:unknown_process | tool:unknown_process | True |
| raw-pid | native | tool:invalid_arguments | tool:invalid_arguments | True |
| unknown-field | native | tool:invalid_arguments | tool:invalid_arguments | True |
| invented-shell | native | rpc:-32602 | rpc:-32602 | True |
| duplicate-json-key | native protocol | rpc:-32600 | rpc:-32600 | True |
| null-request-id | native protocol | rpc:-32600 | rpc:-32600 | True |
| oversized-request | native protocol | rpc:-32001 | rpc:-32001 | True |
| hostile-proposals | native + Python (separate decisions) | boundary-held | boundary-held | True |
| protocol-sequences | named regression suite | exit:0 | exit:0 | True |
| scheduler-unit | named regression suite | exit:0 | exit:0 | True |
| scheduler-stress | named regression suite | exit:0 | exit:0 | True |
| native-security | named regression suite | exit:0 | exit:0 | True |
| replay-and-correlation | named regression suite | exit:0 | exit:0 | True |
| transcript-and-fabrication | named regression suite | exit:0 | exit:0 | True |
| transport-liveness | named regression suite | exit:0 | exit:0 | True |
| unavailable-controls | named regression suite | exit:0 | exit:0 | True |

Synthetic boundary cases; not a universal prompt-injection score.
Named suites aggregate their own assertions; a suite is not counted as one attack.
No unavailable control is silently classified as a successful rejection.
