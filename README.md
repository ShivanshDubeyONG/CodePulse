# CodePulse

CodePulse is an experimental codebase intelligence tool.

Phase 1 currently proves the core execution pipeline:

Repository
  → Docker sandbox
  → benchmark
  → latency result

The target repository executes inside a disposable, resource-constrained Docker container, and its benchmark output is parsed into a structured result.
