# parser.py
import re
from typing import Dict, List, Tuple, Any

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
                # escape next
                out.append(text[i + 1])
                i += 2
                continue
            if ch == str_ch:
                in_str = False
            i += 1
            continue

        # not in string/comment
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
    """
    Returns (opens, closes) brace counts ignoring braces inside quoted strings.
    """
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
# Matches things like:
#   label: node-name@addr {
#   node-name@addr {
#   &phandle {
#   / {
NODE_OPEN_RE = re.compile(
    r"""
    ^\s*
    (?:
        (?P<label>[\w\-\.@]+)\s*:\s*
    )?
    (?P<name>
        / |
        &[\w\-\.@]+ |
        [\w\-\.,@/]+
    )
    \s*
    \{
    """,
    re.VERBOSE,
)

def parse_dtsi_with_map(content: str) -> Dict[str, Any]:
    """
    Parses DTSI into:
      - mermaid_code: flowchart TD with click callbacks
      - nodes: {nodeId: {label, name, display, start_line, end_line, path}}
      - edges: list of (parentId, childId)
      - paths: set of hierarchical paths for diffing
    """
    clean = _strip_comments(content)
    lines = clean.splitlines()

    # Stack holds dicts: {id, display, brace_level_at_open, path, start_line}
    stack: List[Dict[str, Any]] = []
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Tuple[str, str]] = []
    paths = set()

    # Track brace depth globally; used to close nodes accurately
    brace_depth = 0

    # Mermaid header (useMaxWidth false keeps it from shrinking)
    graph_lines = [
        "%%{init: {'flowchart': {'useMaxWidth': false, 'htmlLabels': true}}}%%",
        "graph TD",
    ]

    node_index = 0

    for idx, raw_line in enumerate(lines, start=1):  # 1-based line numbers
        line = raw_line.rstrip()

        # detect node openings (can have multiple in a single line, but rare; handle first)
        m = NODE_OPEN_RE.search(line)
        if m:
            label = m.group("label")
            name = m.group("name")
            display = label if label else name

            node_id = f"N{node_index}"
            node_index += 1

            # build path
            parent_path = stack[-1]["path"] if stack else ""
            # normalize display for path: strip quotes and spaces
            disp_norm = re.sub(r"\s+", "", display.strip('"'))
            path = f"{parent_path}/{disp_norm}" if parent_path else f"/{disp_norm}"
            paths.add(path)

            # create node
            nodes[node_id] = {
                "label": label,
                "name": name,
                "display": display,
                "start_line": idx,
                "end_line": None,
                "path": path,
            }
            graph_lines.append(f'  {node_id}["{display}"]')

            # create edge from parent
            if stack:
                parent_id = stack[-1]["id"]
                graph_lines.append(f"  {parent_id} --> {node_id}")
                edges.append((parent_id, node_id))

            # Mermaid click callback (JS function defined in analyze.html)
            graph_lines.append(f'  click {node_id} onNodeClick "{display}"')

            # determine brace depth at open: count braces in this line
            opens, closes = _count_braces_outside_strings(line)
            # open occurs at first "{", but line may close too.
            brace_depth += opens - closes

            stack.append(
                {
                    "id": node_id,
                    "display": display,
                    "brace_depth_at_open": brace_depth,  # after applying line counts
                    "path": path,
                    "start_line": idx,
                }
            )

            # if node opened and closed on same line (e.g. foo { ... };)
            # then closes would have reduced brace_depth already; we close stack based on brace transitions below too
            # Continue to closing logic after updating brace_depth (already done)
        else:
            # update brace depth even if no node open
            opens, closes = _count_braces_outside_strings(line)
            brace_depth += opens - closes

        # Close nodes when brace_depth drops below the stored open depth.
        # We stored brace_depth_at_open AFTER applying this line's brace delta, so closing is when future lines reduce depth.
        # But if braces closed on same line, brace_depth may have already dropped; handle by popping while needed:
        while stack:
            top = stack[-1]
            # When we pop, we set end_line to current idx
            # Condition: current brace_depth < top's brace_depth_at_open OR line contains '};' or '}' finishing it
            # More robust: close when brace_depth < top.open_depth OR if the line has a closing brace and we're at/under.
            if brace_depth < top["brace_depth_at_open"]:
                nid = top["id"]
                nodes[nid]["end_line"] = idx
                stack.pop()
            else:
                break

    # Close anything unclosed at EOF
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


def parse_dtsi_to_mermaid(content: str) -> str:
    """
    Backward compatible: return only mermaid code.
    """
    return parse_dtsi_with_map(content)["mermaid_code"]


def parse_dtsi_structure(content: str) -> Dict[str, Any]:
    """
    Used for diff: returns set/list of hierarchical node paths extracted from DTSI.
    """
    data = parse_dtsi_with_map(content)
    return {"paths": set(data["paths"]), "nodes": data["nodes"]}