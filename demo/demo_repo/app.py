"""Deterministic workload for the demo repository."""

def run_workload() -> int:
    """Perform a deterministic CPU-bound calculation."""
    total = 0
    for i in range(100_000):
        total += i * i
    return total


if __name__ == "__main__":
    print(f"Workload result: {run_workload()}")
