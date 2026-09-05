"""Benchmark execution and latency parsing for CodePulse."""

import re
import sys
from pathlib import Path
from typing import Optional, Union
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
    """Structured result of a benchmark execution."""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    latency: Optional[float] = None
    error: Optional[str] = None


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


def run_benchmark(
    repo_path: Union[str, Path],
    image: str = "python:3.11-slim",
    cpu_limit: float = 2.0,
    memory_limit: str = "2GB",
    timeout_seconds: int = 60,
    sandbox: Optional[DockerSandbox] = None,
) -> BenchmarkResult:
    """Execute the repository benchmark inside a Docker sandbox and return structured results."""
    repo = Path(repo_path).resolve()
    if not repo.exists() or not repo.is_dir():
        return BenchmarkResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            duration=0.0,
            error=f"Repository path does not exist or is not a directory: {repo}",
        )

    # 1. Load and validate configuration
    try:
        config = load_config(repo)
    except Exception as exc:
        return BenchmarkResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            duration=0.0,
            error=f"Configuration error: {exc}",
        )

    # 2. Instantiate sandbox
    active_sandbox = sandbox or DockerSandbox(
        repo_path=repo,
        image=image,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        timeout_seconds=timeout_seconds,
    )

    # 3. Execute setup command if configured
    if config.setup and config.setup.command and config.setup.command.strip():
        try:
            setup_out = active_sandbox.execute(config.setup.command.strip())
            if setup_out.exit_code != 0:
                return BenchmarkResult(
                    success=False,
                    exit_code=setup_out.exit_code,
                    stdout=setup_out.stdout,
                    stderr=setup_out.stderr,
                    duration=setup_out.duration,
                    error=f"Setup command failed with exit code {setup_out.exit_code}: {setup_out.stderr.strip()}",
                )
        except SandboxError as exc:
            return BenchmarkResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration=0.0,
                error=f"Sandbox error during setup: {exc}",
            )

    # 4. Execute benchmark command
    try:
        bench_out = active_sandbox.execute(config.benchmark.command.strip())
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

    # 5. Parse latency
    try:
        latency = parse_latency(bench_out.stdout, config.result.pattern)
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
    if result.latency is not None:
        print(f"Latency: {result.latency:.3f}s")
    if result.error:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()
