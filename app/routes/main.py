# main.py
import re
import difflib
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, current_app, abort, jsonify

from app.services.git_service import start_clone_thread, get_state
from app.services.parser import (
    parse_dtsi_structure,
    parse_idle_mermaid,
    parse_overview_mermaid,
)

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    projects_dir = current_app.config["PROJECTS_DIR"]
    projects = []
    if projects_dir.exists():
        for p in sorted(projects_dir.iterdir()):
            if p.is_dir():
                state = get_state(p.name)
                is_cloned = (p / "linux/arch/arm64/boot/dts/qcom").exists()
                status = "ready" if is_cloned else state["status"]
                projects.append({"name": p.name, "status": status, "state_details": state})
    return render_template("index.html", projects=projects)


@main_bp.route("/create", methods=["POST"])
def create():
    name = re.sub(r"[^a-zA-Z0-9_-]", "", request.form.get("name", ""))
    if name:
        (current_app.config["PROJECTS_DIR"] / name).mkdir(parents=True, exist_ok=True)
        return redirect(f"/project/{name}")
    return redirect("/")


@main_bp.route("/project/<name>")
def project(name):
    state = get_state(name)
    proj_dir = current_app.config["PROJECTS_DIR"] / name
    dts_dir = proj_dir / "linux/arch/arm64/boot/dts/qcom"
    files = []
    if dts_dir.exists():
        files = sorted([f.name for f in dts_dir.glob("*.dtsi")])
    return render_template("project.html", name=name, files=files, state=state)


@main_bp.route("/clone/<name>", methods=["POST"])
def clone(name):
    repo = current_app.config["REPOS"]["linux"]
    start_clone_thread(name, repo, current_app.config["PROJECTS_DIR"])
    return redirect(f"/project/{name}")


@main_bp.route("/state/<name>")
def state(name):
    """Return clone/sync state for live polling."""
    return jsonify(get_state(name))


@main_bp.route("/preview/<name>/<filename>")
def preview(name, filename):
    """Return a small snippet of the DTSI so the drawer can show a quick preview."""
    fpath = _safe_dtsi_path(name, filename)
    lines = fpath.read_text(errors="ignore").splitlines()
    head_n = 220
    head = "\n".join(lines[:head_n])
    return jsonify(
        {
            "file": Path(filename).name,
            "total_lines": len(lines),
            "head": head,
        }
    )


def _safe_dtsi_path(project: str, filename: str) -> Path:
    proj_dir = current_app.config["PROJECTS_DIR"] / project
    dts_dir = proj_dir / "linux/arch/arm64/boot/dts/qcom"
    fn = Path(filename).name
    if not fn.endswith(".dtsi"):
        abort(400, "Invalid filename")
    fpath = dts_dir / fn
    if not fpath.exists():
        abort(404, "File not found")
    return fpath


@main_bp.route("/analyze/<name>/<filename>")
def analyze(name, filename):
    fpath = _safe_dtsi_path(name, filename)
    content = fpath.read_text(errors="ignore")

    # Overview view (default): for all DTSIs
    overview_mermaid = parse_overview_mermaid(content)

    # Optional: Power/Idle view (only when present)
    idle_mermaid = parse_idle_mermaid(content)
    has_idle = bool(idle_mermaid.strip())

    src_lines = content.splitlines()
    return render_template(
        "analyze.html",
        name=name,
        filename=Path(filename).name,
        overview_mermaid=overview_mermaid,
        idle_mermaid=idle_mermaid,
        has_idle=has_idle,
        source_lines=src_lines,
    )


@main_bp.route("/diff/<name>")
def diff_view(name):
    proj_dir = current_app.config["PROJECTS_DIR"] / name
    dts_dir = proj_dir / "linux/arch/arm64/boot/dts/qcom"
    if not dts_dir.exists():
        abort(404, "Repo not synced")

    files = sorted([f.name for f in dts_dir.glob("*.dtsi")])
    a = request.args.get("a", "")
    b = request.args.get("b", "")

    diff_html = None
    summary = None
    tree_delta = None

    if a and b:
        pa = _safe_dtsi_path(name, a)
        pb = _safe_dtsi_path(name, b)
        ca = pa.read_text(errors="ignore").splitlines()
        cb = pb.read_text(errors="ignore").splitlines()

        hd = difflib.HtmlDiff(tabsize=4, wrapcolumn=120)
        diff_html = hd.make_table(ca, cb, fromdesc=a, todesc=b, context=True, numlines=4)

        ud = list(difflib.unified_diff(ca, cb, lineterm=""))
        added = sum(1 for x in ud if x.startswith("+") and not x.startswith("+++"))
        removed = sum(1 for x in ud if x.startswith("-") and not x.startswith("---"))
        summary = {"added": added, "removed": removed}

        sa = parse_dtsi_structure("\n".join(ca))["paths"]
        sb = parse_dtsi_structure("\n".join(cb))["paths"]
        tree_delta = {
            "added_nodes": sorted(list(sb - sa)),
            "removed_nodes": sorted(list(sa - sb)),
        }

    return render_template(
        "diff.html",
        name=name,
        files=files,
        a=a,
        b=b,
        diff_html=diff_html,
        summary=summary,
        tree_delta=tree_delta,
    )