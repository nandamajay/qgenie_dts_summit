import re
from flask import Blueprint, render_template, request, redirect, current_app
from app.services.git_service import start_clone_thread, get_state
from app.services.parser import parse_dtsi_to_mermaid

main_bp = Blueprint('main', __name__)

@main_bp.route("/")
def index():
    projects_dir = current_app.config['PROJECTS_DIR']
    projects = []
    
    if projects_dir.exists():
        for p in sorted(projects_dir.iterdir()):
            if p.is_dir():
                state = get_state(p.name)
                # Check if actually cloned on disk
                is_cloned = (p / "linux/arch/arm64/boot/dts/qcom").exists()
                status = "ready" if is_cloned else state['status']
                projects.append({
                    "name": p.name, 
                    "status": status,
                    "state_details": state
                })
                
    return render_template("index.html", projects=projects)

@main_bp.route("/create", methods=["POST"])
def create():
    name = re.sub(r'[^a-zA-Z0-9_-]', '', request.form.get('name', ''))
    if name:
        (current_app.config['PROJECTS_DIR'] / name).mkdir(parents=True, exist_ok=True)
        return redirect(f"/project/{name}")
    return redirect("/")

@main_bp.route("/project/<name>")
def project(name):
    state = get_state(name)
    proj_dir = current_app.config['PROJECTS_DIR'] / name
    dts_dir = proj_dir / "linux/arch/arm64/boot/dts/qcom"
    
    files = []
    if dts_dir.exists():
        files = sorted([f.name for f in dts_dir.glob("*.dtsi")])
        
    return render_template("project.html", name=name, files=files, state=state)

@main_bp.route("/clone/<name>", methods=["POST"])
def clone(name):
    repo = current_app.config['REPOS']['linux']
    start_clone_thread(name, repo, current_app.config['PROJECTS_DIR'])
    return redirect(f"/project/{name}")

@main_bp.route("/analyze/<name>/<filename>")
def analyze(name, filename):
    proj_dir = current_app.config['PROJECTS_DIR'] / name
    fpath = proj_dir / "linux/arch/arm64/boot/dts/qcom" / filename
    
    if not fpath.exists():
        return "File not found", 404
        
    content = fpath.read_text(errors="ignore")
    mermaid_code = parse_dtsi_to_mermaid(content)
    
    return render_template("analyze.html", 
                           name=name, 
                           filename=filename, 
                           mermaid_code=mermaid_code, 
                           source_code=content)
