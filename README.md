# Python framework for Cadence

[Cadence](https://github.com/uber/cadence) is a distributed, scalable, durable, and highly available orchestration engine we developed at Uber Engineering to execute asynchronous long-running business logic in a scalable and resilient way.

`cadence-python-client` is the Python framework for authoring workflows and activities.

## Disclaimer
**This SDK is currently an early work-in-progress (WIP) and is NOT ready for production use.**

- This project is still in active development
- It has not been published to any package repository (PyPI, etc.)
- APIs and interfaces are subject to change without notice

## Installation

```bash
git clone https://github.com/cadence-workflow/cadence-python-client.git
cd cadence-python-client
```

## Development

### Setup

1. **Install protobuf (required):**
   ```bash
   # macOS
   brew install protobuf@29

   # Linux/Other
   # Install protobuf 29.x via your package manager
   ```

2. **Install uv (recommended):**
   ```bash
   # macOS
   brew install uv

   # Linux/Other
   curl -LsSf https://astral.sh/uv/install.sh | sh
   source $HOME/.local/bin/env  # Add to your shell profile for persistence
   ```

3. **Create virtual environment and install dependencies:**
   ```bash
   uv venv
   uv pip install -e ".[dev]"
   ```

   Or if you prefer traditional pip:
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -e ".[dev]"
   ```

### Generate Protobuf and gRPC Files

Run the generation script:
```bash
# Using uv (recommended)
uv sync --extra dev
uv run python scripts/generate_proto.py

# Or using traditional Python
python scripts/generate_proto.py
```

This will:
- Download protoc 29.1 binary
- Install grpcio-tools if needed
- Generate Python protobuf files in `cadence/api/v1/`
- Generate gRPC service files in `cadence/api/v1/`
- Create proper package structure with both protobuf and gRPC imports

### Test

Verify the generated files work:
```bash
# Using uv (recommended)
uv run python cadence/sample/simple_usage_example.py
uv run python cadence/sample/grpc_usage_example.py

# Or using traditional Python
python cadence/sample/simple_usage_example.py
python test_grpc_with_examples.py
```

### Development Script

The project includes a development script that provides convenient commands for common tasks:

```bash
# Generate protobuf files
uv run python scripts/dev.py protobuf

# Run tests
uv run python scripts/dev.py test

# Run tests with coverage
uv run python scripts/dev.py test-cov

# Run linting
uv run python scripts/dev.py lint

# Format code
uv run python scripts/dev.py format

# Install in development mode
uv run python scripts/dev.py install

# Install with dev dependencies
uv run python scripts/dev.py install-dev

# Build package
uv run python scripts/dev.py build

# Clean build artifacts
uv run python scripts/dev.py clean

# Run all checks (lint + test)
uv run python scripts/dev.py check
```

## Community & Contributing

### Get Involved

We'd love your help in making Cadence great! Here's how you can get involved:

- **Join the conversation**: Connect with the Cadence community on [CNCF Slack](https://slack.cncf.io/) in the `#cadence` channel
- **Contributing Guide**: Please see our [Contributing Guide](https://github.com/cadence-workflow/cadence/blob/master/CONTRIBUTING.md) for details on:
  - How to contribute
  - Development workflow
  - Code review process
  - Community guidelines

### Resources

- [Cadence Documentation](https://cadenceworkflow.io/docs/)
- [Main Cadence Repository](https://github.com/uber/cadence)
- [Cadence Samples](https://github.com/cadence-workflow/cadence-samples)

### Reporting Issues

If you find a bug or have a feature request, please [open an issue](https://github.com/cadence-workflow/cadence-python-client/issues/new) on GitHub.

## License

Apache 2.0 License, please see [LICENSE](LICENSE) for details.
