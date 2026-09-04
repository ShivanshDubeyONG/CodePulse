# CodePulse

> **Experimental Codebase Intelligence**

CodePulse measures runtime performance across controlled execution environments, detects statistically meaningful regressions, and traces those regressions through Git history to pinpoint the first commit where performance degraded.

## Architecture

- **Core Engine:** Statistical testing (Welch's t-test, Mann-Whitney U, Cohen's d), multi-run outlier mitigation, automated Git bisection.
- **Execution Sandboxes:** Controlled Docker containers (CPU limits, RAM limits, Python 3.11/3.13) with local process isolation fallback.
- **Attribution:** AST function/import diffing, dependency manifest inspection, unified Git diff analysis.
- **Interface:** FastAPI REST & Server-Sent Events (SSE) backend + developer-infrastructure dashboard.
