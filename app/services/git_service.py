import shutil
import subprocess
import threading
import re
from pathlib import Path

# In-memory state storage
STATE = {}

def get_state(name):
    return STATE.get(name, {"status": "idle", "percent": 0, "log": ""})

def update_state(name, status, percent=0, log=""):
    STATE[name] = {"status": status, "percent": percent, "log": log}

def run_sparse_checkout(name, repo_url, projects_dir):
    proj_dir = Path(projects_dir) / name
    linux_dir = proj_dir / "linux"
    log_file = proj_dir / "clone.log"
    
    # Cleanup previous if exists and failed, or just update
    if not (linux_dir / ".git").exists():
        if linux_dir.exists(): shutil.rmtree(linux_dir)
        linux_dir.mkdir(parents=True, exist_ok=True)
        fresh = True
    else:
        fresh = False

    update_state(name, "cloning", 0, "Starting...")

    try:
        with open(log_file, "w") as lf:
            def run_git(args, msg=None):
                if msg: lf.write(f"\n> {msg}\n")
                subprocess.run(["git"] + args, cwd=linux_dir, stdout=lf, stderr=lf, check=True)

            if fresh:
                run_git(["init"], "Initializing Repo")
                run_git(["remote", "add", "origin", repo_url], "Adding Remote")
                run_git(["config", "core.sparseCheckout", "true"], "Configuring Sparse Checkout")
                
                # Write sparse checkout file
                sparse_path = linux_dir / ".git" / "info" / "sparse-checkout"
                sparse_path.parent.mkdir(parents=True, exist_ok=True)
                with open(sparse_path, "w") as f:
                    f.write("arch/arm64/boot/dts/qcom/\n")

            lf.write("\n> Fetching data...\n")
            
            # Run pull with progress capture
            process = subprocess.Popen(
                ["git", "pull", "--depth", "1", "origin", "master", "--progress"],
                cwd=linux_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            
            for line in process.stdout:
                lf.write(line)
                m = re.search(r'(\d{1,3})%', line)
                if m:
                    update_state(name, "cloning", int(m.group(1)), line.strip())
            
            process.wait()
            
            if process.returncode == 0:
                update_state(name, "ready", 100, "Ready")
            else:
                update_state(name, "error", 0, "Git Error")

    except Exception as e:
        update_state(name, "error", 0, str(e))

def start_clone_thread(name, repo_url, projects_dir):
    t = threading.Thread(target=run_sparse_checkout, args=(name, repo_url, projects_dir))
    t.start()
