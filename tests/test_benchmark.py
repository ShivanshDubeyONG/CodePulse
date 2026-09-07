"""Tests for benchmark execution, Docker sandbox, and latency parsing."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock
from codepulse.sandbox import (
    DockerSandbox,
    ExecutionOutput,
    DockerUnavailableError,
    format_memory_limit,
    is_docker_available,
)
from codepulse.benchmark import (
    parse_latency,
    run_benchmark,
    BenchmarkResult,
    RepeatedBenchmarkResult,
)


def test_parse_latency_standard():
    stdout = "App initialized\nRunning benchmark...\nLATENCY=0.123456\nDone."
    latency = parse_latency(stdout)
    assert latency == 0.123456


def test_parse_latency_custom_pattern():
    stdout = "Time taken: 42.10 ms"
    latency = parse_latency(stdout, pattern=r"Time taken:\s*([0-9.]+)\s*ms")
    assert latency == 42.10


def test_parse_latency_empty_stdout():
    with pytest.raises(ValueError, match="empty"):
        parse_latency("")


def test_parse_latency_not_found():
    with pytest.raises(ValueError, match="did not match"):
        parse_latency("No latency output printed here.")


def test_format_memory_limit():
    assert format_memory_limit("2GB") == "2g"
    assert format_memory_limit("512MB") == "512m"
    assert format_memory_limit("1g") == "1g"


def test_docker_command_construction():
    sandbox = DockerSandbox(
        repo_path="demo/demo_repo",
        image="python:3.11-slim",
        cpu_limit=2.0,
        memory_limit="2GB",
    )
    cmd = sandbox.build_docker_cmd("python benchmark.py")

    assert cmd[0] == "docker"
    assert cmd[1] == "run"
    assert "--rm" in cmd
    assert "--cpus=2.0" in cmd
    assert "--memory=2g" in cmd
    assert "--memory-swap=2g" in cmd
    assert "-w" in cmd
    assert "/workspace" in cmd
    assert "python:3.11-slim" in cmd
    assert "python benchmark.py" in cmd


def test_docker_unavailable_raises_error(monkeypatch):
    sandbox = DockerSandbox(repo_path="demo/demo_repo")
    monkeypatch.setattr("codepulse.sandbox.is_docker_available", lambda: False)

    with pytest.raises(DockerUnavailableError, match="Docker is not available"):
        sandbox.execute("echo test")


def test_benchmark_successful_execution_mocked():
    mock_sandbox = MagicMock()
    mock_setup = ExecutionOutput(
        command="python -c \"print('setup ok')\"",
        exit_code=0,
        stdout="setup ok\n",
        stderr="",
        duration=0.05,
    )
    mock_bench = ExecutionOutput(
        command="python benchmark.py",
        exit_code=0,
        stdout="Workload finished\nLATENCY=0.045678\n",
        stderr="",
        duration=0.15,
    )
    mock_sandbox.execute.side_effect = lambda cmd: mock_setup if "print" in cmd else mock_bench

    result = run_benchmark("demo/demo_repo", sandbox=mock_sandbox, runs=1)
    assert isinstance(result, BenchmarkResult)
    assert isinstance(result, RepeatedBenchmarkResult)
    assert result.success is True
    assert result.exit_code == 0
    assert result.latency == 0.045678
    assert result.successful_run_count == 1
    assert result.failed_run_count == 0
    assert result.error is None


def test_benchmark_setup_failure_mocked():
    mock_sandbox = MagicMock()
    mock_setup = ExecutionOutput(
        command="python -c \"print('setup ok')\"",
        exit_code=1,
        stdout="",
        stderr="Setup failed: missing package\n",
        duration=0.05,
    )
    mock_sandbox.execute.return_value = mock_setup

    result = run_benchmark("demo/demo_repo", sandbox=mock_sandbox, runs=1)
    assert result.success is False
    assert result.exit_code == 1
    assert "Setup command failed" in result.error
    assert result.latency is None


def test_benchmark_exit_code_failure_mocked():
    mock_sandbox = MagicMock()
    mock_setup = ExecutionOutput(
        command="python -c \"print('setup ok')\"",
        exit_code=0,
        stdout="setup ok\n",
        stderr="",
        duration=0.05,
    )
    mock_bench = ExecutionOutput(
        command="python benchmark.py",
        exit_code=1,
        stdout="",
        stderr="RuntimeError: division by zero\n",
        duration=0.10,
    )
    mock_sandbox.execute.side_effect = lambda cmd: mock_setup if "print" in cmd else mock_bench

    result = run_benchmark("demo/demo_repo", sandbox=mock_sandbox, runs=1)
    assert result.success is False
    assert result.exit_code == 1
    assert "All 1 benchmark runs failed" in result.error


def test_repeated_benchmark_multiple_successful_runs():
    mock_sandbox = MagicMock()
    mock_setup = ExecutionOutput(
        command="python -c \"print('setup ok')\"",
        exit_code=0,
        stdout="setup ok\n",
        stderr="",
        duration=0.05,
    )
    bench_outputs = [
        ExecutionOutput(command="python benchmark.py", exit_code=0, stdout="LATENCY=0.10\n", stderr="", duration=0.10),
        ExecutionOutput(command="python benchmark.py", exit_code=0, stdout="LATENCY=0.20\n", stderr="", duration=0.20),
        ExecutionOutput(command="python benchmark.py", exit_code=0, stdout="LATENCY=0.30\n", stderr="", duration=0.30),
    ]
    iterator = iter([mock_setup] + bench_outputs)
    mock_sandbox.execute.side_effect = lambda cmd: next(iterator)

    result = run_benchmark("demo/demo_repo", sandbox=mock_sandbox, runs=3)
    assert result.success is True
    assert result.total_runs == 3
    assert result.successful_run_count == 3
    assert result.successful_runs == 3
    assert result.failed_run_count == 0
    assert result.failed_runs == 0
    assert result.raw_latency_samples == [0.10, 0.20, 0.30]
    assert result.raw_latencies == [0.10, 0.20, 0.30]
    assert result.min_latency == 0.10
    assert result.max_latency == 0.30
    assert result.mean_latency == 0.20
    assert result.median_latency == 0.20
    assert result.latency == 0.20
    assert result.error is None
    assert len(result.runs) == 3


def test_repeated_benchmark_correct_mean_median_min_max():
    mock_sandbox = MagicMock()
    mock_setup = ExecutionOutput(command="setup", exit_code=0, stdout="ok\n", stderr="", duration=0.01)
    # 4 samples: [0.10, 0.20, 0.40, 0.50]
    bench_outputs = [
        ExecutionOutput(command="bench", exit_code=0, stdout="LATENCY=0.10\n", stderr="", duration=0.1),
        ExecutionOutput(command="bench", exit_code=0, stdout="LATENCY=0.20\n", stderr="", duration=0.1),
        ExecutionOutput(command="bench", exit_code=0, stdout="LATENCY=0.40\n", stderr="", duration=0.1),
        ExecutionOutput(command="bench", exit_code=0, stdout="LATENCY=0.50\n", stderr="", duration=0.1),
    ]
    iterator = iter([mock_setup] + bench_outputs)
    mock_sandbox.execute.side_effect = lambda cmd: next(iterator)

    result = run_benchmark("demo/demo_repo", sandbox=mock_sandbox, runs=4)
    assert result.min_latency == 0.10
    assert result.max_latency == 0.50
    assert result.mean_latency == 0.30
    assert result.median_latency == 0.30


def test_repeated_benchmark_mixed_success_failure():
    mock_sandbox = MagicMock()
    mock_setup = ExecutionOutput(command="setup", exit_code=0, stdout="ok\n", stderr="", duration=0.01)
    bench_outputs = [
        ExecutionOutput(command="bench", exit_code=0, stdout="LATENCY=0.10\n", stderr="", duration=0.1),
        ExecutionOutput(command="bench", exit_code=1, stdout="", stderr="Error in run 2\n", duration=0.1),
        ExecutionOutput(command="bench", exit_code=0, stdout="LATENCY=0.30\n", stderr="", duration=0.1),
        ExecutionOutput(command="bench", exit_code=1, stdout="", stderr="Error in run 4\n", duration=0.1),
    ]
    iterator = iter([mock_setup] + bench_outputs)
    mock_sandbox.execute.side_effect = lambda cmd: next(iterator)

    result = run_benchmark("demo/demo_repo", sandbox=mock_sandbox, runs=4)
    assert result.success is True
    assert result.total_runs == 4
    assert result.successful_run_count == 2
    assert result.failed_run_count == 2
    assert result.raw_latency_samples == [0.10, 0.30]
    # Statistics calculated strictly from successful runs
    assert result.min_latency == 0.10
    assert result.max_latency == 0.30
    assert result.mean_latency == 0.20
    assert result.median_latency == 0.20
    # Failure recorded and not discarded
    assert "2 of 4 benchmark runs failed" in result.error
    assert len(result.runs) == 4
    assert result.runs[1].success is False
    assert result.runs[1].exit_code == 1
    assert "Error in run 2" in result.runs[1].stderr


def test_repeated_benchmark_all_runs_failing():
    mock_sandbox = MagicMock()
    mock_setup = ExecutionOutput(command="setup", exit_code=0, stdout="ok\n", stderr="", duration=0.01)
    bench_outputs = [
        ExecutionOutput(command="bench", exit_code=1, stdout="", stderr="Crash 1\n", duration=0.1),
        ExecutionOutput(command="bench", exit_code=1, stdout="", stderr="Crash 2\n", duration=0.1),
    ]
    iterator = iter([mock_setup] + bench_outputs)
    mock_sandbox.execute.side_effect = lambda cmd: next(iterator)

    result = run_benchmark("demo/demo_repo", sandbox=mock_sandbox, runs=2)
    assert result.success is False
    assert result.total_runs == 2
    assert result.successful_run_count == 0
    assert result.failed_run_count == 2
    assert result.raw_latency_samples == []
    assert result.min_latency is None
    assert result.max_latency is None
    assert result.mean_latency is None
    assert result.median_latency is None
    assert result.latency is None
    assert "All 2 benchmark runs failed" in result.error


def test_repeated_benchmark_configured_run_count():
    mock_sandbox = MagicMock()
    mock_setup = ExecutionOutput(command="setup", exit_code=0, stdout="ok\n", stderr="", duration=0.01)
    call_count = {"count": 0}

    def fake_execute(cmd):
        if "print" in cmd:
            return mock_setup
        call_count["count"] += 1
        return ExecutionOutput(command=cmd, exit_code=0, stdout="LATENCY=0.05\n", stderr="", duration=0.05)

    mock_sandbox.execute.side_effect = fake_execute

    # In demo_repo codepulse.yaml, runs is configured to 5
    result = run_benchmark("demo/demo_repo", sandbox=mock_sandbox)
    assert result.total_runs == 5
    assert call_count["count"] == 5

    # Passing explicit runs overrides the configuration
    call_count["count"] = 0
    result_override = run_benchmark("demo/demo_repo", sandbox=mock_sandbox, runs=2)
    assert result_override.total_runs == 2
    assert call_count["count"] == 2


@pytest.mark.skipif(not is_docker_available(), reason="Docker daemon is not available on host")
def test_live_docker_execution():
    result = run_benchmark("demo/demo_repo", runs=2)
    assert result.success is True
    assert result.exit_code == 0
    assert result.total_runs == 2
    assert result.successful_run_count == 2
    assert len(result.raw_latency_samples) == 2
    assert result.min_latency is not None and result.min_latency > 0
    assert result.max_latency is not None and result.max_latency >= result.min_latency
    assert result.mean_latency is not None and result.mean_latency > 0
    assert result.median_latency is not None and result.median_latency > 0

