#!/usr/bin/env python3
"""
Fix missing datetime imports in generated .pyi stub files.
This is a workaround for a bug in grpcio-tools where it generates
type hints using datetime.datetime/datetime.timedelta but doesn't
import the datetime module.
"""

from pathlib import Path


def fix_pyi_file(pyi_file: Path) -> bool:
    """Add missing datetime import to a .pyi file if needed."""
    content = pyi_file.read_text()

    # Check if datetime types are used
    uses_datetime = "datetime.datetime" in content or "datetime.timedelta" in content
    has_datetime_import = "import datetime" in content

    # if use datetime but not import it, add it
    if uses_datetime and not has_datetime_import:
        # Find the right place to insert the import (after other imports)
        lines = content.split("\n")

        # Find the last import line
        last_import_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("from ") or line.startswith("import "):
                last_import_idx = i

        # Insert datetime import after the last import
        lines.insert(last_import_idx + 1, "import datetime")

        # Write back
        pyi_file.write_text("\n".join(lines))
        print(f"  ✓ Fixed {pyi_file.name}")
        return True

    return False


def main():
    """Fix all .pyi files in cadence/api/v1/."""
    project_root = Path(__file__).parent.parent
    pyi_dir = project_root / "cadence" / "api" / "v1"

    if not pyi_dir.exists():
        print(f"Error: {pyi_dir} not found")
        return

    print("Fixing missing datetime imports in .pyi files...")
    fixed_count = 0

    for pyi_file in pyi_dir.glob("*.pyi"):
        if fix_pyi_file(pyi_file):
            fixed_count += 1

    if fixed_count > 0:
        print(f"Fixed {fixed_count} .pyi files")
    else:
        print("No .pyi files needed fixing")


if __name__ == "__main__":
    main()
