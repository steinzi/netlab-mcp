# netlab-mcp

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](pyproject.toml)
[![CI](https://github.com/steinzi/netlab-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/steinzi/netlab-mcp/actions/workflows/ci.yml)
[![engine: netlab 26.06](https://img.shields.io/badge/engine-netlab%2026.06-green.svg)](https://github.com/ipspace/netlab)

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

> [!WARNING]
> **Lab ≠ production.** Every config-bearing tool response embeds the full disclaimer from
> `netlab_mcp.models.DISCLAIMER`. Configs are validated only in an isolated, synthetic netlab +
> containerlab lab on free images. *"Validated in lab" ≠ "safe in your network"* — review IP/AS/naming
> and interactions with your existing config before applying to real gear. See [SECURITY.md](SECURITY.md).

## Scope (MVP)

- Free containerlab images only: `srlinux`, `frr`, `cumulus`, `vyos`, `linux` (`ceos` behind an explicit
  EULA env flag). Licensed NOSes (nxos/iosxr/sros/junos/…) come later behind a self-hosted runner.
- First proven loop: **eBGP across srlinux + frr**.

## Tools

| Tool | Mode | Disclaimer | Purpose |
|---|---|---|---|
| `generate_topology` | offline | — | intent + platforms → netlab topology YAML (validated by parse) |
| `render_config` | offline | ✅ | topology → real per-device config + clab.yml |
| `query_compatibility` | offline | — | netlab declared support, overlaid with observed lab verdicts |
| `get_known_good` | offline | ✅ | return a previously lab-passed topology + config |
| `list_examples` | offline | — | index netlab's integration test topologies |
| `report_failure` | offline | — | record a negative result into the matrix |
| `host_check` | offline | — | doctor: lab readiness, versions, loaded images, validation plugins |
| `validate_in_lab` | **lab** | ✅ | deploy + `netlab validate` + record verdict |

`Mode`: *offline* needs no docker; *lab* requires docker + containerlab. `Disclaimer`: ✅ responses embed
the lab≠production disclaimer.

## Install — offline (no docker)

The engine (`netlab` binary + `netsim`) installs from PyPI as `networklab`; you do not need to vendor it.

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e '.[dev]'          # pulls networklab (the `netlab` binary) from PyPI

# Only `list_examples` needs netlab's SOURCE tree (tests/integration); it is gitignored.
git clone --depth 1 https://github.com/ipspace/netlab netlab

pytest -m "not docker"              # offline + contract suite, no docker needed
netlab-mcp                          # run the MCP server over stdio
```

## Install — lab (docker + containerlab)

The lab path (`validate_in_lab`) has host prerequisites that `pip` does **not** install. On a dedicated
Linux lab host:

| # | Prerequisite | Why | How |
|---|---|---|---|
| 1 | **containerlab ≥ 0.75.0** | netlab 26.06's container provider requires it | [containerlab install docs](https://containerlab.dev/install/) |
| 2 | **Ansible in the *same* venv** as netlab | netlab pushes device config via Ansible, calling bare `ansible-galaxy`/`ansible-playbook` from `PATH` | `uv pip install 'ansible<=11.10' paramiko netmiko ansible-pylibssh ncclient netaddr` (or `netlab install ansible`) |
| 3 | **Per-device Ansible collections** | each NOS driver needs its collection | e.g. `ansible-galaxy collection install nokia.srlinux` (srlinux); `arista.eos` (ceos) |
| 4 | **Scoped passwordless sudo for containerlab** | netlab runs `sudo -E containerlab deploy` non-interactively | see block below |

> **PATH trap:** because netlab invokes bare binary names, the server must run with the venv **activated**
> (or `.venv/bin` on `PATH`), or netlab won't find `ansible-playbook` / `netlab`.

Passwordless sudo — create `/etc/sudoers.d/netlab-clab` (mode `0440`, validate with `visudo -cf`):

```sudoers
<user> ALL=(root) NOPASSWD: SETENV: /usr/bin/containerlab
```

- The `SETENV:` tag is **mandatory** — netlab passes `-E`; without it you get
  `sorry, you are not allowed to preserve the environment`.
- **Do NOT** use `NOPASSWD: ALL`.
- **Security implication:** containerlab can bind-mount host paths and run privileged containers, so this
  entry is effectively passwordless root for `<user>`. Use it only on a dedicated/disposable lab host.
  See [SECURITY.md](SECURITY.md).

Verify the host is lab-ready: `docker info` and `containerlab version` (≥ 0.75.0) succeed. If they don't,
`validate_in_lab` degrades cleanly to verdict `unavailable` (it is not an error) and the offline tools
keep working.

## Quickstart — the eBGP srlinux + frr loop

Canonical topology: [`tests/fixtures/mvp_bgp.yml`](tests/fixtures/mvp_bgp.yml) — srlinux DUT (AS 65000) ↔
frr peer (AS 65100), with a `validate.session` test that checks the BGP neighbor reaches `Established`.

Driving the tools the way an MCP client would (see [`scripts/smoke_offline.py`](scripts/smoke_offline.py)):

1. `generate_topology("ebgp peering", ["srlinux", "frr"])` → netlab topology YAML.
2. `render_config(topology_yaml)` → real per-node config (srlinux JSON-RPC, frr vtysh) + `clab.yml`.
3. `validate_in_lab(topology_yaml, ["srlinux", "frr"], module="bgp")` → deploy + `netlab validate`;
   verdict `pass` is recorded as known-good (with cached artifacts).
4. `get_known_good("bgp", "srlinux")` → the lab-passed topology + config for reuse.

## Security model

- **Free-image allow-list**, enforced on netlab's *resolved* node devices (not the caller's `platforms`
  claim) and **fails closed** when a device can't be resolved — licensed NOSes are rejected.
- **`ceos`** is gated behind the explicit `NETLAB_MCP_ACCEPT_CEOS_EULA` env flag.
- **External `tools:`** (edgeshark, nso, …) are rejected, with `netlab up --no-tools` as a backstop.
- A **platforms/topology mismatch** is rejected (no spoofing the declared device set).
- Every config-bearing response embeds the **lab≠production disclaimer**.

Full threat model — including what the guardrails explicitly do *not* protect against — is in
[SECURITY.md](SECURITY.md).

## Configuration (env vars)

| Variable | Effect |
|---|---|
| `NETLAB_MCP_NETLAB_BIN` | path to the `netlab` executable (default: same venv, then `PATH`) |
| `NETLAB_MCP_STORE` | store dir for the matrix db + artifacts (default: `./store`) |
| `NETLAB_MCP_WORKDIR` | base dir for per-request temp workdirs (default: `./.work`) |
| `NETLAB_MCP_ACCEPT_CEOS_EULA` | set truthy to allow the EULA-gated `ceos` image |
| `NETLAB_MCP_PLATFORMS` | comma-separated extra device names to allow past the free set |
| `NETLAB_MCP_ALLOW_INSTALLED` | set truthy to allow any device backed by a locally loaded docker image |
| `NETLAB_MCP_TRANSPORT` | `stdio` (default) or `http` (streamable HTTP on `/mcp`) |
| `NETLAB_MCP_HOST` / `NETLAB_MCP_PORT` | HTTP bind address (default `127.0.0.1:8000`) |
| `NETLAB_MCP_TOKEN` / `NETLAB_MCP_TOKEN_FILE` | enable static bearer auth on the HTTP transport |

### HTTP transport

```bash
NETLAB_MCP_TRANSPORT=http NETLAB_MCP_TOKEN_FILE=/etc/netlab-mcp/token netlab-mcp
```

serves MCP on `http://127.0.0.1:8000/mcp` (`Authorization: Bearer <token>`) plus an
**unauthenticated** `GET /health` liveness probe (cheap, non-sensitive — safe to expose to
uptime checks). A non-loopback `NETLAB_MCP_HOST` is refused unless a token is configured:
`validate_in_lab` reaches docker/sudo on this machine, so the token is effectively
root-equivalent — treat it accordingly and prefer `NETLAB_MCP_TOKEN_FILE` (mode 0600) over
the bare env var. Client config:

```json
{
  "mcpServers": {
    "netlab": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

Systemd unit sketch:

```ini
[Service]
Environment=NETLAB_MCP_TRANSPORT=http
Environment=NETLAB_MCP_TOKEN_FILE=/etc/netlab-mcp/token
ExecStart=/opt/netlab-mcp/.venv/bin/netlab-mcp
User=netlab
```

## Architecture

LLM / MCP client → FastMCP server (allow-list + disclaimer guardrails) → offline engine (`netlab create`
/ `initial -o` / `show module-support`) or lab engine (`netlab up` → containerlab → `netlab validate`) →
sqlite matrix store. See [`docs/netlab-mcp-architecture.excalidraw`](docs/netlab-mcp-architecture.excalidraw)
(open at [excalidraw.com](https://excalidraw.com) → *File ▸ Open*; regenerate with `python scripts/gen_diagram.py`).

## Layout

```
src/netlab_mcp/
  server.py            FastMCP app + tool registrations
  config.py            netlab binary discovery, platform allow-list, paths
  models.py            disclaimer + shared constants
  engine/              runner, transform, render, compat, probes, lab, topo, topogen
  store/               sqlite matrix + yaml mirror + results.yaml harvest
store/                 runtime state (matrix.db gitignored, matrix.yaml committed)
tests/                 offline (CI-safe), contract, lab (docker-gated)
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The PR gate is `pytest -m "not docker"`; lab tests are
docker-gated. By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[Apache-2.0](LICENSE). The wrapped `ipspace/netlab` engine is separately licensed (MIT) and is **not**
vendored or redistributed by this project — it is installed as a dependency.

## Acknowledgements

Built on [`ipspace/netlab`](https://github.com/ipspace/netlab) and
[containerlab](https://containerlab.dev). Disclaimer: this is an independent project, not affiliated with
or endorsed by either.
