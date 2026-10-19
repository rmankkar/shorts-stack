{\rtf1\ansi\ansicpg1252\cocoartf2870
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 import json\
import os\
import re\
import subprocess\
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\
from pathlib import Path\
\
SCRIPTS = Path("/opt/shorts-scripts")\
JOBS = Path("/data/jobs")\
PYTHON = "/opt/shorts-venv/bin/python"\
\
OPERATIONS = \{\
    "/voice": [PYTHON, str(SCRIPTS / "make_voice.py")],\
    "/captions": [PYTHON, str(SCRIPTS / "make_srt.py")],\
    "/render": ["bash", str(SCRIPTS / "render_short.sh")],\
\}\
\
class Handler(BaseHTTPRequestHandler):\
    def send_json(self, status, data):\
        body = json.dumps(data).encode()\
        self.send_response(status)\
        self.send_header("Content-Type", "application/json")\
        self.send_header("Content-Length", str(len(body)))\
        self.end_headers()\
        self.wfile.write(body)\
\
    def do_GET(self):\
        if self.path == "/health":\
            return self.send_json(200, \{"status": "ok", "service": "shorts-worker"\})\
        return self.send_json(404, \{"error": "Unknown endpoint"\})\
\
    def do_POST(self):\
        operation = OPERATIONS.get(self.path)\
        if not operation:\
            return self.send_json(404, \{"error": "Unknown operation"\})\
\
        try:\
            length = int(self.headers.get("Content-Length", "0"))\
            payload = json.loads(self.rfile.read(length) or b"\{\}")\
            job = payload.get("job", "test")\
\
            if not isinstance(job, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", job):\
                return self.send_json(400, \{"error": "Invalid job name"\})\
\
            job_dir = JOBS / job\
            if not job_dir.is_dir():\
                return self.send_json(400, \{"error": f"Job folder not found: \{job\}"\})\
\
            script = Path(operation[-1])\
            if not script.is_file():\
                return self.send_json(500, \{"error": f"Script not found: \{script.name\}"\})\
\
            result = subprocess.run(\
                operation + [str(job_dir)],\
                cwd=str(job_dir),\
                capture_output=True,\
                text=True,\
                timeout=600,\
                check=False,\
            )\
\
            return self.send_json(\
                200 if result.returncode == 0 else 500,\
                \{\
                    "success": result.returncode == 0,\
                    "operation": self.path,\
                    "job": job,\
                    "return_code": result.returncode,\
                    "stdout": result.stdout[-8000:],\
                    "stderr": result.stderr[-8000:],\
                \},\
            )\
        except subprocess.TimeoutExpired:\
            return self.send_json(504, \{"error": "Operation timed out after 10 minutes"\})\
        except Exception as exc:\
            return self.send_json(500, \{"error": str(exc)\})\
\
    def log_message(self, fmt, *args):\
        print(fmt % args, flush=True)\
\
server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("WORKER_PORT", "8000"))), Handler)\
print("Shorts worker listening on port 8000", flush=True)\
server.serve_forever()}