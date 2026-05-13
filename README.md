# Python framework for Cadence
[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Fcadence-workflow%2Fcadence-python-client.svg?type=shield)](https://app.fossa.com/projects/git%2Bgithub.com%2Fcadence-workflow%2Fcadence-python-client?ref=badge_shield)


[Cadence](https://github.com/uber/cadence) is a distributed, scalable, durable, and highly available orchestration engine we developed at Uber Engineering to execute asynchronous long-running business logic in a scalable and resilient way.

If you'd like to propose a new feature, first join the [CNCF Slack workspace](https://communityinviter.com/apps/cloud-native/cncf) in the **#cadence-users** channel to start a discussion.

`cadence-python-client` is the Python framework for authoring workflows and activities.

## Disclaimer
**This SDK is currently an early work-in-progress (WIP) and is NOT ready for production use.**

- This project is still in active development
- APIs and interfaces are subject to change without notice

## Installation

Install from [PyPI](https://pypi.org/project/cadence-python-client/):

```bash
pip install cadence-python-client
```

Or with `uv`:

```bash
uv add cadence-python-client
```

The core package supports Python `>=3.11,<3.14`.

Clone the repository if you want to develop locally:

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
   uv sync --all-extras
   ```

   Or if you prefer traditional pip:
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -e ".[dev]"
   ```

### Generate Protobuf and gRPC Files

Run the generation script only if you change files under `idls/proto/`:

```bash
# Recommended
make generate

# Or run the script directly
uv run python scripts/generate_proto.py
```

This will:
- Generate Python protobuf files in `cadence/api/v1/`
- Generate gRPC service files in `cadence/api/v1/`
- Refresh the package imports for the generated modules

### Test

Run the main checks:

```bash
make lint
make type-check
make test
```

Run integration tests with Docker:

```bash
make integration-test
```

You can also verify the generated files manually:

```bash
uv run python cadence/sample/simple_usage_example.py
uv run python cadence/sample/grpc_usage_example.py
```

### Development Commands

The current repository workflow is centered on `make` targets:

```bash
make install
make generate
make lint
make type-check
make test
make integration-test
make pr
```

## License

Apache 2.0 License, please see [LICENSE](LICENSE) for details.


[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Fcadence-workflow%2Fcadence-python-client.svg?type=large)](https://app.fossa.com/projects/git%2Bgithub.com%2Fcadence-workflow%2Fcadence-python-client?ref=badge_large)