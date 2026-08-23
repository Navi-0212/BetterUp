import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

# Optional python-dotenv support for convenience
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from src.audit_log import AuditLog
from src.claude_handler import ClaudeHandler
from src.connectors import (
    FakeExpoITConnector,
    FakeLumosConnector,
    FakeOktaConnector,
    FakeTrackerConnector,
    FakeWorkdayConnector,
)
from src.models import ChangeEvent
from src.state_store import StateStore
from src.sync_engine import process_event


def main(argv: Sequence[str] | None = None) -> int:
    """Parses --event, --data-dir, --dry-run. Loads and validates the
    event JSON into a ChangeEvent, runs process_event, prints a summary,
    returns a process exit code (0 = no failures, 1 = any FAILED or
    needs_human_review entries)."""
    parser = argparse.ArgumentParser(description="BetterUp Sync Engine CLI")
    parser.add_argument(
        "--event",
        required=True,
        type=str,
        help="Path to a ChangeEvent JSON file",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        type=str,
        help="Path to state data directory (default: ./data)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run normalization/validation without writing state or calling connectors",
    )

    args = parser.parse_args(argv)

    event_path = Path(args.event)
    if not event_path.exists():
        print(f"Error: Event file not found at {args.event}", file=sys.stderr)
        return 1

    try:
        with open(event_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        event = ChangeEvent.model_validate(raw_data)
    except Exception as e:
        print(f"Error loading event JSON: {e}", file=sys.stderr)
        return 1

    store = StateStore(data_dir=Path(args.data_dir))
    audit_log = AuditLog(log_path=Path(args.data_dir) / "audit_log.jsonl")

    connectors = {
        "workday": FakeWorkdayConnector(),
        "okta": FakeOktaConnector(),
        "lumos": FakeLumosConnector(),
        "expoit": FakeExpoITConnector(),
        "tracker": FakeTrackerConnector(),
    }

    claude_handler = ClaudeHandler()

    print("=" * 60)
    print(f"Processing Event: {event.event_id} ({event.event_type})")
    print(f"Employee ID: {event.employee_id} | Source: {event.source_system}")
    if args.dry_run:
        print("MODE: DRY RUN (No mutations will be persisted)")
    print("=" * 60)

    result = process_event(
        event=event,
        store=store,
        connectors=connectors,
        claude_handler=claude_handler,
        dry_run=args.dry_run,
        audit_log=audit_log,
    )

    print("\n--- Execution Summary ---")
    print(f"Fields Propagated: {result.fields_propagated}")
    print(f"Fields Rejected:   {result.fields_rejected}")
    print(f"Systems Written:   {result.systems_written}")
    print(f"Systems Failed:    {result.systems_failed}")

    if result.conflict_resolution:
        print(f"Conflict Decision: {result.conflict_resolution.decision} (confidence: {result.conflict_resolution.confidence})")
        print(f"Reasoning:         {result.conflict_resolution.reasoning}")

    if result.needs_human_review:
        print("\n[!] STATUS: NEEDS_HUMAN_REVIEW (Flagged for human triage)")
        return 1

    if result.systems_failed:
        print(f"\n[!] STATUS: FAILED ({len(result.systems_failed)} systems failed writes)")
        return 1

    print("\n[+] STATUS: SUCCESS (All valid fields propagated cleanly)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
