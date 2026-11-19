"""Select generic plugin sources while excluding runtime and personal data."""
from pathlib import Path

DIRECTORIES = ("agents", "skills", "hooks", "scripts", "ui", "mcp", "bin", "dashboard", "contracts")
EXCLUDED = {"__pycache__", "node_modules", ".next", ".git", "coverage", "tests", "test-results", "playwright-report", "users", "events", "runtime", ".env", ".env.local"}


def distributed_files(root: Path):
    for directory in DIRECTORIES:
        for path in sorted((root / directory).rglob("*")):
            relative = path.relative_to(root)
            if any(part in EXCLUDED for part in relative.parts) or path.name == ".gitkeep" or path.name.endswith((".log", ".tsbuildinfo")) or path.name.startswith(".env"):
                continue
            if path.is_symlink():
                raise ValueError("Distributed plugin sources cannot contain symbolic links.")
            if path.is_file():
                yield path
