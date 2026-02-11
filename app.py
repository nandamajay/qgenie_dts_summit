# app.py (Phase-1.5: dashboard + async clone progress)
import os
import json
import subprocess
import shutil
import threading
import time
import re
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, Response, send_file, redirect

APP_PORT = int(os.environ.get("PORT", "8080"))
WORK_DIR = Path(os.environ.get("WORK_DIR", "/work")).resolve()
PROJECTS_DIR = WORK_DIR / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

# Two upstream options for Phase-1 simplicity
REPOS = {
    "linux": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git",
    "linux-next": "https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git",
}

app = Flask(__name__)

# ------------------------
# Template + render helper
# ------------------------
HTML_BASE = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>QGenie Phase‑1</title>
    <style>
      body{font-family: system-ui, Arial; background:#0f172a; color:#e2e8f0;}
      .wrap{max-width: 980px; margin: 24px auto;}
      .card{background:#111827; border:1px solid #334155; border-radius:12px; padding:20px; margin-bottom:16px}
      input,select,button{font-size:15px}
      input[type=text]{width:100%; background:#0b1220; color:#e2e8f0; border:1px solid #334155; border-radius:8px; padding:10px}
      button{padding:8px 12px; border:0; border-radius:8px; background:#2563eb; color:#fff; cursor:pointer}
      button.secondary{background:#334155}
      .row{display:flex; gap:8px; align-items:center}
      .mt8{margin-top:8px} .mt12{margin-top:12px} .mt16{margin-top:16px}
      .mono{font-family: ui-monospace, SFMono-Regular, Menlo, monospace;}
      .dim{color:#94a3b8}
      a{color:#93c5fd; text-decoration:none}
      table{width:100%; border-collapse: collapse;}
      th,td{border-bottom:1px solid #223046; padding:8px; font-size:14px}
      .badge{padding:2px 8px; border-radius:8px; font-weight:600;}
      .b-idle{background:#1f2937; color:#94a3b8}
      .b-cloning{background:#1f2937; color:#f59e0b}
      .b-ready{background:#1f2937; color:#22c55e}
      .b-error{background:#1f2937; color:#ef4444}
      .right{float:right}
      .btn-link{background:#334155; padding:6px 10px; border-radius:8px; color:#e2e8f0}
    </style>
  </head>
  <body>
    <div class="wrap">
      {body}
    </div>
  </body>
</html>
"""

# IMPORTANT: Avoid str.format on HTML with CSS braces
def render(body_html: str) -> Response:
    return Response(HTML_BASE.replace("{body}", body_html), mimetype="text/html")


# ------------------------
# Clone state & helpers
# ------------------------
STATE = {}  # { name: {"status": "idle|cloning|ready|error", "percent": int, "log": str} }

def _state(name, **updates):
    s = STATE.get(name, {"status": "idle", "percent": 0, "log": ""})
    s.update(updates)
    STATE[name] = s
    return s

def _project_dirs(name):
    proj_dir = PROJECTS_DIR / name
    linux_dir = proj_dir / "linux"
    log_file = proj_dir / "clone.log"
    return proj_dir, linux_dir, log_file

def _run_clone(name, repo_url):
    proj_dir, linux_dir, log_file = _project_dirs(name)
    proj_dir.mkdir(parents=True, exist_ok=True)
    if linux_dir.exists():
        shutil.rmtree(linux_dir)
    _state(name, status="cloning", percent=0, log=str(log_file))
    cmd = ["git", "clone", "--progress", "--depth", "1", repo_url, str(linux_dir)]
    with open(log_file, "w", encoding="utf-8", errors="ignore") as lf:
        try:
            p = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=str(proj_dir)
            )
            pct = 0
            for line in p.stdout:
                lf.write(line)
                lf.flush()
                # Pull % from lines like: "Receiving objects:  73% (..)"
                m = re.search(r'([Rr]eceiving objects|[Rr]esolving deltas|Updating files).*?(\\d{1,3})%', line)
                if m:
                    pct = max(pct, min(100, int(m.group(2))))
                    _state(name, percent=pct)
            p.wait()
            if p.returncode == 0:
                _state(name, status="ready", percent=100)
            else:
                _state(name, status="error")
        except Exception as e:
            lf.write(f"\\nERROR: {e}\\n")
            _state(name, status="error")


# ------------------------
# Utilities
# ------------------------
def list_projects():
    items = []
    for p in sorted(PROJECTS_DIR.glob("*")):
        if not p.is_dir():
            continue
        meta = p / "project.json"
        info = {"name": p.name, "repo": None, "created": None}
        if meta.exists():
            try:
                info.update(json.loads(meta.read_text()))
            except Exception:
                pass
        info["cloned"] = (p / "linux").exists()
        items.append(info)
    return items


# ------------------------
# Routes
# ------------------------
@app.get("/")
def home():
    rows = []
    for prj in list_projects():
        name = prj["name"]
        status = STATE.get(name, {}).get("status", "ready" if prj["cloned"] else "idle")
        badge = {
            "idle":    "<span class='badge b-idle'>IDLE</span>",
            "cloning": "<span class='badge b-cloning'>CLONING</span>",
            "ready":   "<span class='badge b-ready'>READY</span>",
            "error":   "<span class='badge b-error'>ERROR</span>",
        }.get(status, "<span class='badge b-idle'>IDLE</span>")
        rows.append(
            "<tr>"
            f"<td><a href='/project/{name}'><b>{name}</b></a></td>"
            f"<td class='mono'>{prj.get('repo','')}</td>"
            f"<td class='dim'>{prj.get('created','')}</td>"
            f"<td>{badge}</td>"
            "</tr>"
        )

    body = f"""
    <div class='card'>
      <h2>Create Project</h2>
      <form class='mt12' method='POST' action='/create_project'>
        <label>Project Name</label>
        <input name='name' type='text' placeholder='e.g., qgenie-demo' required />
        <div class='row mt12'>
          <label>Repository:</label>
          <select name='repo'>
            <option value='linux'>linux (Linus)</option>
            <option value='linux-next'>linux-next</option>
          </select>
          <button type='submit'>Create</button>
        </div>
      </form>
    </div>
    <div class='card'>
      <h2>Projects</h2>
      <table>
        <thead><tr><th>Name</th><th>Repo</th><th>Created</th><th>Status</th></tr></thead>
        <tbody>{''.join(rows) if rows else "<tr><td colspan=4 class=dim>No projects</td></tr>"}</tbody>
      </table>
    </div>
    """
    return render(body)


@app.post("/create_project")
def create_project():
    name = (request.form.get("name") or "").strip()
    repo_key = (request.form.get("repo") or "linux").strip()
    if not name:
        return render("<div class='card'>Name is required</div>")
    if any(c in name for c in "/\\ "):
        return render("<div class='card'>Name must not contain spaces or slashes</div>")
    if repo_key not in REPOS:
        return render("<div class='card'>Invalid repo</div>")
    proj_dir = PROJECTS_DIR / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name,
        "repo": repo_key,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    (proj_dir / "project.json").write_text(json.dumps(meta, indent=2))
    return redirect(f"/project/{name}")


@app.get("/project/<name>")
def project_page(name):
    proj_dir = PROJECTS_DIR / name
    meta = json.loads((proj_dir / "project.json").read_text()) if (proj_dir / "project.json").exists() else {}
    cloned = (proj_dir / "linux").exists()
    repo_key = meta.get("repo", "linux")
    repo_url = REPOS.get(repo_key, "")
    base = (proj_dir / "linux" / "arch" / "arm64" / "boot" / "dts" / "qcom")
    files = []
    if base.exists():
        files = sorted([f.name for f in base.iterdir() if f.suffix in (".dts", ".dtsi")])

    # Button triggers async clone; progress bar + tail logs poll /api/clone_status/<name>
    body = f"""
    <div class='card'>
      <a href='/'>&larr; Back</a>
      <span class='right'><span class='mono dim'>URL: {repo_url}</span></span>
      <h2 class='mt8'>Project: <span class='mono'>{name}</span></h2>
      <div class='dim mt8'>Repo: <span class='mono'>{repo_key}</span></div>
      <div class='mt16'>
        <button id="cloneBtn" onclick="startClone()" {'class="secondary" disabled' if cloned else ''}>
          {'Re-clone' if cloned else 'Clone now'}
        </button>
      </div>
    </div>

    <div class='card'>
      <h3>DTS/DTSI Browser</h3>
      <div class='dim'>Base path (qcom): <span class='mono'>{base}</span></div>
      <div class='mt12'>
        <select id='dts' style='width:100%; background:#0b1220; color:#e2e8f0; border:1px solid #334155; border-radius:8px; padding:10px'>
          {''.join([f"<option>{x}</option>" for x in files])}
        </select>
      </div>
      <div class='row mt12'>
        <a class='button' href='/download_zip/{name}'><button>Download DTS bundle (zip)</button></a>
        <a class='button' href='/api/files?project={name}'><button class='secondary'>List via API</button></a>
      </div>
    </div>

    <div id="progressBox" class="card" style="display:none;">
      <h3>Clone Progress</h3>
      <div class="dim">Status: <span id="status">starting...</span> &middot; <span id="pct">0%</span></div>
      <div style="height:10px;background:#223046;border-radius:6px;overflow:hidden;margin-top:6px;">
        <div id="bar" style="height:10px;background:#22c55e;width:0%"></div>
      </div>
      <pre id="log" style="background:#0b1220;border:1px solid #334155;border-radius:8px;padding:10px;max-height:300px;overflow:auto;margin-top:10px;"></pre>
    </div>

    <script>
      async function startClone(){{
        const btn = document.getElementById('cloneBtn');
        btn.disabled = true;
        document.getElementById('progressBox').style.display = 'block';
        document.getElementById('status').textContent = 'cloning';
        try {{
          await fetch('/clone/{name}/start', {{ method: 'POST' }});
          pollClone();
        }} catch(e) {{
          document.getElementById('status').textContent = 'error';
        }}
      }}

      async function pollClone(){{
        const r = await fetch('/api/clone_status/{name}');
        const j = await r.json();
        const pct = j.percent || 0;
        document.getElementById('pct').textContent = pct + '%';
        document.getElementById('bar').style.width = pct + '%';
        document.getElementById('status').textContent = j.status || 'cloning';
        document.getElementById('log').textContent = (j.tail || []).join('');
        if (j.status === 'cloning') {{
          setTimeout(pollClone, 700);
        }} else if (j.status === 'ready') {{
          // reload to show newly scanned DTS files
          location.reload();
        }} else if (j.status === 'error') {{
          // keep the log visible for debugging
        }} else {{
          // default - poll a bit more if needed
          setTimeout(pollClone, 700);
        }}
      }}
    </script>
    """
    return render(body)


# Start async clone (returns immediately)
@app.post("/clone/<name>/start")
def clone_start(name):
    meta_path = (PROJECTS_DIR / name / "project.json")
    if not meta_path.exists():
        return jsonify({"error": "Project not found"}), 404
    meta = json.loads(meta_path.read_text())
    repo_key = meta.get("repo", "linux")
    repo_url = REPOS.get(repo_key)
    t = threading.Thread(target=_run_clone, args=(name, repo_url), daemon=True)
    t.start()
    return jsonify({"status": "started"})


# Poll clone status and return tail of log
@app.get("/api/clone_status/<name>")
def clone_status(name):
    s = STATE.get(name, {"status": "idle", "percent": 0, "log": ""})
    tail_lines = []
    log_path = s.get("log")
    if log_path and os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                tail_lines = lines[-200:]
        except Exception:
            tail_lines = []
    return jsonify({
        "status": s.get("status", "idle"),
        "percent": s.get("percent", 0),
        "tail": tail_lines
    })


# List DTS/DTSI under qcom/
@app.get("/api/files")
def api_files():
    name = request.args.get("project")
    if not name:
        return jsonify({"error": "project required"}), 400
    proj_dir = PROJECTS_DIR / name
    base = proj_dir / "linux" / "arch" / "arm64" / "boot" / "dts" / "qcom"
    files = []
    if base.exists():
        files = sorted([f.name for f in base.iterdir() if f.suffix in (".dts", ".dtsi")])
    return jsonify({
        "project": name,
        "base_path": str(base),
        "count": len(files),
        "files": files,
    })


# Download all DTS/DTSI as zip
@app.get("/download_zip/<name>")
def download_zip(name):
    proj_dir = PROJECTS_DIR / name
    base = proj_dir / "linux" / "arch" / "arm64" / "boot" / "dts" / "qcom"
    if not base.exists():
        return render("<div class='card'>DTS base not found. Clone first.</div>")
    out_zip = proj_dir / f"{name}-qcom-dts.zip"
    if out_zip.exists():
        out_zip.unlink()
    import zipfile
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(base.iterdir()):
            if p.suffix in (".dts", ".dtsi"):
                z.write(p, arcname=p.name)
    return send_file(out_zip, as_attachment=True)


@app.get("/favicon.ico")
def favicon():
    return ('', 204)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=APP_PORT)
