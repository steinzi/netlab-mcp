"""Generate a high-level Excalidraw architecture diagram for netlab-mcp.

Run: python scripts/gen_diagram.py
Output: docs/netlab-mcp-architecture.excalidraw  (open at excalidraw.com -> File > Open)
"""
import itertools
import json
from pathlib import Path

_id = itertools.count(1)


def nid(prefix: str) -> str:
    return f"{prefix}{next(_id)}"


_seed = itertools.count(1000)


def seed() -> int:
    return next(_seed)


# --- boxes: key -> (x, y, w, h, bg, text) -------------------------------------
BOXES = {
    "client": (450, 40, 300, 80, "#a5d8ff",
               "LLM / MCP Client"),
    "server": (420, 210, 360, 120, "#d0bfff",
               "netlab-mcp server\n(FastMCP · stdio)\nguardrails: allow-list + disclaimer"),
    "offline": (40, 430, 350, 190, "#b2f2bb",
                "OFFLINE tools  (no docker)\n\ngenerate_topology · render_config\nquery_compatibility · get_known_good\nlist_examples · report_failure"),
    "lab": (820, 430, 360, 170, "#ffc9c9",
            "LAB tool  (docker + containerlab)\n\nvalidate_in_lab\nprobe → deploy → validate"),
    "engine": (430, 680, 350, 130, "#ffec99",
               "netlab engine  (vendored)\n\nnetlab create · initial -o\nvalidate · show module-support"),
    "config": (40, 700, 350, 150, "#d3f9d8",
               "Validated config (returned)\n\nsrlinux set-path · frr vtysh\n+ clab.yml"),
    "clab": (820, 690, 360, 150, "#ffd8a8",
             "containerlab\nsrlinux + frr containers\n\nexit code → verdict 0/1/3/2"),
    "store": (430, 900, 350, 130, "#dee2e6",
              "Matrix store\nsqlite matrix.db + matrix.yaml\nversion-scoped verdicts"),
}

# --- edges: (from, to, label, dashed) -----------------------------------------
EDGES = [
    ("client", "server", "MCP stdio", False),
    ("server", "offline", "", False),
    ("server", "lab", "", False),
    ("offline", "engine", "subprocess: render", False),
    ("engine", "config", "config files", False),
    ("lab", "engine", "subprocess: up + validate", False),
    ("engine", "clab", "netlab up → deploy", False),
    ("clab", "store", "record verdict", False),
    ("store", "offline", "known-good / observed", True),
]

# explicit elbow routes (absolute waypoints) for edges that would otherwise cut a box
ROUTES = {
    ("clab", "store"): {"pts": [(1000, 840), (1000, 965), (780, 965)],
                        "label_at": (1010, 905)},
    ("store", "offline"): {"pts": [(430, 965), (18, 965), (18, 525), (40, 525)],
                          "label_at": (18, 600)},
}

elements = []
box_ids = {}
box_bound = {}  # box key -> list of boundElements


def base(t, x, y, w, h):
    return {
        "id": "", "type": t, "x": x, "y": y, "width": w, "height": h, "angle": 0,
        "strokeColor": "#1e1e1e", "backgroundColor": "transparent", "fillStyle": "solid",
        "strokeWidth": 2, "strokeStyle": "solid", "roughness": 1, "opacity": 100,
        "groupIds": [], "frameId": None, "roundness": {"type": 3}, "seed": seed(),
        "version": 1, "versionNonce": seed(), "isDeleted": False, "boundElements": [],
        "updated": 1, "link": None, "locked": False,
    }


# rectangles + their bound labels
for key, (x, y, w, h, bg, text) in BOXES.items():
    rid = nid("r")
    box_ids[key] = rid
    rect = base("rectangle", x, y, w, h)
    rect.update(id=rid, backgroundColor=bg)
    box_bound[key] = []
    rect["boundElements"] = box_bound[key]

    tid = nid("t")
    lines = text.split("\n")
    th = len(lines) * 20
    txt = base("text", x + 10, y + h / 2 - th / 2, w - 20, th)
    txt.update(
        id=tid, text=text, originalText=text, fontSize=16, fontFamily=2,
        textAlign="center", verticalAlign="middle", containerId=rid,
        lineHeight=1.25, roundness=None,
    )
    box_bound[key].append({"type": "text", "id": tid})
    elements.append(rect)
    elements.append(txt)

def _clip(cx, cy, hw, hh, vx, vy, gap=4):
    """Point where the ray (vx,vy) from box center hits the border, pushed out by gap."""
    s = 1.0 / max(abs(vx) / hw, abs(vy) / hh)
    mag = (vx * vx + vy * vy) ** 0.5 or 1.0
    return (cx + vx * s + vx / mag * gap, cy + vy * s + vy / mag * gap)


def anchors(src, dst):
    """Endpoints on each box border along the center-to-center line (clean diagonals)."""
    sx, sy, sw, sh, *_ = BOXES[src]
    dx, dy, dw, dh, *_ = BOXES[dst]
    scx, scy, dcx, dcy = sx + sw / 2, sy + sh / 2, dx + dw / 2, dy + dh / 2
    vx, vy = dcx - scx, dcy - scy
    start = _clip(scx, scy, sw / 2, sh / 2, vx, vy)
    end = _clip(dcx, dcy, dw / 2, dh / 2, -vx, -vy)
    return start, end


# arrows (no bindings; straight border-clip or explicit elbow routes) + standalone labels
for src, dst, label, dashed in EDGES:
    route = ROUTES.get((src, dst))
    if route:
        pts = [tuple(p) for p in route["pts"]]
        lx, ly = route["label_at"]
    else:
        s, e = anchors(src, dst)
        pts = [s, e]
        lx, ly = (s[0] + e[0]) / 2, (s[1] + e[1]) / 2

    x0, y0 = pts[0]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    aid = nid("a")
    arrow = base("arrow", x0, y0, max(xs) - min(xs), max(ys) - min(ys))
    arrow.update(
        id=aid,
        roundness=None,
        strokeStyle="dashed" if dashed else "solid",
        strokeColor="#868e96" if dashed else "#1e1e1e",
        points=[[p[0] - x0, p[1] - y0] for p in pts],
        lastCommittedPoint=None,
        startBinding=None, endBinding=None,
        startArrowhead=None, endArrowhead="arrow",
    )
    elements.append(arrow)

    if label:
        tid = nid("t")
        w = max(80, len(label) * 8 + 12)
        txt = base("text", lx - w / 2, ly - 11, w, 22)
        txt.update(
            id=tid, text=label, originalText=label, fontSize=13, fontFamily=2,
            textAlign="center", verticalAlign="middle", containerId=None,
            lineHeight=1.25, roundness=None, backgroundColor="#ffffff",
        )
        elements.append(txt)

# title
title = base("text", 40, 0, 700, 30)
title.update(
    id=nid("t"), text="netlab-mcp — how it works (high level)", originalText="netlab-mcp — how it works (high level)",
    fontSize=24, fontFamily=2, textAlign="left", verticalAlign="top",
    containerId=None, lineHeight=1.25, roundness=None,
)
elements.append(title)

doc = {
    "type": "excalidraw",
    "version": 2,
    "source": "netlab-mcp/scripts/gen_diagram.py",
    "elements": elements,
    "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
    "files": {},
}

out = Path(__file__).resolve().parents[1] / "docs" / "netlab-mcp-architecture.excalidraw"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(doc, indent=2))
print(f"wrote {out}")
print(f"elements: {len(elements)} | boxes: {len(BOXES)} | edges: {len(EDGES)}")
