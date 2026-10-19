import os
import json
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="YouTube Shorts Worker")

JOB_ROOT = Path("/data/jobs").resolve()
SCRIPTS = Path("/opt/shorts-scripts")
PYTHON = "/opt/shorts-venv/bin/python"


class JobRequest(BaseModel):
    job_id: str = "test"


def get_job_dir(job_id: str) -> Path:
    # Restrict job IDs to simple folder names.
    if not job_id or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for c in job_id
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid job_id. Use letters, numbers, underscores or hyphens.",
        )

    job_dir = (JOB_ROOT / job_id).resolve()

    if job_dir.parent != JOB_ROOT:
        raise HTTPException(status_code=400, detail="Invalid job directory")

    if not job_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Job directory does not exist: {job_dir}",
        )

    return job_dir

class PrepareRequest(BaseModel):
    job_id: str
    script: dict


@app.post("/prepare")
def prepare_job(request: PrepareRequest):
    job_id = request.job_id

    # Validate job ID to prevent unsafe directory paths
    if not job_id or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for c in job_id
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid job_id. Use letters, numbers, underscores or hyphens."
        )

    # Ensure the narration exists before creating the job
    narration = request.script.get("narration", "")
    if not isinstance(narration, str) or not narration.strip():
        raise HTTPException(
            status_code=400,
            detail="The script must contain a non-empty narration field."
        )

    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    job_dir = JOB_ROOT / job_id

    # Do not overwrite an existing job
    try:
        job_dir.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        raise HTTPException(
            status_code=409,
            detail=f"Job already exists: {job_id}"
        )

    script_file = job_dir / "script.json"

    try:
        with script_file.open("w", encoding="utf-8") as f:
            json.dump(request.script, f, ensure_ascii=False, indent=2)
    except Exception:
        # Remove a partially created job if writing fails
        import shutil
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail="Could not save script.json."
        )

    return {
        "success": True,
        "job_id": job_id,
        "script_path": str(script_file)
    }

@app.post("/visuals")
def generate_visuals(request: JobRequest):
    job_dir = get_job_dir(request.job_id)
    script = SCRIPTS / "make_visuals.py"

    if not script.is_file():
        raise HTTPException(
            status_code=500,
            detail="make_visuals.py is missing"
        )

    return run_script(
        [PYTHON, str(script), str(job_dir)],
        job_dir
    )

def run_script(command: list[str], job_dir: Path) -> dict:
    try:
        result = subprocess.run(
            command,
            cwd=str(job_dir),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="The video-generation step exceeded 10 minutes.",
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Worker step failed",
                "return_code": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
            },
        )

    return {
        "success": True,
        "job_id": job_dir.name,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "shorts-worker"}


@app.post("/voice")
def generate_voice(request: JobRequest):
    job_dir = get_job_dir(request.job_id)
    script = SCRIPTS / "make_voice.py"

    if not script.is_file():
        raise HTTPException(status_code=500, detail="make_voice.py is missing")

    return run_script([PYTHON, str(script), str(job_dir)], job_dir)


@app.post("/captions")
def generate_captions(request: JobRequest):
    job_dir = get_job_dir(request.job_id)
    script = SCRIPTS / "make_srt.py"

    if not script.is_file():
        raise HTTPException(status_code=500, detail="make_srt.py is missing")

    return run_script([PYTHON, str(script), str(job_dir)], job_dir)


@app.post("/render")
def render_short(request: JobRequest):
    job_dir = get_job_dir(request.job_id)
    script = SCRIPTS / "render_short.sh"

    if not script.is_file():
        raise HTTPException(status_code=500, detail="render_short.sh is missing")

    return run_script(["bash", str(script), str(job_dir)], job_dir)
