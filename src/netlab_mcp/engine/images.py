"""Host docker-image awareness: which NOS images are loaded, and which device they serve.

vrnetlab-built and vendor-restricted images exist ONLY in the local docker store — a
topology that references a missing/default tag hard-fails at `netlab up` with a pull error.
This module maps netlab devices to images that are actually present so the platform gate
and topology generator can work with the host's library instead of netlab's defaults.
"""
from __future__ import annotations

import re
import time
from functools import lru_cache

import yaml

from .probes import _cmd_output
from .runner import cleanup, new_workdir, run_netlab

# Modern hellt/vrnetlab builds use names netlab's image table doesn't know about yet.
# Checked against both: netlab 26.06 `show images` vs vrnetlab master `make` output.
_EXTRA_DEVICE_REPOS: dict[str, list[str]] = {
    "nxos": ["vrnetlab/cisco_n9kv", "vrnetlab/cisco_nxostitanium"],
    "fortios": ["vrnetlab/fortinet_fortigate"],
    "iosxr": ["ios-xr/xrd-vrouter"],
}

_CACHE_TTL_S = 30.0
_images_cache: tuple[float, dict[str, set[str]]] | None = None


def installed_images(refresh: bool = False) -> dict[str, set[str]]:
    """{repo: {tags}} from the local docker store. Cached ~30s; {} without docker."""
    global _images_cache
    now = time.monotonic()
    if not refresh and _images_cache and now - _images_cache[0] < _CACHE_TTL_S:
        return _images_cache[1]

    repos: dict[str, set[str]] = {}
    out = _cmd_output(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], timeout=15)
    for line in (out or "").splitlines():
        repo, _, tag = line.strip().rpartition(":")
        if repo and tag and tag != "<none>":
            repos.setdefault(repo, set()).add(tag)
    _images_cache = (now, repos)
    return repos


@lru_cache(maxsize=1)
def _netlab_default_clab_images() -> dict[str, str]:
    """{device: 'repo:tag'} clab defaults from `netlab show images`. {} on ANY failure.

    Must never raise: it sits under generate_topology, check_platforms (with
    NETLAB_MCP_ALLOW_INSTALLED) and host_check — the doctor tool especially has to keep
    working on a host where the netlab binary is missing (RuntimeError from netlab_bin()).
    """
    wd = new_workdir("nlmcp-img-")
    try:
        r = run_netlab(["show", "images", "--format", "yaml"], cwd=wd, timeout=60)
        if not r.ok:
            return {}
        data = yaml.safe_load(r.stdout) or {}
        return {
            dev: spec["clab"]
            for dev, spec in data.items()
            if isinstance(spec, dict) and isinstance(spec.get("clab"), str)
        }
    except (yaml.YAMLError, RuntimeError):
        return {}
    finally:
        cleanup(wd)


def _version_key(tag: str) -> tuple:
    """Sort key putting the highest-looking version last; 'latest' below any number."""
    if tag.lower() == "latest":
        return (0, ())
    return (1, tuple(int(n) for n in re.findall(r"\d+", tag)) or (0,))


def _tags_for_device(device: str, repo: str, tags: set[str]) -> set[str]:
    """Filter shared-repo tags: cisco_iol holds both iol (plain) and ioll2 (l2-/L2-) tags."""
    if repo.endswith("cisco_iol"):
        l2 = {t for t in tags if t.lower().startswith("l2")}
        return l2 if device == "ioll2" else tags - l2
    return tags


def device_image_map() -> dict[str, str]:
    """{device: 'repo:tag'} for every netlab device backed by a locally loaded image.

    Tag choice is deterministic: netlab's default tag when it is loaded, else the
    highest version-sorted loaded tag (an explicit version beats 'latest'; equal
    version keys tie-break on the tag string so set iteration order never decides).
    """
    local = installed_images()
    if not local:
        return {}

    chosen: dict[str, str] = {}
    defaults = _netlab_default_clab_images()
    candidates: dict[str, list[str]] = {}
    for dev, image in defaults.items():
        candidates.setdefault(dev, []).append(image.rpartition(":")[0])
    for dev, repos in _EXTRA_DEVICE_REPOS.items():
        candidates.setdefault(dev, []).extend(repos)

    for dev, repos in candidates.items():
        default_image = defaults.get(dev, "")
        for repo in repos:
            tags = _tags_for_device(dev, repo, local.get(repo, set()))
            if not tags:
                continue
            default_tag = default_image.rpartition(":")[2]
            if default_image.rpartition(":")[0] == repo and default_tag in tags:
                chosen[dev] = default_image
            else:
                chosen[dev] = f"{repo}:{max(tags, key=lambda t: (_version_key(t), t))}"
            break
    return chosen


def devices_with_images() -> set[str]:
    """netlab devices that can deploy from the local image store right now."""
    return set(device_image_map())
