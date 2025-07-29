#!/usr/bin/env python3
"""
Final protobuf generation script that generates files in correct structure without modifying serialized data.
"""

import subprocess
import sys
import os
from pathlib import Path
import shutil
import platform
import urllib.request
import zipfile


def download_protoc_29_1(project_root: Path) -> str:
    """Download protoc 29.1 from GitHub releases to .bin directory like the cadence-idl Makefile."""
    bin_dir = project_root / ".bin"
    bin_dir.mkdir(exist_ok=True)
    
    # Determine OS and architecture
    os_name = platform.system().lower()
    arch = platform.machine().lower()
    
    # Normalize architecture names for protobuf releases (like the Makefile)
    if arch in ['arm64', 'aarch64']:
        arch = 'aarch_64'
    elif arch == 'x86_64':
        arch = 'x86_64'
    
    # Normalize OS names
    if os_name == 'darwin':
        os_name = 'osx'
    elif os_name == 'linux':
        os_name = 'linux'
    elif os_name == 'windows':
        os_name = 'windows'
    
    protoc_version = "29.1"
    protoc_bin = bin_dir / f"protoc-{protoc_version}"
    
    # Check if already downloaded
    if protoc_bin.exists():
        try:
            result = subprocess.run([str(protoc_bin), "--version"], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and "29.1" in result.stdout:
                print(f"Using existing .bin protoc 29.1: {result.stdout.strip()}")
                return str(protoc_bin)
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            pass
    
    # Download URL (same as Makefile)
    url = f"https://github.com/protocolbuffers/protobuf/releases/download/v{protoc_version}/protoc-{protoc_version}-{os_name}-{arch}.zip"
    zip_path = bin_dir / "protoc.zip"
    unzip_dir = bin_dir / f"protoc-{protoc_version}-zip"
    
    print(f"Downloading protoc {protoc_version} to .bin directory from {url}")
    
    try:
        # Download
        urllib.request.urlretrieve(url, zip_path)
        
        # Clean up any existing unzip directory
        if unzip_dir.exists():
            shutil.rmtree(unzip_dir)
        
        # Unzip
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(unzip_dir)
        
        # Copy protoc binary to standard location
        source_protoc = unzip_dir / "bin" / "protoc"
        if source_protoc.exists():
            shutil.copy2(source_protoc, protoc_bin)
            protoc_bin.chmod(0o755)  # Make executable
            
            # Clean up
            shutil.rmtree(unzip_dir)
            zip_path.unlink()
            
            print(f"Successfully downloaded and installed protoc {protoc_version} to .bin directory")
            return str(protoc_bin)
        else:
            raise FileNotFoundError(f"protoc binary not found in {source_protoc}")
            
    except Exception as e:
        print(f"Failed to download protoc 29.1: {e}")
        # Clean up on failure
        if zip_path.exists():
            zip_path.unlink()
        if unzip_dir.exists():
            shutil.rmtree(unzip_dir)
        raise


def find_protoc() -> str:
    """Find the protoc binary, preferring .bin/protoc-29.1, then download it if not available."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # First, check for protoc-29.1 in .bin directory (preferred)
    bin_protoc = project_root / ".bin" / "protoc-29.1"
    if bin_protoc.exists():
        try:
            result = subprocess.run([str(bin_protoc), "--version"], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and "29.1" in result.stdout:
                print(f"Using .bin protoc-29.1: {result.stdout.strip()}")
                return str(bin_protoc)
        except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError) as e:
            print(f"Warning: .bin protoc-29.1 failed: {e}")
    
    # Download protoc 29.1 to .bin directory if not available
    try:
        protoc_29_1_path = download_protoc_29_1(project_root)
        return protoc_29_1_path
    except Exception as e:
        print(f"Error: Could not download protoc 29.1: {e}")
        raise RuntimeError(
            f"Failed to download protoc 29.1 to .bin directory: {e}\n"
            "Please check your internet connection and try again."
        )


def find_proto_files(proto_dir: Path) -> list[Path]:
    """Find all .proto files in the given directory."""
    proto_files = []
    for proto_file in proto_dir.rglob("*.proto"):
        proto_files.append(proto_file)
    return sorted(proto_files)


def create_init_files(output_dir: Path) -> None:
    """Create __init__.py files for all subdirectories."""
    for subdir in output_dir.rglob("*"):
        if subdir.is_dir():
            init_file = subdir / "__init__.py"
            if not init_file.exists():
                init_file.touch()
                print(f"  ✓ Created {init_file}")


def find_brew_protobuf_include(project_root: Path) -> str:
    """Find the protobuf include directory, preferring downloaded protoc 29.1, then brew installations."""
    # First, check if we have downloaded protoc 29.1 and use its include directory
    protoc_29_1_bin = project_root / "bin" / "protoc-29.1"
    if protoc_29_1_bin.exists():
        # The downloaded protoc includes the well-known types in the zip
        # We'll use the local include directory as fallback
        local_include = project_root / "include"
        if local_include.exists():
            print(f"Using local include directory: {local_include}")
            return str(local_include)
    
    try:
        # Try to find main brew protobuf installation (version 29.3)
        result = subprocess.run(["brew", "--prefix", "protobuf"], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            brew_prefix = result.stdout.strip()
            include_path = f"{brew_prefix}/include"
            if os.path.exists(include_path):
                print(f"Using main protobuf include: {include_path}")
                return include_path
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    # Check protobuf@29 second (version 29.4)
    protobuf_29_include = "/opt/homebrew/opt/protobuf@29/include"
    if os.path.exists(protobuf_29_include):
        print(f"Using protobuf@29 include: {protobuf_29_include}")
        return protobuf_29_include
    
    # Fallback to common brew location
    common_paths = [
        "/opt/homebrew/include",
        "/usr/local/include",
        "/opt/homebrew/Cellar/protobuf/*/include"
    ]
    
    for path_pattern in common_paths:
        if "*" in path_pattern:
            # Handle wildcard pattern
            import glob
            matches = glob.glob(path_pattern)
            if matches:
                # Use the latest version
                latest = sorted(matches)[-1]
                if os.path.exists(latest):
                    print(f"Using brew protobuf include: {latest}")
                    return latest
        else:
            if os.path.exists(path_pattern):
                print(f"Using brew protobuf include: {path_pattern}")
                return path_pattern
    
    return None


def generate_protobuf_files(proto_dir: Path, output_dir: Path, project_root: Path) -> None:
    """Generate Python protobuf files from .proto files."""
    proto_files = find_proto_files(proto_dir)
    
    if not proto_files:
        print("No .proto files found!")
        return
    
    print(f"Found {len(proto_files)} .proto files:")
    for proto_file in proto_files:
        print(f"  - {proto_file}")
    
    # Create temporary directory for initial generation
    temp_dir = output_dir.parent / ".temp_gen"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(exist_ok=True)
    
    # Find protoc binary
    protoc_path = find_protoc()
    
    # Find brew protobuf include directory
    brew_include = find_brew_protobuf_include(project_root)
    
    # Generate Python files for each proto file in temp directory
    print("Generating Python files in temporary directory...")
    
    for proto_file in proto_files:
        # Get relative path from proto directory
        rel_path = proto_file.relative_to(proto_dir)
        
        # Build command with appropriate include paths
        cmd = [
            protoc_path,
            f"--python_out={temp_dir}",
            f"--pyi_out={temp_dir}",
            f"--proto_path={proto_dir}",
        ]
        
        # Add brew protobuf include path if available
        if brew_include:
            cmd.append(f"--proto_path={brew_include}")
        else:
            # Fallback to local include directory
            cmd.append(f"--proto_path={project_root}/include")
        
        cmd.append(str(proto_file))
        
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"  ✓ Generated files for {rel_path}")
        except subprocess.CalledProcessError as e:
            print(f"  ✗ Failed to generate files for {rel_path}: {e}")
            print(f"  stderr: {e.stderr}")
    
    # Move files from temp directory to correct locations
    print("Moving files to correct locations...")
    for proto_file in proto_files:
        rel_path = proto_file.relative_to(proto_dir)
        parts = rel_path.parts

        # Keep the full path including 'uber' and 'cadence' parts
        # uber/cadence/admin/v1/queue.proto -> uber/cadence/admin/v1/queue.proto
        target_parts = parts

        # Get the filename without extension
        filename = target_parts[-1].replace('.proto', '_pb2.py')
        pyi_filename = target_parts[-1].replace('.proto', '_pb2.pyi')

        # Source files in temp directory (with original structure)
        source_rel_path = Path(*parts)
        source_file = temp_dir / source_rel_path.parent / filename
        source_pyi_file = temp_dir / source_rel_path.parent / pyi_filename

        # Target directory and files - keep the full uber.cadence structure
        target_dir = output_dir
        for part in target_parts[:-1]:  # All parts except the filename
            target_dir = target_dir / part

        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / filename
        target_pyi_file = target_dir / pyi_filename

        # Move .py file
        if source_file.exists():
            shutil.move(str(source_file), str(target_file))
            print(f"  ✓ Moved {filename} to {target_file}")
        else:
            print(f"  ✗ Source file not found: {source_file}")
        
        # Move .pyi file
        if source_pyi_file.exists():
            shutil.move(str(source_pyi_file), str(target_pyi_file))
            print(f"  ✓ Moved {pyi_filename} to {target_pyi_file}")
        else:
            print(f"  ✗ Source pyi file not found: {source_pyi_file}")

    # Clean up temp directory
    shutil.rmtree(temp_dir)

    # Create __init__.py files for all generated directories
    create_init_files(output_dir)





def main():
    """Main function."""
    # Get the script directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # Define paths
    proto_dir = project_root / "idls" / "proto"
    output_dir = project_root / "shared"
    
    print(f"Proto directory: {proto_dir}")
    print(f"Output directory: {output_dir}")
    
    # Check if proto directory exists
    if not proto_dir.exists():
        print(f"Error: Proto directory not found: {proto_dir}")
        sys.exit(1)
    
    # Generate protobuf files
    generate_protobuf_files(proto_dir, output_dir, project_root)
    
    print(f"\nProtobuf generation complete. Files generated in {output_dir}")
    print("Note: Files are generated in correct structure with original serialized data.")


if __name__ == "__main__":
    main() 