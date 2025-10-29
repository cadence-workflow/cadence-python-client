#!/usr/bin/env python3
"""
Final protobuf generation script that generates files in correct structure without modifying serialized data.
Now includes gRPC code generation.
"""

import subprocess
import sys
from pathlib import Path
import shutil
import runpy


def get_project_root() -> Path:
    try:
        return Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], text=True
            ).strip()
        )
    except Exception as e:
        raise RuntimeError("Error: Could not determine project root from git:", e)


def generate_init_file(output_dir: Path) -> None:
    """Generate the __init__.py file for cadence/api/v1 with clean imports."""
    v1_dir = output_dir / "cadence" / "api" / "v1"
    init_file = v1_dir / "__init__.py"
    init_file.touch()

    # Find all _pb2.py files in the v1 directory
    pb2_files = []
    for file in v1_dir.glob("*_pb2*.py"):
        module_name = file.stem  # e.g., "common_pb2" -> "common_pb2"
        clean_name = module_name.replace("_pb2", "")  # e.g., "common_pb2" -> "common"
        pb2_files.append((module_name, clean_name))

    # Sort for consistent ordering
    pb2_files.sort()

    # Generate the __init__.py content
    content = "# Auto-generated __init__.py file\n"
    content += "# Import all generated protobuf modules\n"

    # Add imports
    for module_name, clean_name in pb2_files:
        content += f"from . import {module_name}\n"

    content += "\n# Create cleaner aliases for easier imports\n"

    # Add aliases
    for module_name, clean_name in pb2_files:
        content += f"{clean_name} = {module_name}\n"

    content += "\n# Only expose clean module names (no _pb2)\n"
    content += "__all__ = [\n"

    # Add __all__ list
    for module_name, clean_name in pb2_files:
        content += f"    '{clean_name}',\n"

    content += "]\n"

    # Write the file
    with open(init_file, "w") as f:
        f.write(content)

    print(f"  ✓ Generated {init_file} with {len(pb2_files)} modules")


def setup_temp_proto_structure(proto_dir: Path, temp_dir: Path) -> None:
    """Create a temporary directory with proto files in the proper structure for cadence.api.v1 imports."""
    print("Setting up temporary proto structure...")

    proto_file_dir = proto_dir / "uber" / "cadence" / "api" / "v1"
    output_dir = temp_dir / "cadence" / "api" / "v1"

    # Create the cadence/api/v1 directory structure in temp_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy all proto files from proto_dir to temp_dir
    for proto_file in proto_file_dir.glob("*.proto"):
        # Copy the proto file and update import statements
        with open(proto_file, "r") as src_file:
            content = src_file.read()

        # Update import statements to remove 'uber/' prefix
        # Replace "uber/cadence/api/v1/" with "cadence/api/v1/"
        updated_content = content.replace(
            'import "uber/cadence/api/v1/', 'import "cadence/api/v1/'
        )

        # Write the updated content to the target file
        with open(output_dir / proto_file.name, "w") as dst_file:
            dst_file.write(updated_content)

        print(f"  ✓ Copied and updated {proto_file.name}")


def delete_temp_dir(temp_dir: Path):
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
        print(f"Deleted temp directory: {temp_dir}")


def generate_protobuf_files(temp_dir: Path, gen_dir: Path) -> None:
    # Find all .proto files in the cadence/api/v1 directory
    proto_files = list((temp_dir / "cadence/api/v1").glob("*.proto"))

    if not proto_files:
        print("No .proto files found in temp_dir/cadence/api/v1/")
        delete_temp_dir(temp_dir)
        sys.exit(1)

    # Convert Path objects to strings for sys.argv
    proto_file_paths = [str(f) for f in proto_files]

    # Save original argv and set up new argv for grpc_tools.protoc
    original_argv = sys.argv
    sys.argv = [
        "grpc_tools.protoc",
        "--proto_path",
        str(temp_dir),
        "--python_out",
        str(gen_dir),
        "--pyi_out",
        str(gen_dir),
        "--grpc_python_out",
        str(gen_dir),
    ] + proto_file_paths

    try:
        runpy.run_module("grpc_tools.protoc", run_name="__main__", alter_sys=True)
        print(
            f"Successfully generated protobuf files using runpy for {len(proto_files)} files"
        )
    except SystemExit as e:
        if e.code == 0:
            print(
                f"Successfully generated protobuf files using runpy for {len(proto_files)} files"
            )
        else:
            print("Error running grpc_tools.protoc via runpy {}", e)
            raise e
    finally:
        # Restore original argv
        sys.argv = original_argv


def main():
    project_root = get_project_root()

    proto_dir = project_root / "idls" / "proto"
    temp_dir = project_root / ".temp_proto"
    gen_dir = project_root

    setup_temp_proto_structure(proto_dir, temp_dir)

    generate_protobuf_files(temp_dir, gen_dir)
    generate_init_file(gen_dir)
    delete_temp_dir(temp_dir)


if __name__ == "__main__":
    main()
