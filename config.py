# config.py
import os
from pathlib import Path

class Config:
    # Use current directory as base, fallback to 'work' folder locally
    BASE_DIR = Path(os.getcwd())
    WORK_DIR = Path(os.environ.get("WORK_DIR", BASE_DIR / "work")).resolve()
    
    PROJECTS_DIR = WORK_DIR / "projects"
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    
    REPOS = {
        "linux": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git",
    }