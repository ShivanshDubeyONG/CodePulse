"""Benchmark script measuring deterministic workload execution time."""

import time
from app import run_workload

# Warmup run
_ = run_workload()

# Measured run
start = time.perf_counter()
_ = run_workload()
latency = time.perf_counter() - start

print(f"LATENCY={latency:.6f}")
