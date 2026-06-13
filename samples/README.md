# Cadence Python Client — Samples

Runnable examples for the Cadence Python SDK.

**Prerequisites for all samples:**

1. A running Cadence server. The easiest way:
   ```bash
   cd tests/integration_tests
   docker compose up -d
   ```
2. Install dependencies:
   ```bash
   uv sync --all-extras
   ```

---

## Schedules

> **Server prerequisite:** the target domain must have `worker.enableScheduler: true` in the server's dynamic config.

### schedule_sample

Full schedule lifecycle in one script: **create → describe → pause → unpause → backfill → update → list → delete**.

**1. Start a worker** (keep running in one terminal):
```bash
uv run python samples/schedule_sample/schedule_sample.py worker
```

**2. Run the demo** (in a second terminal):
```bash
uv run python samples/schedule_sample/schedule_sample.py demo
```

Both subcommands accept `--target` (default `localhost:7833`) and `--domain` (default `samples-domain`).
