# netlab-mcp

An MCP server that **wraps [`ipspace/netlab`](https://github.com/ipspace/netlab) as an engine** to give LLMs
access to *validated, lab-tested* network device configurations — instead of hallucinated ones.

## Why

Getting working network configs out of a raw LLM is unreliable: vendor-syntax drift, no validation,
invented data-model fields, no interop guarantees. netlab already solves the hard part — it owns the
data-model transform (AS / RD-RT / VNI / neighbor computation), the Jinja2 render, the containerlab
provider, and a `netlab validate` test system. This server does **not** re-serve raw `.j2` templates or
rebuild that pipeline. It exposes netlab's *outputs* to an LLM and records what actually passes in a lab.

## What it does

- **Offline (fast, no docker):** translate intent → netlab topology, render real per-device config,
  query declared module/platform support.
- **Lab (needs docker + containerlab):** deploy to containerlab, run `netlab validate`, record the
  pass/fail verdict into a version-scoped compatibility matrix.

> ⚠️ **Lab ≠ production.** Every config-bearing response carries a disclaimer. Configs are validated in an
> isolated synthetic lab on free images — verify addressing, naming, and interactions with existing config
> before touching real gear.

## Scope (MVP)

- Free containerlab images only: `srlinux`, `frr`, `cumulus`, `vyos`, `linux` (`ceos` behind an explicit
  EULA env flag). Licensed NOSes (nxos/iosxr/sros/junos/…) come later behind a self-hosted runner.
- First proven loop: **eBGP across srlinux + frr**.

## Tools

| Tool | Mode | Purpose |
|---|---|---|
| `generate_topology` | offline | intent + platforms → netlab topology YAML (validated by parse) |
| `render_config` | offline | topology → real per-device config + clab.yml |
| `query_compatibility` | offline | netlab declared support, overlaid with observed lab verdicts |
| `get_known_good` | offline | return a previously lab-passed topology + config |
| `list_examples` | offline | index netlab's integration test topologies |
| `report_failure` | offline | record a negative result into the matrix |
| `validate_in_lab` | **lab** | deploy + `netlab validate` + record verdict |

## Layout

```
src/netlab_mcp/
  server.py            FastMCP app + tool registrations
  config.py            netlab binary discovery, platform allow-list, paths
  models.py            disclaimer + shared constants
  engine/              runner, transform, render, compat, probes, lab
  store/               sqlite matrix + yaml mirror + results.yaml harvest
store/                 runtime state (matrix.db gitignored, matrix.yaml committed)
tests/                 offline (CI-safe), contract, lab (docker-gated)
```

## Dev

```bash
git clone --depth 1 https://github.com/ipspace/netlab netlab   # engine (gitignored, not committed)
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ./netlab -e '.[dev]'   # netlab vendored editable during MVP
pytest -m "not docker"                    # offline + contract suite, no docker needed
```

Run the server: `netlab-mcp` (stdio).
