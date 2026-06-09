# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Unreleased

First public alpha. **Lab ≠ production** — see [SECURITY.md](SECURITY.md).

### Added
- MCP server (FastMCP, stdio) wrapping the `ipspace/netlab` engine.
- Offline tools (no docker): `generate_topology`, `render_config`, `query_compatibility`,
  `get_known_good`, `list_examples`, `report_failure`.
- Lab tool (docker + containerlab): `validate_in_lab` — deploy + `netlab validate` + record verdict into
  a version-scoped sqlite compatibility matrix with a committed YAML mirror.
- First proven loop: lab-validated eBGP across **srlinux + frr**.
- Security guardrails: free-image allow-list enforced on netlab-*resolved* node devices (fail-closed),
  platforms/topology mismatch rejection, external-`tools:` rejection with `netlab up --no-tools` backstop,
  `ceos` EULA gate, and a lab≠production disclaimer on every config-bearing response.
- Validation integrity: generated topologies anchor `validate:` tests on a BGP-validation-plugin-capable
  node; a fully-skipped validation is demoted from `pass` to `no_tests` so it never caches as known-good.
- Apache-2.0 license, packaging metadata, GitHub Actions CI (offline suite on Python 3.10–3.12), and
  community-health docs.

[0.1.0]: https://github.com/steinzi/netlab-mcp/releases/tag/v0.1.0
