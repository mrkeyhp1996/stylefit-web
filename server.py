import os
import time
import uuid
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from syncfinder import find_offset

BASE_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = BASE_DIR / "exports"
UPLOADS_DIR = BASE_DIR / "uploads"
EXPORTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

KEEP_SECONDS = 2 * 3600  # delete user files after 2 hours (privacy + disk)
BLOCKED_PREFIXES = ("/uploads", "/server.py", "/syncfinder.py", "/.git", "/__pycache__")

# Keep the mini PC responsive for other workloads (e.g. Pi Node): run ffmpeg at low priority.
LOW_PRIORITY = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)

app = FastAPI(title="StyleFit Music Sync Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def block_private_paths(request: Request, call_next):
    if request.url.path.startswith(BLOCKED_PREFIXES):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return await call_next(request)


def cleanup_old_files():
    now = time.time()
    for d in (UPLOADS_DIR, EXPORTS_DIR):
        for p in d.iterdir():
            try:
                if now - p.stat().st_mtime > KEEP_SECONDS:
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
            except Exception:
                pass


def run_ffmpeg(args):
    cmd = ["ffmpeg", "-y", "-v", "error"] + args
    print("FFMPEG:", " ".join(cmd))
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, creationflags=LOW_PRIORITY)
    if res.returncode != 0:
        print("FFmpeg error:", res.stderr)
        raise HTTPException(status_code=500, detail="Lỗi xử lý video: " + res.stderr[-300:])
    return time.time() - t0


async def save_upload(up: UploadFile, dest: Path):
    with open(dest, "wb") as f:
        while chunk := await up.read(1024 * 1024):
            f.write(chunk)


@app.post("/api/analyze")
async def analyze(fileGoc: UploadFile = File(...), fileNhay: UploadFile = File(...)):
    """Upload both videos once, find the offset over the WHOLE audio, keep files for render."""
    cleanup_old_files()
    sid = uuid.uuid4().hex[:12]
    sdir = UPLOADS_DIR / sid
    sdir.mkdir()
    ext_g = Path(fileGoc.filename or "goc.mp4").suffix or ".mp4"
    ext_n = Path(fileNhay.filename or "nhay.mp4").suffix or ".mp4"
    goc_path = sdir / f"goc{ext_g}"
    nhay_path = sdir / f"nhay{ext_n}"
    await save_upload(fileGoc, goc_path)
    await save_upload(fileNhay, nhay_path)

    try:
        r = find_offset(nhay_path, goc_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "sessionId": sid,
        "offsetMs": r["offset_ms"],
        "confidenceLevel": r["confidence_level"],
        "confidenceRatio": r["confidence_ratio"],
        "driftMs": r["drift_ms"],
        "danceDuration": r["dance_duration"],
        "originalDuration": r["original_duration"],
    }


@app.post("/api/render")
async def render_video(
    sessionId: str = Form(...),
    offsetMs: int = Form(...),
    musicVol: int = Form(100),
    roomVol: int = Form(0),
    trimLeadIn: int = Form(1),
):
    """
    offsetMs > 0 : music starts offsetMs AFTER the beginning of the dance video.
    offsetMs < 0 : music is trimmed by |offsetMs| from its beginning.
    trimLeadIn   : when offsetMs > 0, cut the dance video's lead-in so the output starts when the music starts.
    """
    if not sessionId.isalnum():
        raise HTTPException(status_code=400, detail="sessionId không hợp lệ")
    sdir = UPLOADS_DIR / sessionId
    goc = next(iter(sdir.glob("goc.*")), None) if sdir.exists() else None
    nhay = next(iter(sdir.glob("nhay.*")), None) if sdir.exists() else None
    if not goc or not nhay:
        raise HTTPException(status_code=404, detail="Phiên làm việc đã hết hạn. Hãy chọn lại video ở bước 1.")

    off = offsetMs / 1000.0
    vm = max(0, min(150, musicVol)) / 100.0
    vr = max(0, min(100, roomVol)) / 100.0
    out_name = f"StyleFit_Synced_{sessionId}_{int(time.time())}.mp4"
    out_path = EXPORTS_DIR / out_name

    trim_video = bool(trimLeadIn) and off > 0
    args = []
    if trim_video:
        # Output starts exactly when the music starts: cut the dance video's lead-in (accurate seek, re-encode video).
        args += ["-ss", f"{off:.3f}", "-i", str(nhay), "-i", str(goc)]
        music_chain = f"[1:a]volume={vm}"
        video_opts = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    elif off >= 0:
        args += ["-i", str(nhay), "-i", str(goc)]
        ms = int(round(off * 1000))
        music_chain = f"[1:a]adelay={ms}|{ms},volume={vm}"
        video_opts = ["-c:v", "copy"]
    else:
        args += ["-i", str(nhay), "-ss", f"{abs(off):.3f}", "-i", str(goc)]
        music_chain = f"[1:a]volume={vm}"
        video_opts = ["-c:v", "copy"]

    if vr > 0:
        fc = (f"{music_chain}[m];[0:a]volume={vr}[r];"
              f"[m][r]amix=inputs=2:duration=longest:normalize=0[a]")
    else:
        fc = f"{music_chain}[a]"

    args += ["-filter_complex", fc, "-map", "0:v:0", "-map", "[a]"] + video_opts + [
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out_path)]

    dur = run_ffmpeg(args)
    return {
        "ok": True,
        "renderTimeSec": round(dur, 2),
        "fileSize": os.path.getsize(out_path),
        "offsetUsed": offsetMs,
        "trimmedLeadIn": trim_video,
        "downloadUrl": f"/exports/{out_name}",
        "filename": out_name,
    }


app.mount("/exports", StaticFiles(directory=str(EXPORTS_DIR)), name="exports")
app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8088)
