# Documentation writing style

## Reference

The active technical documents use an ASD-STE100 Issue 9 aligned style.
ASD-STE100 is a controlled language for technical documentation.

This project does not claim formal certification by ASD or by an approved checker.
A maintainer must review technical meaning after each style change.

## Project rules

Use these rules for new technical text:

1. Use short sentences.
2. Put one main statement in each sentence.
3. Use active voice when the actor is important.
4. Use direct imperative sentences for procedures.
5. Use the same term for the same object or action.
6. Do not use a synonym only for variation.
7. Put a condition before the action when the order is important.
8. Use lists for multiple requirements, limits, or steps.
9. Keep warnings, limits, and non-claims explicit.
10. Do not change code, commands, identifiers, protocol fields, or file names for style.

## Technical terms

The project uses these technical nouns and verbs when necessary:

- MCP
- JSON-RPC
- JSON
- SAX
- DOM
- C++20
- coroutine
- libFuzzer
- AddressSanitizer
- UndefinedBehaviorSanitizer
- ThreadSanitizer
- `openat2`
- pidfd
- procfs
- ELF
- AF_UNIX
- FIFO
- runtime policy
- tool call
- request ID
- standard input
- standard output
- standard error

Use each term with one stable meaning.
Define a new project-specific term before you use it in a procedure.

## Protected text

Do not rewrite these items for language style:

- license text
- third-party license text
- legal notices
- code examples
- command examples
- JSON examples
- API names
- file names
- commit IDs
- tag names
- exact error codes

A language change must not change a security boundary, a resource limit, or a release fact.
