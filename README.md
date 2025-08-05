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

### Generate Protobuf Files

Run the generation script:
```bash
python scripts/generate_proto.py
```

This will:
- Download protoc 29.1 binary
- Generate Python files in `cadence/api/v1/`
- Create proper package structure

### Test

Verify the generated files work:
```bash
python cadence/sample/simple_usage_example.py
```

### Usage

```python
from cadence.api.v1 import workflow, common, domain

# Create objects
wf_exec = common.WorkflowExecution()
wf_exec.workflow_id = "my-workflow"

# Use enums
status = workflow.WORKFLOW_EXECUTION_CLOSE_STATUS_COMPLETED
```

## License

Apache 2.0 License, please see [LICENSE](LICENSE) for details.
