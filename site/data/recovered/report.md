# Native investigation: recovered

**recovery-observed**

deterministic scripted proposals; no live model

## Observed facts

- The bounded search returned 4 incident lines. (e1)
- The ELF header declares machine number 62. (e3)
- The named server was observed with strict pidfd identity pinning. (e4)

## Supported inferences

- The available incident log reports recovery after retries. (e1, e2)

## Boundary decisions

All four authorized evidence calls completed.

## Unresolved and limits

- The process counters describe this demo server, not the incident application.
- Synthetic logs are observations, not proof of the real cause of an outage.
- Hostile proposals are scripted independently of log text. This tests enforcement, not model susceptibility.
- Each evidence item projects a validated MCP result. Volatile process values are retained in run.json.
- Transcript correlation does not authenticate a report rewritten by an attacker.

## Evidence references

- e1: `logs.search`, response 3, action `c4c82ff1da69fd1e3bc48d24667b4996`. Inspect report.json for bounded fields.
- e2: `logs.tail`, response 4, action `274c23127eee9a18ca6075cd33c43d40`. Inspect report.json for bounded fields.
- e3: `elf.inspect`, response 5, action `e0387164e4ab51e0fe5e4ef8ca6bc37d`. Inspect report.json for bounded fields.
- e4: `proc.memory`, response 6, action `6ac509b7821d9e4d4ba4e949e2a1f171`. Inspect report.json for bounded fields.
