#!/usr/bin/env python3
"""
Final protobuf generation script that generates files in correct structure without modifying serialized data.
Now includes gRPC code generation.
"""

import subprocess
import sys
import os
from pathlib import Path
import shutil
import platform
import urllib.request
import zipfile


def check_grpc_tools():
    """Check if grpc_tools is installed, install if not."""
    try:
        import grpc_tools
        print("✓ grpc_tools is already installed")
        return True
    except ImportError:
        print("Installing grpc_tools...")
        try:
            subprocess.run(["uv", "pip", "install", "grpcio-tools"], 
                         check=True, capture_output=True, text=True)
            print("✓ grpc_tools installed successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to install grpc_tools: {e}")
            return False


def find_grpc_python_plugin():
    """Find the grpc_python_plugin binary."""
    try:
        # Try to find it in the current Python environment using uv
        result = subprocess.run(["uv", "run", "python", "-m", "grpc_tools.protoc", "--help"], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # The plugin is available through grpc_tools.protoc
            return "grpc_tools.protoc"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    # Try to find it as a standalone binary
    try:
        result = subprocess.run(["grpc_python_plugin", "--help"], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return "grpc_python_plugin"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return None


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
    """Find all .proto files in the given directory, excluding admin files."""
    proto_files = []
    for proto_file in proto_dir.rglob("*.proto"):
        # Skip admin proto files
        if "admin" in str(proto_file):
            continue
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


def generate_init_file(output_dir: Path) -> None:
    """Generate the __init__.py file for cadence/api/v1 with clean imports."""
    v1_dir = output_dir / "api" / "v1"
    init_file = v1_dir / "__init__.py"
    
    # Find all _pb2.py files in the v1 directory
    pb2_files = []
    for file in v1_dir.glob("*_pb2.py"):
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
    with open(init_file, 'w') as f:
        f.write(content)
    
    print(f"  ✓ Generated {init_file} with {len(pb2_files)} modules")


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


def setup_temp_proto_structure(proto_dir: Path, temp_dir: Path) -> None:
    """Create a temporary directory with proto files in the proper structure for cadence.api.v1 imports."""
    print("Setting up temporary proto structure...")
    
    # Find all proto files (excluding admin)
    proto_files = find_proto_files(proto_dir)
    
    if not proto_files:
        print("No .proto files found!")
        return
    
    print(f"Found {len(proto_files)} .proto files (excluding admin):")
    for proto_file in proto_files:
        print(f"  - {proto_file}")
    
    # Copy proto files to temp directory with proper structure
    for proto_file in proto_files:
        # Get relative path from proto directory
        rel_path = proto_file.relative_to(proto_dir)
        
        # Create target path in temp directory
        # We want to transform: uber/cadence/api/v1/file.proto -> cadence/api/v1/file.proto
        parts = list(rel_path.parts)
        
        # Remove 'uber' from the path to get cadence.api.v1 structure
        if parts[0] == 'uber':
            parts = parts[1:]  # Remove 'uber'
        
        target_path = temp_dir / Path(*parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy the proto file and update import statements
        with open(proto_file, 'r') as src_file:
            content = src_file.read()
        
        # Update import statements to remove 'uber/' prefix
        # Replace "uber/cadence/api/v1/" with "cadence/api/v1/"
        updated_content = content.replace('import "uber/cadence/api/v1/', 'import "cadence/api/v1/')
        
        # Write the updated content to the target file
        with open(target_path, 'w') as dst_file:
            dst_file.write(updated_content)
        
        print(f"  ✓ Copied and updated {rel_path} -> {target_path}")


def generate_protobuf_files(temp_proto_dir: Path, output_dir: Path, project_root: Path) -> None:
    """Generate Python protobuf files and gRPC code from .proto files in temp directory."""
    proto_files = list(temp_proto_dir.rglob("*.proto"))
    
    if not proto_files:
        print("No .proto files found in temp directory!")
        return
    
    print(f"Generating Python files from {len(proto_files)} .proto files...")
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Find protoc binary - always use the downloaded protoc 29.1
    protoc_path = find_protoc()
    print(f"Using protoc: {protoc_path}")
    
    # Check for gRPC tools
    if not check_grpc_tools():
        print("Warning: grpc_tools not available, skipping gRPC code generation")
        grpc_plugin = None
    else:
        grpc_plugin = find_grpc_python_plugin()
        if grpc_plugin:
            print(f"✓ Found gRPC plugin: {grpc_plugin}")
        else:
            print("Warning: grpc_python_plugin not found, skipping gRPC code generation")
    
    # Find brew protobuf include directory
    brew_include = find_brew_protobuf_include(project_root)
    
    # Generate Python files for each proto file
    for proto_file in proto_files:
        # Get relative path from temp proto directory
        rel_path = proto_file.relative_to(temp_proto_dir)
        
        # Build command with appropriate include paths
        cmd = [
            protoc_path,
            f"--python_out={output_dir}",
            f"--pyi_out={output_dir}",
            f"--proto_path={temp_proto_dir}",
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
            print(f"  ✓ Generated .py and .pyi files for {rel_path}")
        except subprocess.CalledProcessError as e:
            print(f"  ✗ Failed to generate .py and .pyi files for {rel_path}: {e}")
            print(f"  stderr: {e.stderr}")
            continue
        
        # Add gRPC generation if plugin is available
        if grpc_plugin and grpc_plugin == "grpc_tools.protoc":
            # For grpc_tools.protoc, only generate gRPC files (not _pb2.py)
            grpc_cmd = [
                "uv", "run", "python", "-m", "grpc_tools.protoc",
                f"--grpc_python_out={output_dir}",
                f"--proto_path={temp_proto_dir}",
            ]
            
            # Add brew protobuf include path if available
            if brew_include:
                grpc_cmd.append(f"--proto_path={brew_include}")
            else:
                # Fallback to local include directory
                grpc_cmd.append(f"--proto_path={project_root}/include")
            
            grpc_cmd.append(str(proto_file))
            
            try:
                result = subprocess.run(grpc_cmd, check=True, capture_output=True, text=True)
                print(f"  ✓ Generated gRPC files for {rel_path}")
            except subprocess.CalledProcessError as e:
                print(f"  ✗ Failed to generate gRPC files for {rel_path}: {e}")
                print(f"  stderr: {e.stderr}")
        
        elif grpc_plugin and grpc_plugin != "grpc_tools.protoc":
            # Use standalone protoc with grpc_python_plugin
            grpc_cmd = [
                protoc_path,
                f"--grpc_python_out={output_dir}",
                f"--proto_path={temp_proto_dir}",
            ]
            
            # Add brew protobuf include path if available
            if brew_include:
                grpc_cmd.append(f"--proto_path={brew_include}")
            else:
                # Fallback to local include directory
                grpc_cmd.append(f"--proto_path={project_root}/include")
            
            grpc_cmd.append(str(proto_file))
            
            try:
                result = subprocess.run(grpc_cmd, check=True, capture_output=True, text=True)
                print(f"  ✓ Generated gRPC files for {rel_path}")
            except subprocess.CalledProcessError as e:
                print(f"  ✗ Failed to generate gRPC files for {rel_path}: {e}")
                print(f"  stderr: {e.stderr}")
    
    # Move files from nested structure to correct structure
    print("Moving files to correct structure...")
    nested_cadence_dir = output_dir / "cadence"
    if nested_cadence_dir.exists():
        # Move all contents from cadence/cadence/api/v1/ to cadence/api/v1/
        nested_api_dir = nested_cadence_dir / "api"
        if nested_api_dir.exists():
            target_api_dir = output_dir / "api"
            target_api_dir.mkdir(parents=True, exist_ok=True)
            
            # Move api/v1 directory
            nested_v1_dir = nested_api_dir / "v1"
            target_v1_dir = target_api_dir / "v1"
            
            if nested_v1_dir.exists():
                # Remove target if it exists
                if target_v1_dir.exists():
                    shutil.rmtree(target_v1_dir)
                
                # Move the v1 directory
                shutil.move(str(nested_v1_dir), str(target_v1_dir))
                print(f"  ✓ Moved api/v1 directory to correct location")
            
            # Move api/__init__.py if it exists
            nested_init = nested_api_dir / "__init__.py"
            target_init = target_api_dir / "__init__.py"
            if nested_init.exists():
                shutil.move(str(nested_init), str(target_init))
                print(f"  ✓ Moved api/__init__.py to correct location")
            
            # Remove the nested cadence directory
            shutil.rmtree(nested_cadence_dir)
            print(f"  ✓ Cleaned up nested cadence directory")


def generate_grpc_init_file(output_dir: Path) -> None:
    """Generate the __init__.py file for cadence/api/v1 with gRPC imports."""
    v1_dir = output_dir / "api" / "v1"
    init_file = v1_dir / "__init__.py"
    
    # Find all _pb2.py and _pb2_grpc.py files in the v1 directory
    pb2_files = []
    grpc_files = []
    
    for file in v1_dir.glob("*_pb2.py"):
        module_name = file.stem  # e.g., "common_pb2" -> "common_pb2"
        clean_name = module_name.replace("_pb2", "")  # e.g., "common_pb2" -> "common"
        pb2_files.append((module_name, clean_name))
    
    for file in v1_dir.glob("*_pb2_grpc.py"):
        module_name = file.stem  # e.g., "service_workflow_pb2_grpc" -> "service_workflow_pb2_grpc"
        clean_name = module_name.replace("_pb2_grpc", "_grpc")  # e.g., "service_workflow_pb2_grpc" -> "service_workflow_grpc"
        grpc_files.append((module_name, clean_name))
    
    # Sort for consistent ordering
    pb2_files.sort()
    grpc_files.sort()
    
    # Generate the __init__.py content
    content = "# Auto-generated __init__.py file\n"
    content += "# Import all generated protobuf and gRPC modules\n"
    
    # Add protobuf imports
    for module_name, clean_name in pb2_files:
        content += f"from . import {module_name}\n"
    
    # Add gRPC imports
    for module_name, clean_name in grpc_files:
        content += f"from . import {module_name}\n"
    
    content += "\n# Create cleaner aliases for easier imports\n"
    
    # Add protobuf aliases
    for module_name, clean_name in pb2_files:
        content += f"{clean_name} = {module_name}\n"
    
    # Add gRPC aliases
    for module_name, clean_name in grpc_files:
        content += f"{clean_name} = {module_name}\n"
    
    content += "\n# Only expose clean module names\n"
    content += "__all__ = [\n"
    
    # Add __all__ list
    for module_name, clean_name in pb2_files:
        content += f"    '{clean_name}',\n"
    for module_name, clean_name in grpc_files:
        content += f"    '{clean_name}',\n"
    
    content += "]\n"
    
    # Write the file
    with open(init_file, 'w') as f:
        f.write(content)
    
    print(f"  ✓ Generated {init_file} with {len(pb2_files)} protobuf and {len(grpc_files)} gRPC modules")


def main():
    """Main function."""
    # Get the script directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # Define paths
    proto_dir = project_root / "idls" / "proto"
    output_dir = project_root / "cadence"  # This will be the cadence folder directly
    temp_dir = project_root / ".temp_proto"
    
    print(f"Proto directory: {proto_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Temp directory: {temp_dir}")
    
    # Check if proto directory exists
    if not proto_dir.exists():
        print(f"Error: Proto directory not found: {proto_dir}")
        sys.exit(1)
    
    # Clean up temp directory if it exists
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    
    try:
        # Step 1: Create temp directory and copy proto files in proper structure
        temp_dir.mkdir(exist_ok=True)
        setup_temp_proto_structure(proto_dir, temp_dir)
        
        # Step 2: Generate Python files in the cadence directory
        generate_protobuf_files(temp_dir, output_dir, project_root)
        
        # Step 3: Create __init__.py files for all generated directories
        create_init_files(output_dir)
        generate_grpc_init_file(output_dir)
        
        print(f"\nProtobuf and gRPC generation complete. Files generated in {output_dir}")
        print("Files can now be imported as:")
        print("  - cadence.api.v1.workflow (protobuf messages)")
        print("  - cadence.api.v1.service_workflow_grpc (gRPC services)")
        
    finally:
        # Step 4: Clean up temp directory
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
            print(f"Cleaned up temp directory: {temp_dir}")


if __name__ == "__main__":
    main() 