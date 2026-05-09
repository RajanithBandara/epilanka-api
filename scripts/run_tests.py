#!/usr/bin/env python
"""
Visual test runner with rich output and reporting options.
Usage:
    python scripts/run_tests.py [--full] [--html] [--coverage]
"""

import subprocess
import sys

def run_command(cmd, description):
    """Run a command and print formatted output."""
    print(f"\n{'=' * 70}")
    print(f"📋 {description}")
    print(f"{'=' * 70}\n")
    result = subprocess.run(cmd, shell=True)
    return result.returncode == 0

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run tests with visual feedback")
    parser.add_argument("--full", action="store_true", help="Run all tests including slow ones")
    parser.add_argument("--html", action="store_true", help="Generate HTML report")
    parser.add_argument("--coverage", action="store_true", help="Include coverage report")
    parser.add_argument("--watch", action="store_true", help="Watch for changes and re-run tests")
    args = parser.parse_args()

    base_cmd = "python -m pytest"
    
    # Add coverage if requested
    if args.coverage:
        base_cmd += " --cov=controllers --cov=routes --cov=utils --cov=models --cov-report=html"
    
    # Add HTML report if requested
    if args.html:
        base_cmd += " --html=reports/pytest_report.html --self-contained-html"
    
    # Exclude slow tests unless --full
    if not args.full:
        base_cmd += " -m 'not slow'"

    # Run tests
    success = run_command(base_cmd, "🧪 Running FastAPI Endpoint Tests")
    
    if not success:
        print("\n❌ Tests failed!")
        sys.exit(1)
    
    if args.html:
        print("\n✅ HTML report generated at: reports/pytest_report.html")
    
    if args.coverage:
        print("\n✅ Coverage report generated at: htmlcov/index.html")
    
    print("\n✅ All tests passed!")

if __name__ == "__main__":
    main()

