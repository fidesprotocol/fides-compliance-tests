#!/usr/bin/env python3
"""
Fides Compliance Test Suite Runner

Official test runner for validating Fides Protocol v0.3 implementations.

Usage:
    python runner.py                    # Run all tests
    python runner.py --report           # Generate compliance report
    python runner.py --test 01          # Run specific test module
    python runner.py --url http://...   # Specify implementation URL

Environment:
    FIDES_IMPL_URL  - Implementation base URL (default: http://localhost:8000)
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


TESTS_DIR = Path(__file__).parent / "tests"

TEST_MODULES = [
    ("01_append_only", "Append-Only Behavior", "No retroactive alteration possible"),
    ("02_canonical_json", "Canonical JSON", "Correct serialization for hashing"),
    ("03_hash_chain", "Hash Chain Integrity", "Chain links all records"),
    ("04_signatures", "Cryptographic Signatures", "Signatures verifiable"),
    ("05_timestamps", "Timestamp Attestation", "External timestamp proofs"),
    ("06_payment_auth", "Payment Authorization", "No payment without valid DR"),
    ("07_payment_serial", "Payment Serialization", "Concurrent payments serialized"),
    ("08_sdr_expiration", "SDR Expiration", "SDR term limits enforced"),
    ("09_revocation", "Revocation Authority", "Revocation rules enforced"),
    ("10_registration_delay", "Registration Delay", "72h maximum enforced"),
    ("11_anchor_interval", "Anchor Interval", "24h maximum enforced"),
]


def run_tests(test_filter: str | None = None, verbose: bool = False) -> dict:
    """Run pytest and return results."""
    cmd = [
        sys.executable, "-m", "pytest",
        str(TESTS_DIR),
        "-v" if verbose else "-q",
        "--tb=short",
        "-x" if not test_filter else "",  # Stop on first failure unless filtering
    ]

    if test_filter:
        cmd.extend(["-k", test_filter])

    # Add JSON output for parsing
    cmd.extend(["--json-report", "--json-report-file=.test_results.json"])

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Parse results
    results = {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
    }

    # Try to parse JSON report if available
    try:
        with open(".test_results.json", "r") as f:
            json_report = json.load(f)
            summary = json_report.get("summary", {})
            results["passed"] = summary.get("passed", 0)
            results["failed"] = summary.get("failed", 0)
            results["skipped"] = summary.get("skipped", 0)
            results["errors"] = summary.get("error", 0)
            results["tests"] = json_report.get("tests", [])
        os.remove(".test_results.json")
    except (FileNotFoundError, json.JSONDecodeError):
        # Parse from stdout if JSON not available
        for line in result.stdout.split("\n"):
            if "passed" in line:
                try:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == "passed":
                            results["passed"] = int(parts[i-1])
                        elif p == "failed":
                            results["failed"] = int(parts[i-1])
                        elif p == "skipped":
                            results["skipped"] = int(parts[i-1])
                except (ValueError, IndexError):
                    pass

    return results


def generate_report(impl_url: str) -> dict:
    """Generate comprehensive compliance report."""
    print("=" * 60)
    print("FIDES COMPLIANCE TEST SUITE v0.3")
    print("=" * 60)
    print(f"\nTarget: {impl_url}")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("-" * 60)

    report = {
        "version": "0.3",
        "implementation_url": impl_url,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tests": [],
        "summary": {
            "total_passed": 0,
            "total_failed": 0,
            "total_skipped": 0,
            "compliance_status": "UNKNOWN",
        }
    }

    all_passed = True

    for module, name, description in TEST_MODULES:
        print(f"\n[{module}] {name}")
        print(f"  {description}")

        results = run_tests(test_filter=module, verbose=False)

        status = "PASS" if results["failed"] == 0 and results["errors"] == 0 else "FAIL"
        if results["passed"] == 0 and results["skipped"] > 0:
            status = "SKIP"

        symbol = {"PASS": "+", "FAIL": "x", "SKIP": "-"}[status]
        print(f"  [{symbol}] {status}: {results['passed']} passed, {results['failed']} failed, {results['skipped']} skipped")

        if status == "FAIL":
            all_passed = False

        report["tests"].append({
            "module": module,
            "name": name,
            "description": description,
            "status": status,
            "passed": results["passed"],
            "failed": results["failed"],
            "skipped": results["skipped"],
        })

        report["summary"]["total_passed"] += results["passed"]
        report["summary"]["total_failed"] += results["failed"]
        report["summary"]["total_skipped"] += results["skipped"]

    # Determine compliance status
    if all_passed:
        report["summary"]["compliance_status"] = "COMPLIANT"
    else:
        report["summary"]["compliance_status"] = "NON-COMPLIANT"

    report["completed_at"] = datetime.now(timezone.utc).isoformat()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total Passed:  {report['summary']['total_passed']}")
    print(f"Total Failed:  {report['summary']['total_failed']}")
    print(f"Total Skipped: {report['summary']['total_skipped']}")
    print("-" * 60)

    if report["summary"]["compliance_status"] == "COMPLIANT":
        print("\n  *** COMPLIANT WITH FIDES v0.3 ***")
    else:
        print("\n  !!! NON-COMPLIANT - See failed tests above !!!")

    print()

    return report


def save_report(report: dict, output_path: str | None = None):
    """Save compliance report to file."""
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"compliance_report_{timestamp}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Report saved to: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Fides Compliance Test Suite Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python runner.py                    Run all tests
  python runner.py --report           Generate compliance report
  python runner.py --test 01          Run test module 01 only
  python runner.py --test signatures  Run tests matching 'signatures'
  python runner.py -v                 Verbose output

Environment Variables:
  FIDES_IMPL_URL    Implementation URL (default: http://localhost:8000)
        """
    )

    parser.add_argument(
        "--url", "-u",
        default=os.environ.get("FIDES_IMPL_URL", "http://localhost:8000"),
        help="Implementation base URL"
    )
    parser.add_argument(
        "--test", "-t",
        help="Run specific test module or filter"
    )
    parser.add_argument(
        "--report", "-r",
        action="store_true",
        help="Generate compliance report"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file for report (default: compliance_report_TIMESTAMP.json)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all test modules"
    )

    args = parser.parse_args()

    # Set environment variable for tests
    os.environ["FIDES_IMPL_URL"] = args.url

    if args.list:
        print("Available test modules:")
        print("-" * 60)
        for module, name, description in TEST_MODULES:
            print(f"  {module}: {name}")
            print(f"           {description}")
        return 0

    if args.report:
        report = generate_report(args.url)
        save_report(report, args.output)
        return 0 if report["summary"]["compliance_status"] == "COMPLIANT" else 1

    # Run tests
    results = run_tests(test_filter=args.test, verbose=args.verbose)

    print(results["stdout"])
    if results["stderr"]:
        print(results["stderr"], file=sys.stderr)

    return results["returncode"]


if __name__ == "__main__":
    sys.exit(main())
