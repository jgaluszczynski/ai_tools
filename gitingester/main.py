#!/usr/bin/env python3
"""GitIngest processor CLI entry point"""
import argparse
from datetime import datetime
from pathlib import Path

from gitingest import ingest  # add via pip -> pip install gitingest

DEFAULT_PATTERNS_TO_EXCLUDE = {"__pycache__*", "*venv*"}
DISABLED_CHARS = "$[]#,"


def process_gitignore(input_dir: Path) -> set[str]:
    """
    Parse and convert .gitignore patterns to exclusion set,
    excluding lines with $, [, ], or , characters.
    """
    exclude_patterns = set()
    gitignore_path = input_dir / ".gitignore"

    if gitignore_path.exists():
        with gitignore_path.open() as f:
            for line in f:
                if line := line.strip():
                    # Skip lines containing $, [, ], or ,
                    if any(char in line for char in DISABLED_CHARS):
                        continue
                    # Convert .gitignore patterns to match gitingest format
                    pattern = line.strip("/")
                    if "/" in pattern:
                        pattern = f"**/{pattern}"
                    exclude_patterns.add(pattern)
        return exclude_patterns
    else:
        return DEFAULT_PATTERNS_TO_EXCLUDE


def process_directory(
    input_dir: Path,
    output_path: Path,
    debug: bool | None,
    include_patterns: set[str] | None,
    exclude_patterns: set[str] | None,
    max_file_size: int = 20 * 1024,
):
    """Process directory with combined .gitignore and CLI exclusions"""
    if not output_path.parent.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
    if not exclude_patterns:
        exclude_patterns = set()

    gitignore_excludes = process_gitignore(input_dir)
    exclude_patterns = gitignore_excludes | exclude_patterns

    if debug:
        print(f"\ninclude patterns:\n{include_patterns};\n\nexclude patterns:\n{exclude_patterns}\n")

    _summary, _tree, _result = ingest(
        str(input_dir),
        max_file_size=max_file_size,
        output=str(output_path),
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    )

    print(f"Summary\n===================\n{_summary}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Process directories with GitIngest"
    )
    parser.add_argument(
        "--dir",
        type=Path,
        required=True,
        help="Directory to process",
    )
    parser.add_argument(
        "--fs",
        type=int,
        default=20 * 1024,
        help="Maximum file size in bytes (default: 20KB)",
    )
    parser.add_argument(
        "--incl",
        type=str,
        help="Include patterns (;-separated)",
    )
    parser.add_argument(
        "--excl",
        type=str,
        help="Exclude patterns (;-separated)",
    )
    parser.add_argument(
        "--suffix",
        type=str,
        help="custom suffix for the output filename",
    )
    parser.add_argument(
        "--debug",
        type=str,
        help="log params",
    )

    args = parser.parse_args()

    # Create output path
    timestamp = datetime.now().strftime("%Y-%m-%d@%H-%M")
    suffix = f"-{args.suffix}" if args.suffix else ""
    output_name = f"{args.dir.name}@{timestamp}{suffix}.txt"
    output_path = Path("_processed") / output_name

    process_directory(
        args.dir,
        output_path,
        debug=args.debug,
        max_file_size=args.fs,
        include_patterns=set(args.incl.split(";")) if args.incl else None,
        exclude_patterns=set(args.excl.split(";")) if args.excl else None,
    )
