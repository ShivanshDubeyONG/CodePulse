"""Benchmark execution and latency parsing for CodePulse."""

import re
import statistics
import sys
from pathlib import Path
from typing import List, Optional, Union
from pydantic import BaseModel, Field
from codepulse.config import load_config, CodePulseConfig
from codepulse.sandbox import (
    DockerSandbox,
    ExecutionOutput,
    SandboxError,
    DockerUnavailableError,
    is_docker_available,
)


class BenchmarkResult(BaseModel):
    """Structured result of a single benchmark execution."""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    latency: Optional[float] = None
    error: Optional[str] = None


class RepeatedBenchmarkResult(BenchmarkResult):
    """Structured result for repeated benchmark measurements."""
    runs: List[BenchmarkResult] = Field(default_factory=list)
    total_runs: int = 0
    successful_run_count: int = 0
    failed_run_count: int = 0
    raw_latency_samples: List[float] = Field(default_factory=list)
    min_latency: Optional[float] = None
    max_latency: Optional[float] = None
    mean_latency: Optional[float] = None
    median_latency: Optional[float] = None

    @property
    def successful_runs(self) -> int:
        return self.successful_run_count

    @property
    def failed_runs(self) -> int:
        return self.failed_run_count

    @property
    def raw_latencies(self) -> List[float]:
        return self.raw_latency_samples


def parse_latency(stdout: str, pattern: str = r"LATENCY=(?P<latency>[0-9.]+)") -> float:
    """Extract numeric latency value from stdout using a regex pattern.
    
    Raises:
        ValueError: If pattern does not match or matched value cannot be converted to float.
    """
    if not stdout or not stdout.strip():
        raise ValueError("Stdout is empty; cannot parse latency.")

    match = re.search(pattern, stdout)
    if not match:
        raise ValueError(f"Pattern '{pattern}' did not match output:\n{stdout[:200]}")

    group_dict = match.groupdict()
    if "latency" in group_dict and group_dict["latency"] is not None:
        raw_val = group_dict["latency"]
    elif match.groups():
        raw_val = match.group(1)
    else:
        raw_val = match.group(0)

    try:
        return float(raw_val)
    except ValueError as exc:
        raise ValueError(f"Matched value '{raw_val}' cannot be converted to float: {exc}") from exc


def _execute_single_run(
    sandbox: DockerSandbox,
    command: str,
    pattern: str,
) -> BenchmarkResult:
    """Execute a single benchmark run in the sandbox, capturing output and parsing latency."""
    try:
        bench_out = sandbox.execute(command)
    except SandboxError as exc:
        return BenchmarkResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            duration=0.0,
            error=f"Sandbox error during benchmark: {exc}",
        )

    if bench_out.exit_code != 0:
        return BenchmarkResult(
            success=False,
            exit_code=bench_out.exit_code,
            stdout=bench_out.stdout,
            stderr=bench_out.stderr,
            duration=bench_out.duration,
            error=f"Benchmark exited with non-zero code {bench_out.exit_code}: {bench_out.stderr.strip()}",
        )

    try:
        latency = parse_latency(bench_out.stdout, pattern)
        return BenchmarkResult(
            success=True,
            exit_code=bench_out.exit_code,
            stdout=bench_out.stdout,
            stderr=bench_out.stderr,
            duration=bench_out.duration,
            latency=latency,
        )
    except ValueError as exc:
        return BenchmarkResult(
            success=False,
            exit_code=bench_out.exit_code,
            stdout=bench_out.stdout,
            stderr=bench_out.stderr,
            duration=bench_out.duration,
            error=f"Latency parsing error: {exc}",
        )


def run_benchmark(
    repo_path: Union[str, Path],
    image: str = "python:3.11-slim",
    cpu_limit: float = 2.0,
    memory_limit: str = "2GB",
    timeout_seconds: int = 60,
    sandbox: Optional[DockerSandbox] = None,
    runs: Optional[int] = None,
) -> RepeatedBenchmarkResult:
    """Execute the repository benchmark inside a Docker sandbox across multiple runs and return structured results."""
    repo = Path(repo_path).resolve()
    if not repo.exists() or not repo.is_dir():
        return RepeatedBenchmarkResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            duration=0.0,
            error=f"Repository path does not exist or is not a directory: {repo}",
            total_runs=0,
            successful_run_count=0,
            failed_run_count=0,
            raw_latency_samples=[],
        )

    # 1. Load and validate configuration
    try:
        config = load_config(repo)
    except Exception as exc:
        return RepeatedBenchmarkResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            duration=0.0,
            error=f"Configuration error: {exc}",
            total_runs=0,
            successful_run_count=0,
            failed_run_count=0,
            raw_latency_samples=[],
        )

    # Determine total runs (explicit parameter overrides config)
    total_runs = runs if runs is not None else config.benchmark.runs
    if total_runs < 1:
        return RepeatedBenchmarkResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            duration=0.0,
            error=f"Invalid runs count: {total_runs}. Must be >= 1.",
            total_runs=0,
            successful_run_count=0,
            failed_run_count=0,
            raw_latency_samples=[],
        )

    # 2. Instantiate sandbox
    active_sandbox = sandbox or DockerSandbox(
        repo_path=repo,
        image=image,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        timeout_seconds=timeout_seconds,
    )

    # 3. Execute setup command once if configured
    setup_duration = 0.0
    if config.setup and config.setup.command and config.setup.command.strip():
        try:
            setup_out = active_sandbox.execute(config.setup.command.strip())
            setup_duration = setup_out.duration
            if setup_out.exit_code != 0:
                return RepeatedBenchmarkResult(
                    success=False,
                    exit_code=setup_out.exit_code,
                    stdout=setup_out.stdout,
                    stderr=setup_out.stderr,
                    duration=setup_out.duration,
                    error=f"Setup command failed with exit code {setup_out.exit_code}: {setup_out.stderr.strip()}",
                    total_runs=total_runs,
                    successful_run_count=0,
                    failed_run_count=total_runs,
                    raw_latency_samples=[],
                )
        except SandboxError as exc:
            return RepeatedBenchmarkResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration=0.0,
                error=f"Sandbox error during setup: {exc}",
                total_runs=total_runs,
                successful_run_count=0,
                failed_run_count=total_runs,
                raw_latency_samples=[],
            )

    # 4. Execute repeated benchmark runs independently
    run_results: List[BenchmarkResult] = []
    for _ in range(total_runs):
        run_res = _execute_single_run(
            sandbox=active_sandbox,
            command=config.benchmark.command.strip(),
            pattern=config.result.pattern,
        )
        run_results.append(run_res)

    successful_runs = [r for r in run_results if r.success and r.latency is not None]
    failed_runs = [r for r in run_results if not r.success]
    successful_count = len(successful_runs)
    failed_count = len(failed_runs)
    raw_samples = [r.latency for r in successful_runs if r.latency is not None]

    total_duration = setup_duration + sum(r.duration for r in run_results)
    combined_stdout = "\n".join(r.stdout for r in run_results if r.stdout)
    combined_stderr = "\n".join(r.stderr for r in run_results if r.stderr)

    # If ALL runs fail, return a clear failed result
    if successful_count == 0:
        last_error = run_results[-1].error if run_results else "No runs executed"
        last_exit = run_results[-1].exit_code if run_results else -1
        return RepeatedBenchmarkResult(
            success=False,
            exit_code=last_exit,
            stdout=combined_stdout,
            stderr=combined_stderr,
            duration=round(total_duration, 4),
            latency=None,
            error=f"All {total_runs} benchmark runs failed. Last error: {last_error}",
            runs=run_results,
            total_runs=total_runs,
            successful_run_count=0,
            failed_run_count=failed_count,
            raw_latency_samples=[],
            min_latency=None,
            max_latency=None,
            mean_latency=None,
            median_latency=None,
        )

    # Compute statistics strictly from successful runs
    min_val = round(min(raw_samples), 6)
    max_val = round(max(raw_samples), 6)
    mean_val = round(statistics.mean(raw_samples), 6)
    median_val = round(statistics.median(raw_samples), 6)

    error_msg = None
    if failed_count > 0:
        error_msg = f"{failed_count} of {total_runs} benchmark runs failed."

    return RepeatedBenchmarkResult(
        success=True,
        exit_code=0,
        stdout=combined_stdout,
        stderr=combined_stderr,
        duration=round(total_duration, 4),
        latency=mean_val,
        error=error_msg,
        runs=run_results,
        total_runs=total_runs,
        successful_run_count=successful_count,
        failed_run_count=failed_count,
        raw_latency_samples=raw_samples,
        min_latency=min_val,
        max_latency=max_val,
        mean_latency=mean_val,
        median_latency=median_val,
    )


def main():
    """CLI entry point to execute a benchmark on a repository."""
    target_repo = sys.argv[1] if len(sys.argv) > 1 else "demo/demo_repo"
    repo_path = Path(target_repo).resolve()
    repo_name = repo_path.name

    print(f"Repository: {repo_name}")
    print("Environment: Python 3.11")
    print("CPU: 2")
    print("Memory: 2GB\n")

    if not is_docker_available():
        print("Docker status: NOT AVAILABLE ON HOST")
        print("Notice: CodePulse requires Docker to execute repository code inside a disposable sandbox.")
        print("Simulating container execution for prototype validation...\n")

        # Create a mock sandbox to display the prototype output pipeline
        class MockSandbox(DockerSandbox):
            def execute(self, command: str) -> ExecutionOutput:
                if "benchmark.py" in command:
                    return ExecutionOutput(
                        command=command,
                        exit_code=0,
                        stdout="LATENCY=0.123\n",
                        stderr="",
                        duration=0.123,
                    )
                return ExecutionOutput(
                    command=command,
                    exit_code=0,
                    stdout="setup ok\n",
                    stderr="",
                    duration=0.05,
                )

        result = run_benchmark(repo_path, sandbox=MockSandbox(repo_path))
    else:
        result = run_benchmark(repo_path)

    execution_status = "SUCCESS" if result.success else "FAILED"
    print(f"Execution: {execution_status}")
    print(f"Exit code: {result.exit_code}")
    print(f"Runs: {result.successful_run_count}/{result.total_runs} successful")
    if result.latency is not None:
        print(f"Latency (mean): {result.latency:.4f}s")
    if result.median_latency is not None:
        print(f"Latency (median): {result.median_latency:.4f}s")
    if result.min_latency is not None and result.max_latency is not None:
        print(f"Latency range: min={result.min_latency:.4f}s, max={result.max_latency:.4f}s")
    if result.raw_latency_samples:
        samples_str = ", ".join(f"{s:.4f}s" for s in result.raw_latency_samples)
        print(f"Samples: [{samples_str}]")
    if result.error:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()
