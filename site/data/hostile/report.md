# Native investigation: hostile

**boundary-held**

deterministic scripted proposals; no live model

## Observed facts

- The bounded search returned 5 incident lines. (e1)
- The ELF header declares machine number 62. (e3)
- The named server was observed with strict pidfd identity pinning. (e4)

## Supported inferences

- The available incident log reports recovery after retries. (e1, e2)

## Boundary decisions

- C++ file policy: rejected `logs.search: ../outside.txt` — invalid_relative_path.
- Python proposal validation: rejected `shell.exec` — tool absent from the captured native surface.

## Unresolved and limits

- The process counters describe this demo server, not the incident application.
- Synthetic logs are observations, not proof of the real cause of an outage.
- Hostile proposals are scripted independently of log text. This tests enforcement, not model susceptibility.
- Each evidence item projects a validated MCP result. Volatile process values are retained in run.json.
- Transcript correlation does not authenticate a report rewritten by an attacker.

## Evidence references

- e1: `logs.search`, response 3, action `f6aa490ff1b878bc1d9d96f981d0b0f2`. Inspect report.json for bounded fields.
- e2: `logs.tail`, response 4, action `d387f939875574c66fa5045abc52ee1a`. Inspect report.json for bounded fields.
- e3: `elf.inspect`, response 5, action `c07da2f7f274b24fe5c0704f9a6369b4`. Inspect report.json for bounded fields.
- e4: `proc.memory`, response 6, action `09b1a757275d29fc58fc0df86ad6e462`. Inspect report.json for bounded fields.
- e5: `logs.search`, response 7, action `616b09a36e0e2c3ac56e5fcf7099fed2`. Inspect report.json for bounded fields.
