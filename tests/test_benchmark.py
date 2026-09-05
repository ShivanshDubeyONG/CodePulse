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
    # Mock setup
    mock_setup = ExecutionOutput(
        command="python -c \"print('setup ok')\"",
        exit_code=0,
        stdout="setup ok\n",
        stderr="",
        duration=0.05,
    )
    # Mock benchmark
    mock_bench = ExecutionOutput(
        command="python benchmark.py",
        exit_code=0,
        stdout="Workload finished\nLATENCY=0.045678\n",
        stderr="",
        duration=0.15,
    )
    mock_sandbox.execute.side_effect = [mock_setup, mock_bench]

    result = run_benchmark("demo/demo_repo", sandbox=mock_sandbox)
    assert isinstance(result, BenchmarkResult)
    assert result.success is True
    assert result.exit_code == 0
    assert result.latency == 0.045678
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

    result = run_benchmark("demo/demo_repo", sandbox=mock_sandbox)
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
    mock_sandbox.execute.side_effect = [mock_setup, mock_bench]

    result = run_benchmark("demo/demo_repo", sandbox=mock_sandbox)
    assert result.success is False
    assert result.exit_code == 1
    assert "Benchmark exited with non-zero code" in result.error


@pytest.mark.skipif(not is_docker_available(), reason="Docker daemon is not available on host")
def test_live_docker_execution():
    result = run_benchmark("demo/demo_repo")
    assert result.success is True
    assert result.exit_code == 0
    assert result.latency is not None
    assert result.latency > 0
