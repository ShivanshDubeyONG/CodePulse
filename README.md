# CodePulse

CodePulse is an experimental codebase intelligence tool.

Phase 1 proves the core execution pipeline:

Repository
  → Docker sandbox
  → repeated benchmark measurements
  → structured statistical results

The target repository executes inside disposable, resource-constrained Docker containers.

## Configuration

In `codepulse.yaml`, configure repeated runs under `benchmark` or at top level:

```yaml
setup:
  command: "python -c \"print('setup ok')\""

benchmark:
  command: "python benchmark.py"
  runs: 5

result:
  type: "stdout"
  pattern: "LATENCY=(?P<latency>[0-9.]+)"
```

## Repeated Measurements

CodePulse executes the benchmark independently for each configured run and aggregates:
- `successful_run_count` and `failed_run_count`
- `raw_latency_samples`
- Summary statistics across successful runs: `min_latency`, `max_latency`, `mean_latency`, and `median_latency`
- Individual run records (`runs` containing stdout, stderr, exit code, duration)
