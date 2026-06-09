# Contributing to netlab-mcp

Thanks for your interest! netlab-mcp is intentionally a **thin wrapper** over
[`ipspace/netlab`](https://github.com/ipspace/netlab): it serves netlab's outputs and records lab
verdicts. Please do **not** reimplement netlab's data-model transform, render, or validate pipeline here.

## Dev setup

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e '.[dev]'                              # networklab (the netlab binary) from PyPI
git clone --depth 1 https://github.com/ipspace/netlab netlab   # only list_examples needs the source tree
```

## Test gates

- **Required for every PR:** `pytest -m "not docker"` — the offline + contract suite
  (`tests/test_offline.py`, `tests/test_contract.py`). CI runs this on Python 3.10–3.12.
- **Lint:** `ruff check .` (config in `pyproject.toml`).
- **Lab tests (optional, docker-gated):** `pytest -m docker` — requires the full lab prerequisites
  (containerlab ≥ 0.75.0, Ansible + per-device collections, scoped passwordless sudo; see the README
  "Install — lab" section). Without a lab host these auto-skip.
- **Manual offline smoke:** `PYTHONPATH=src python scripts/smoke_offline.py`.

## PR conventions

- Branch off `main`; one logical change per PR.
- [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`) —
  matches the existing history.
- Never hand-edit `store/matrix.db` (gitignored) — verdicts are written by tool runs. The
  `store/matrix.yaml` mirror is committed; let it change via runs, not by hand.
- Regenerate the architecture diagram with `python scripts/gen_diagram.py` if the architecture changes.
- Contributions are accepted under the project's [Apache-2.0](LICENSE) license.

## Security-sensitive changes

Any change touching the platform allow-list (`src/netlab_mcp/config.py`), device/tool resolution
(`src/netlab_mcp/engine/transform.py`), or the lab deploy path (`src/netlab_mcp/engine/lab.py`,
`runner.py`) **must preserve fail-closed behavior** and add a regression test. See [SECURITY.md](SECURITY.md).

## Roadmap — device & validation support

- **Adding a device:** extend `FREE_PLATFORMS` only for genuinely-free containerlab images; add a lab
  fixture and a `validate_in_lab` test; document the per-device Ansible collection it needs.
- **Validation plugins:** netlab's BGP validation plugin ships only for some devices (e.g. `frr`, `eos`).
  The generated topology must anchor `validate:` tests on a plugin-capable node; see
  `engine/topogen.py` and the false-pass guard in `engine/lab.py`. Model new tests on
  `tests/fixtures/mvp_bgp.yml`.
- **Licensed/EULA NOSes** (nxos/iosxr/sros/junos/…) are deferred to a future self-hosted runner with image
  entitlements.
