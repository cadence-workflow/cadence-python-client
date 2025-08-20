#!/usr/bin/env python3
"""
Development script for Cadence Python client.
Replaces Makefile functionality with Python-native commands.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"Running: {description}")
    try:
        subprocess.run(cmd, shell=True, check=True)
        print(f"✓ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {description} failed: {e}")
        return False


def install():
    """Install the package in development mode."""
    return run_command("uv pip install -e .", "Installing package in development mode")


def install_dev():
    """Install the package with development dependencies."""
    return run_command("uv pip install -e '.[dev]'", "Installing package with dev dependencies")


def test():
    """Run tests."""
    return run_command("uv run pytest", "Running tests")


def test_cov():
    """Run tests with coverage."""
    return run_command("uv run pytest --cov=cadence --cov-report=html --cov-report=term-missing", "Running tests with coverage")


def lint():
    """Run linting tools."""
    commands = [
        ("uv run black --check --diff .", "Checking code formatting with black"),
        ("uv run isort --check-only --diff .", "Checking import sorting with isort"),
        ("uv run flake8 .", "Running flake8 linting"),
        ("uv run mypy .", "Running mypy type checking"),
    ]

    success = True
    for cmd, desc in commands:
        if not run_command(cmd, desc):
            success = False

    return success


def format():
    """Format code."""
    commands = [
        ("uv run black .", "Formatting code with black"),
        ("uv run isort .", "Sorting imports with isort"),
    ]

    success = True
    for cmd, desc in commands:
        if not run_command(cmd, desc):
            success = False

    return success


def clean():
    """Clean build artifacts."""
    dirs_to_remove = [
        "build/",
        "dist/",
        "*.egg-info/",
        ".pytest_cache/",
        ".coverage",
        "htmlcov/",
        ".mypy_cache/",
    ]

    print("Cleaning build artifacts...")

    # Remove directories
    for dir_pattern in dirs_to_remove:
        run_command(f"rm -rf {dir_pattern}", f"Removing {dir_pattern}")

    # Remove Python cache files
    run_command("find . -type d -name __pycache__ -delete", "Removing __pycache__ directories")
    run_command("find . -type f -name '*.pyc' -delete", "Removing .pyc files")

    print("✓ Clean completed")


def build():
    """Build the package."""
    return run_command("uv run python -m build", "Building package")


def protobuf():
    """Generate protobuf files."""
    script_path = Path(__file__).parent / "generate_proto.py"
    return run_command(f"uv run python {script_path}", "Generating protobuf files")


def docs():
    """Build documentation."""
    return run_command("uv run sphinx-build -b html docs/source docs/build/html", "Building documentation")


def check():
    """Run all checks (lint, test)."""
    print("Running all checks...")
    if lint() and test():
        print("✓ All checks passed")
        return True
    else:
        print("✗ Some checks failed")
        return False


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Development script for Cadence Python client")
    parser.add_argument("command", choices=[
        "install", "install-dev", "test", "test-cov", "lint", "format",
        "clean", "build", "protobuf", "docs", "check"
    ], help="Command to run")

    args = parser.parse_args()

    # Map commands to functions
    commands = {
        "install": install,
        "install-dev": install_dev,
        "test": test,
        "test-cov": test_cov,
        "lint": lint,
        "format": format,
        "clean": clean,
        "build": build,
        "protobuf": protobuf,
        "docs": docs,
        "check": check,
    }

    # Run the command
    success = commands[args.command]()

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
