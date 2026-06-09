# TODO

Findings from MCP tool smoke test (2026-06-09, netlab v26.06, macOS / no containerlab).
All 7 tools functional; items below are fixes/improvements.

## Bugs

### F1 — `query_compatibility` multi-platform filter ignored
- **Symptom:** `platforms: ["frr"]` narrows declared output to frr. `platforms: ["frr", "srlinux"]` returns ALL ~33 platforms — filter not applied.
- **Likely cause:** netlab `show module-support -d DEVICE` takes a single device; multi-platform path falls back to full dump.
- **Fix:** loop the netlab query per platform and merge, or filter the declared dict in-process by the requested platform list before returning.
- **Severity:** minor (data correct, just unfiltered).
- **✅ RESOLVED:** `compat.declared_support(platforms=...)` filters the declared dict in-process for any platform count (single still uses `-d` fast path). Test: `test_declared_support_multi_platform_filter`.

### F3 — `generate_topology` `valid` flag is host-dependent (false-negative)
- **Symptom:** ospf/`[frr, vyos]` returns `valid: false`. Topology is structurally correct; fails only because the `valid` precheck runs a full `netlab create`, and vyos's containerlab def bind-mounts `/lib/modules` (absent on macOS).
  - Real error (only obtained by running netlab manually): `IncorrectValue in clab: File /lib/modules mapped to /lib/modules on node peer does not exist`
  - srlinux/frr have no such mount → pass on macOS.
- **Fix options:**
  1. Make the `valid` precheck topology-only (parse/data-model) and NOT gated on host clab bindings, so `valid` means "topology is sound" regardless of host.
  2. OR keep the create-based check but distinguish `topology_invalid` vs `host_unsupported` in the result.
- **Also (F3b):** propagate the root-cause line. Tool returned generic `Errors encountered... Fatal error in netlab`; the actionable `IncorrectValue in clab: ...` line was dropped. Capture and surface netlab's specific error lines.
- **✅ RESOLVED (F3):** `validate_topology` now runs `netlab create -o yaml` (parse + data-model transform, emits YAML instead of provider files) → host-independent; vyos topology is `valid` on macOS. Genuine errors still non-zero. Test: `test_validate_is_host_independent_for_vyos`.
- **✅ RESOLVED (F3b):** `RunResult.error_lines()` now matches netlab error categories (IncorrectValue/Type/Attr/Key, MissingValue/Dependency), so the specific line is surfaced. Test: `test_validate_surfaces_specific_netlab_error`.

## Improvements

### F2 — `generate_topology` silently defaults to bgp on unrecognized intent
- **Symptom:** intent `"xyzzy frobnicate the wibble"` → `ok: true`, `module: bgp`, no signal. Caller can't tell inference matched vs fell back.
- **Fix:** emit a warning (e.g. `"intent did not match a known module keyword; defaulted to bgp"`) when no module keyword hits, or echo the matched keyword in `notes`.
- **✅ RESOLVED:** `topogen.generate` warns when no module keyword matched (defaulted to bgp) and echoes the matched keyword in `notes` otherwise. Test: `test_generate_topology_warns_on_unrecognized_intent`.

## Confirmed good (no action)
- Disclaimer attached to all render + lab outputs.
- `.work/` temp dirs auto-cleaned per render — no leakage.
- Store round-trip works: `report_failure` write → `observed` read → `conflicts` flag.
- `validate_in_lab` degrades cleanly to verdict `unavailable` with a docker/containerlab probe when no lab host.
- `render_config` produces real per-device config (FRR CLI, SRLinux JSON-RPC), `clab.yml`, daemons/hosts/init; `nodes` filter works; malformed-yaml path errors cleanly.
