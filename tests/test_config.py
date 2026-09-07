"""Tests for CodePulse configuration parsing and validation."""

import pytest
from pathlib import Path
from codepulse.config import (
    load_config,
    parse_config_str,
    ConfigError,
    CodePulseConfig,
)


def test_valid_configuration():
    yaml_text = """
    setup:
      command: "pip install -r requirements.txt"
    benchmark:
      command: "python benchmark.py"
    result:
      type: "stdout"
      pattern: "LATENCY=(?P<latency>[0-9.]+)"
    """
    config = parse_config_str(yaml_text)
    assert isinstance(config, CodePulseConfig)
    assert config.setup is not None
    assert config.setup.command == "pip install -r requirements.txt"
    assert config.benchmark.command == "python benchmark.py"
    assert config.result.pattern == "LATENCY=(?P<latency>[0-9.]+)"


def test_valid_minimal_configuration():
    yaml_text = """
    benchmark:
      command: "python benchmark.py"
    """
    config = parse_config_str(yaml_text)
    assert config.setup is None
    assert config.benchmark.command == "python benchmark.py"
    assert config.result.type == "stdout"
    assert "LATENCY" in config.result.pattern


def test_missing_benchmark_command():
    yaml_text = """
    setup:
      command: "echo test"
    """
    with pytest.raises(ConfigError, match="benchmark"):
        parse_config_str(yaml_text)


def test_empty_benchmark_command():
    yaml_text = """
    benchmark:
      command: "   "
    """
    with pytest.raises(ConfigError, match="cannot be empty"):
        parse_config_str(yaml_text)


def test_invalid_yaml_syntax():
    with pytest.raises(ConfigError, match="Invalid YAML"):
        parse_config_str("benchmark: [unclosed")


def test_invalid_regex_pattern():
    yaml_text = """
    benchmark:
      command: "python benchmark.py"
    result:
      pattern: "LATENCY=(?P<latency>[0-9+"
    """
    with pytest.raises(ConfigError, match="Invalid regex"):
        parse_config_str(yaml_text)


def test_load_config_from_demo_repo():
    config = load_config("demo/demo_repo")
    assert config.benchmark.command == "python benchmark.py"
    assert config.benchmark.runs == 5
    assert config.result.type == "stdout"


def test_nonexistent_config_file():
    with pytest.raises(ConfigError, match="not found"):
        load_config("nonexistent_directory")


def test_config_runs_default():
    yaml_text = """
    benchmark:
      command: "python benchmark.py"
    """
    config = parse_config_str(yaml_text)
    assert config.benchmark.runs == 1
    assert config.runs is None


def test_config_runs_configured_under_benchmark():
    yaml_text = """
    benchmark:
      command: "python benchmark.py"
      runs: 7
    """
    config = parse_config_str(yaml_text)
    assert config.benchmark.runs == 7


def test_config_runs_configured_top_level():
    yaml_text = """
    benchmark:
      command: "python benchmark.py"
    runs: 9
    """
    config = parse_config_str(yaml_text)
    assert config.benchmark.runs == 9
    assert config.runs == 9


def test_config_runs_invalid_zero_or_negative():
    yaml_text = """
    benchmark:
      command: "python benchmark.py"
      runs: 0
    """
    with pytest.raises(ConfigError):
        parse_config_str(yaml_text)

