"""Docker sandbox execution layer for CodePulse."""

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Union
from pydantic import BaseModel, Field


class SandboxError(Exception):
    """Base exception for sandbox execution failures."""
    pass


class DockerUnavailableError(SandboxError):
    """Raised when Docker CLI or daemon is not accessible."""
    pass


class SandboxTimeoutError(SandboxError):
    """Raised when execution inside sandbox exceeds timeout."""
    pass


class ExecutionOutput(BaseModel):
    """Output captured from a command executed in the sandbox."""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float


def is_docker_available() -> bool:
    """Check if Docker CLI is installed and the Docker daemon is responding."""
    if not shutil.which("docker"):
        return False
    try:
        res = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return res.returncode == 0
    except Exception:
        return False


def format_memory_limit(mem: str) -> str:
    """Normalize memory limits like '2GB', '512MB', '1g' to Docker flag format ('2g', '512m')."""
    cleaned = mem.strip().lower()
    if cleaned.endswith("gb"):
        return cleaned[:-2] + "g"
    if cleaned.endswith("mb"):
        return cleaned[:-2] + "m"
    return cleaned


class DockerSandbox:
    """Executes commands inside disposable, resource-constrained Docker containers."""

    def __init__(
        self,
        repo_path: Union[str, Path],
        image: str = "python:3.11-slim",
        cpu_limit: float = 2.0,
        memory_limit: str = "2GB",
        timeout_seconds: int = 60,
        workdir: str = "/workspace",
    ):
        self.repo_path = Path(repo_path).resolve()
        self.image = image
        self.cpu_limit = cpu_limit
        self.memory_limit = memory_limit
        self.timeout_seconds = timeout_seconds
        self.workdir = workdir

    def build_docker_cmd(self, command: str) -> List[str]:
        """Construct the 'docker run' CLI command list."""
        mem_flag = format_memory_limit(self.memory_limit)
        host_path = str(self.repo_path)

        return [
            "docker",
            "run",
            "--rm",
            f"--cpus={self.cpu_limit}",
            f"--memory={mem_flag}",
            f"--memory-swap={mem_flag}",
            "-v",
            f"{host_path}:{self.workdir}",
            "-w",
            self.workdir,
            self.image,
            "sh",
            "-c",
            command,
        ]

    def execute(self, command: str) -> ExecutionOutput:
        """Run a command inside the container and capture execution metrics.
        
        The repository code runs inside Docker and NOT on the host.
        """
        if not is_docker_available():
            raise DockerUnavailableError(
                "Docker is not available. Please ensure Docker is installed and the daemon is running."
            )

        cmd = self.build_docker_cmd(command)
        start_time = time.perf_counter()

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
            duration = time.perf_counter() - start_time

            return ExecutionOutput(
                command=command,
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration=round(duration, 4),
            )

        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - start_time
            raise SandboxTimeoutError(
                f"Command timed out after {self.timeout_seconds} seconds: '{command}'"
            ) from exc

        except Exception as exc:
            if isinstance(exc, SandboxError):
                raise
            raise SandboxError(f"Unexpected error executing Docker command: {exc}") from exc
