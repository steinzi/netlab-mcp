# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| `0.1.x` | ✅ (alpha) |

The engine is pinned to `networklab>=26.06,<27`. This is lab/research software intended to be run by a
trusted local operator driving an MCP client over stdio. It is **not** a multi-tenant or internet-facing
service and has no authentication on its transport.

## Threat model

- **Lab-only posture.** Designed for a dedicated, disposable Linux lab host — not production or shared
  infrastructure. The mandatory disclaimer (`netlab_mcp.models.DISCLAIMER`) is attached to every
  config-bearing response: *a `pass` verdict means "netlab's validation plugins passed in a synthetic
  lab," not "safe in your network."*
- **Free-image constraint.** Only the free containerlab images in `FREE_PLATFORMS`
  (srlinux/frr/cumulus/vyos/linux), plus `ceos` behind the explicit `NETLAB_MCP_ACCEPT_CEOS_EULA` flag,
  are permitted. Rationale: no licensed-NOS image entitlements, and a smaller blast radius.
- **Passwordless sudo (primary risk).** The lab path requires a scoped sudoers entry so netlab can run
  `sudo -E containerlab`. containerlab can bind-mount host paths and launch privileged containers, so
  that entry is **effectively passwordless root** for the running user. Mitigations: use a
  dedicated/ephemeral host; use the scoped entry only
  (`<user> ALL=(root) NOPASSWD: SETENV: /usr/bin/containerlab`); never `NOPASSWD: ALL`.
- **Untrusted topology input.** `validate_in_lab` accepts arbitrary caller/LLM-supplied topology YAML and
  feeds it to real netlab + docker.

## What the guardrails protect against

- **Allow-list on resolved devices.** The platform allow-list is enforced on netlab's *resolved* node
  devices (via `transform.resolved_node_devices`), not the caller's `platforms` metadata — so a forbidden
  NOS cannot be smuggled through per-node `device:`, groups, or dotted-key (`defaults.device`) defaults.
  Enforcement **fails closed** when devices can't be resolved or the device set is empty.
- **Mismatch rejection.** A `platforms` argument that disagrees with the resolved topology devices is
  rejected — no spoofing the declared set.
- **External-tools rejection.** Topologies declaring `tools:` (edgeshark, nso, …) — which spawn arbitrary
  Docker containers outside the image allow-list — are rejected, with `netlab up --no-tools` as a
  defense-in-depth backstop.
- **EULA gate.** `ceos` is permitted only when `NETLAB_MCP_ACCEPT_CEOS_EULA` is set; other licensed NOSes
  are rejected with a reason.
- **No false `pass`.** A validation run in which every test was skipped (e.g. no validation plugin for the
  device) is demoted from `pass` to `no_tests` so it is never cached as known-good.

## What the guardrails do NOT protect against

- They do **not** sandbox containerlab itself — a permitted free image is still a real,
  privileged-capable container on your host.
- They do **not** assess config *content* for safety. `pass` ≠ production-safe (see disclaimer).
- They do **not** restrict host networking, image pulls, or resource usage beyond netlab/containerlab
  defaults.
- There is **no authn/authz** on the MCP transport (stdio; local-trust assumption).
- The `no_tests` demotion prevents a false `pass`, but does not guarantee meaningful test coverage.

## Reporting a vulnerability

Please report security issues privately to **steinn@verdi.is** — do **not** open a public issue for a
vulnerability. Include a description, reproduction steps, and impact. Expect an acknowledgement within
about 5 business days. Coordinated disclosure is appreciated.
