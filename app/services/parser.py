# parser.py
import re
from typing import Dict, List, Tuple, Any, Optional

# --- Utilities: comment stripping while preserving strings ---
def _strip_comments(text: str) -> str:
    """
    Removes // and /* */ comments while preserving quoted strings.
    """
    out = []
    i = 0
    n = len(text)
    in_str = False
    str_ch = ""
    in_line_comment = False
    in_block_comment = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == str_ch:
                in_str = False
            i += 1
            continue

        if ch in ("'", '"'):
            in_str = True
            str_ch = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _count_braces_outside_strings(line: str) -> Tuple[int, int]:
    opens = closes = 0
    in_str = False
    str_ch = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if in_str:
            if ch == "\\" and i + 1 < len(line):
                i += 2
                continue
            if ch == str_ch:
                in_str = False
                i += 1
                continue
        if ch in ("'", '"'):
            in_str = True
            str_ch = ch
            i += 1
            continue
        if ch == "{":
            opens += 1
        elif ch == "}":
            closes += 1
        i += 1
    return opens, closes


# --- Node detection ---
NODE_OPEN_RE = re.compile(
    r"""
    ^\s*
    (?:
      (?P<label>[\w\-\.\@]+)\s*:\s*
    )?
    (?P<name>
      / |
      &[\w\-\.\@]+ |
      [\w\-\.\,\@/]+
    )
    \s*
    \{
    """,
    re.VERBOSE,
)


def parse_dtsi_with_map(content: str) -> Dict[str, Any]:
    """
    Phase-1: full tree parser -> Mermaid + node_map for click-to-source.
    """
    clean = _strip_comments(content)
    lines = clean.splitlines()

    stack: List[Dict[str, Any]] = []
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Tuple[str, str]] = []
    paths = set()
    brace_depth = 0

    graph_lines = [
        "%%{init: {'flowchart': {'useMaxWidth': false, 'htmlLabels': true}}}%%",
        "graph TD",
    ]

    node_index = 0
    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip()

        m = NODE_OPEN_RE.search(line)
        if m:
            label = m.group("label")
            name = m.group("name")
            display = label if label else name

            node_id = f"N{node_index}"
            node_index += 1

            parent_path = stack[-1]["path"] if stack else ""
            disp_norm = re.sub(r"\s+", "", display.strip('"'))
            path = f"{parent_path}/{disp_norm}" if parent_path else f"/{disp_norm}"
            paths.add(path)

            nodes[node_id] = {
                "label": label,
                "name": name,
                "display": display,
                "start_line": idx,
                "end_line": None,
                "path": path,
            }

            graph_lines.append(f' {node_id}["{display}"]')

            if stack:
                parent_id = stack[-1]["id"]
                graph_lines.append(f" {parent_id} --> {node_id}")
                edges.append((parent_id, node_id))

            graph_lines.append(f' click {node_id} onNodeClick "{display}"')

            opens, closes = _count_braces_outside_strings(line)
            brace_depth += opens - closes

            stack.append(
                {
                    "id": node_id,
                    "display": display,
                    "brace_depth_at_open": brace_depth,
                    "path": path,
                    "start_line": idx,
                }
            )
        else:
            opens, closes = _count_braces_outside_strings(line)
            brace_depth += opens - closes

        while stack:
            top = stack[-1]
            if brace_depth < top["brace_depth_at_open"]:
                nid = top["id"]
                nodes[nid]["end_line"] = idx
                stack.pop()
            else:
                break

    if lines:
        last_line = len(lines)
        while stack:
            nid = stack[-1]["id"]
            nodes[nid]["end_line"] = last_line
            stack.pop()

    return {
        "mermaid_code": "\n".join(graph_lines),
        "nodes": nodes,
        "edges": edges,
        "paths": sorted(paths),
    }


def parse_dtsi_structure(content: str) -> Dict[str, Any]:
    data = parse_dtsi_with_map(content)
    return {"paths": set(data["paths"]), "nodes": data["nodes"]}


# ----------------------------------------------------------------------
# Universal pictorial view: Overview diagram for ALL DTSIs (safe + small)
# ----------------------------------------------------------------------

def _top_name_from_path(path: str) -> Optional[str]:
    # path like "/soc/gcc" -> "soc"
    parts = [p for p in path.split("/") if p]
    return parts[0] if parts else None


def _second_name_from_path(path: str) -> Optional[str]:
    # "/soc/gcc" -> "gcc"
    parts = [p for p in path.split("/") if p]
    return parts[1] if len(parts) > 1 else None


def parse_overview_mermaid(content: str, max_root_children: int = 18, max_soc_children: int = 18) -> str:
    """
    Builds a small "subsystem map" diagram:
      / -> top-level nodes (cpus, soc, reserved-memory, firmware, thermal-zones, etc.)
      soc -> key second-level nodes (limited count)
    Works for ALL DTSIs and avoids Mermaid size limits.
    """
    data = parse_dtsi_with_map(content)
    paths: List[str] = data.get("paths", [])
    # Collect top-level nodes and soc second-level nodes
    root_children = {}
    soc_children = {}

    for p in paths:
        top = _top_name_from_path(p)
        if not top:
            continue
        # Skip the synthetic "/" only node
        if top == "":
            continue
        root_children[top] = root_children.get(top, 0) + 1

        if top == "soc":
            second = _second_name_from_path(p)
            if second:
                soc_children[second] = soc_children.get(second, 0) + 1

    # Sort by "population" (how many nodes exist under that subtree), descending
    root_sorted = sorted(root_children.items(), key=lambda kv: (-kv[1], kv[0]))[:max_root_children]
    soc_sorted = sorted(soc_children.items(), key=lambda kv: (-kv[1], kv[0]))[:max_soc_children]

    # Mermaid diagram
    lines = [
        "%%{init: {'flowchart': {'useMaxWidth': false}}}%%",
        "flowchart LR",
        '  ROOT["/ (root)"]',
    ]

    # Root-level hubs
    for name, count in root_sorted:
        nid = f"R_{re.sub(r'[^a-zA-Z0-9_]', '_', name)}"
        lines.append(f'  {nid}["{name}\\n({count} nodes)"]')
        lines.append(f"  ROOT --> {nid}")

    # Expand soc subtree (if present)
    if "soc" in root_children and soc_sorted:
        lines.append('  subgraph SOC["/soc (expanded)"]')
        for name, count in soc_sorted:
            nid = f"SOC_{re.sub(r'[^a-zA-Z0-9_]', '_', name)}"
            lines.append(f'    {nid}["{name}\\n({count})"]')
        lines.append("  end")
        lines.append("  R_soc --> SOC")  # uses node id generated above if soc exists
        # Connect SOC cluster to its children boxes
        for name, _count in soc_sorted:
            nid = f"SOC_{re.sub(r'[^a-zA-Z0-9_]', '_', name)}"
            lines.append(f"  SOC --> {nid}")

    return "\n".join(lines)


# ----------------------------------------------------------------------
# Semantic pictorial view: Power/Idle (only when detected)
# ----------------------------------------------------------------------

_CPU_LABEL_RE = re.compile(r"\bcpu(?P<idx>\d+)\s*:\s*cpu@\d+\s*\{", re.MULTILINE)
_CPU_PD_RE = re.compile(r"\bcpu_pd(?P<idx>\d+)\s*:\s*power-domain-cpu\d+\s*\{", re.MULTILINE)

_IDLE_BLOCK_RE = re.compile(
    r"(?P<label>cpu_sleep|cluster_sleep)\s*:\s*[\w\-@\.]+\s*\{(?P<body>.*?)\n\s*\};",
    re.DOTALL | re.MULTILINE,
)
_PSCI_PARAM_RE = re.compile(r"arm,psci-suspend-param\s*=\s*<(?P<val>[^>]+)>\s*;", re.MULTILINE)


def extract_idle_info(content: str) -> Dict[str, Any]:
    clean = _strip_comments(content)
    if "domain-idle-states" not in clean and "idle-states" not in clean:
        return {"found": False}

    cpu_idxs = sorted({int(m.group("idx")) for m in _CPU_LABEL_RE.finditer(clean)})
    pd_idxs = sorted({int(m.group("idx")) for m in _CPU_PD_RE.finditer(clean)})

    cpu_sleep_param: Optional[str] = None
    cluster_sleep_param: Optional[str] = None

    for m in _IDLE_BLOCK_RE.finditer(clean):
        label = m.group("label")
        body = m.group("body") or ""
        pm = _PSCI_PARAM_RE.search(body)
        if pm:
            val = pm.group("val").strip()
            if label == "cpu_sleep":
                cpu_sleep_param = val
            elif label == "cluster_sleep":
                cluster_sleep_param = val

    has_cluster_pd = "cluster_pd:" in clean
    has_mpm = re.search(r"\bmpm\s*:\s*interrupt-controller", clean) is not None

    found = bool(cpu_sleep_param or cluster_sleep_param or (cpu_idxs and has_cluster_pd))
    return {
        "found": found,
        "cpu_idxs": cpu_idxs if cpu_idxs else [0, 1, 2, 3],
        "pd_idxs": pd_idxs if pd_idxs else [0, 1, 2, 3],
        "cpu_sleep_param": cpu_sleep_param,
        "cluster_sleep_param": cluster_sleep_param,
        "has_cluster_pd": has_cluster_pd,
        "has_mpm": has_mpm,
    }


def parse_idle_mermaid(content: str) -> str:
    info = extract_idle_info(content)
    if not info.get("found"):
        return ""

    cpu_idxs: List[int] = info["cpu_idxs"]
    pd_idxs: List[int] = info["pd_idxs"]
    cpu_param = info.get("cpu_sleep_param") or "—"
    cluster_param = info.get("cluster_sleep_param") or "—"

    lines = [
        "%%{init: {'flowchart': {'useMaxWidth': false}}}%%",
        "flowchart TB",
        '  subgraph CPU_Layer["CPU Cores"]',
    ]
    for i in cpu_idxs[:8]:
        lines.append(f'    CPU{i}["CPU{i}"]')
    lines.append("  end")

    lines.append(f'  CPU_IDLE["CPU Idle State\\npower-collapse\\npsci={cpu_param}"]')
    lines.append('  subgraph CPU_PD["CPU Power Domains"]')
    for i in pd_idxs[:8]:
        lines.append(f'    PD{i}["cpu_pd{i}"]')
    lines.append("  end")
    lines.append(f'  CLUSTER_IDLE["Cluster Idle State\\ncluster-sleep\\npsci={cluster_param}"]')
    lines.append('  CLUSTER_PD["cluster_pd"]')
    lines.append('  MPM["MPM\\n(System Power Manager)"]')

    for i in cpu_idxs[:8]:
        lines.append(f"  CPU{i} --> PD{i}" if i in pd_idxs[:8] else f"  CPU{i} --> CPU_IDLE")
    for i in pd_idxs[:8]:
        lines.append(f"  PD{i} --> CPU_IDLE")

    lines.append("  CPU_IDLE --> CLUSTER_IDLE")
    lines.append("  CLUSTER_IDLE --> CLUSTER_PD")
    lines.append("  CLUSTER_PD --> MPM")

    return "\n".join(lines)