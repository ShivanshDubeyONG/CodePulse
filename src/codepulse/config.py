"""Configuration parser and schema for codepulse.yaml."""

import re
from pathlib import Path
from typing import Optional, Union, Dict, Any
import yaml
from pydantic import BaseModel, Field, ValidationError


class ConfigError(Exception):
    """Raised when codepulse.yaml is missing, malformed, or fails validation."""
    pass


class SetupConfig(BaseModel):
    """Setup command executed inside the sandbox before benchmarking."""
    command: Optional[str] = Field(default=None, description="Setup command string")


class BenchmarkConfig(BaseModel):
    """Benchmark command executed inside the sandbox."""
    command: str = Field(..., description="Benchmark command string")
    runs: int = Field(default=1, ge=1, description="Number of times to execute the benchmark")


class ResultConfig(BaseModel):
    """Specification for extracting benchmark metrics from execution output."""
    type: str = Field(default="stdout", description="Source of measurement (e.g. stdout)")
    pattern: str = Field(
        default=r"LATENCY=(?P<latency>[0-9.]+)",
        description="Regex pattern extracting latency value",
    )


class CodePulseConfig(BaseModel):
    """Root configuration contract for CodePulse repositories."""
    setup: Optional[SetupConfig] = Field(default=None)
    benchmark: BenchmarkConfig
    result: ResultConfig = Field(default_factory=ResultConfig)
    runs: Optional[int] = Field(default=None, ge=1, description="Top-level override for benchmark runs")


def parse_config_str(content: str) -> CodePulseConfig:
    """Parse and validate YAML configuration string into CodePulseConfig."""
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML syntax: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("codepulse.yaml content must be a dictionary/mapping")

    try:
        config = CodePulseConfig.model_validate(data)
    except ValidationError as exc:
        errors = [f"{err['loc']}: {err['msg']}" for err in exc.errors()]
        raise ConfigError(f"Configuration validation error: {'; '.join(errors)}") from exc

    if not config.benchmark.command.strip():
        raise ConfigError("benchmark.command cannot be empty")

    if config.runs is not None:
        if not ("benchmark" in data and isinstance(data["benchmark"], dict) and "runs" in data["benchmark"]):
            config.benchmark.runs = config.runs

    try:
        re.compile(config.result.pattern)
    except re.error as exc:
        raise ConfigError(f"Invalid regex pattern in result.pattern: {exc}") from exc

    return config


def load_config(repo_path_or_file: Union[str, Path]) -> CodePulseConfig:
    """Load and validate codepulse.yaml from a repository directory or file path."""
    path = Path(repo_path_or_file)
    if path.is_dir():
        path = path / "codepulse.yaml"

    if not path.is_file():
        raise ConfigError(f"Configuration file not found: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise ConfigError(f"Failed to read configuration file '{path}': {exc}") from exc

    return parse_config_str(content)
