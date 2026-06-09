"""Shared constants and the mandatory lab-vs-prod disclaimer."""
from __future__ import annotations

DISCLAIMER = (
    "LAB/LEARNING ARTIFACT — NOT production-vetted. Validated only in an isolated "
    "netlab + containerlab lab on free images, with synthetic addressing and naming. "
    "'Validated in lab' != 'safe in your network': review IP/AS/naming and interactions "
    "with existing configuration before applying to real devices."
)

# netlab validate exit-code contract (see netsim/cli/validate/__init__.py).
VALIDATE_EXIT = {
    0: "pass",
    1: "fail",
    2: "no_tests",
    3: "warning",
    124: "timeout",  # our runner's synthetic timeout code
}

# Rolled-up verdicts considered "good enough" to serve as known-good.
GOOD_VERDICTS = frozenset({"pass", "warning"})
