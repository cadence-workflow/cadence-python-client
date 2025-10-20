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
uv venv
uv pip install -e ".[dev]"
```

For detailed setup instructions, development workflow, and contribution guidelines, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing

We'd love your help in making Cadence great! Please review our [contribution guide](CONTRIBUTING.md).

If you'd like to propose a new feature, first join the [CNCF Slack workspace](https://communityinviter.com/apps/cloud-native/cncf) in the **#cadence-users** channel to start a discussion.

## Community

- [GitHub Issues](https://github.com/cadence-workflow/cadence-python-client/issues)
  - Best for reporting bugs and feature requests
- [Stack Overflow](https://stackoverflow.com/questions/tagged/cadence-workflow)
  - Best for Q&A and general discussion
- [Slack](https://communityinviter.com/apps/cloud-native/cncf) - Join **#cadence-users** channel on CNCF Slack
  - Best for contributing/development discussion

## Documentation

Visit [cadenceworkflow.io](https://cadenceworkflow.io) to learn more about Cadence.

- [Documentation](https://cadenceworkflow.io/docs/)
- [Main Cadence Repository](https://github.com/uber/cadence)
- [Cadence Samples](https://github.com/cadence-workflow/cadence-samples)

## License

Apache 2.0 License, please see [LICENSE](LICENSE) for details.
