import os
import time
import uuid
import shutil
import subprocess
from pathlib import Path
from typing import Optional

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


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    p = request.url.path
    if p.startswith("/api") or p.endswith((".js", ".css", ".html")) or p == "/":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


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


import json


def probe_video(path: Path):
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate:stream_side_data=rotation:stream_tags=rotate",
        "-of", "json", str(path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, creationflags=LOW_PRIORITY)
        data = json.loads(res.stdout)
        st = data.get("streams", [{}])[0]
        w = st.get("width", 0)
        h = st.get("height", 0)
        rot = 0
        if "side_data_list" in st:
            for sd in st["side_data_list"]:
                if "rotation" in sd:
                    rot = abs(int(sd["rotation"]))
        if rot == 0 and "tags" in st and "rotate" in st["tags"]:
            rot = abs(int(st["tags"]["rotate"]))
        if rot in (90, 270):
            w, h = h, w

        fps_str = st.get("r_frame_rate", "30/1")
        try:
            num, den = map(int, fps_str.split("/"))
            fps = round(num / den) if den else 30
        except Exception:
            fps = 30

        is_4k = (w >= 3840 or h >= 3840 or (w >= 2160 and h >= 3840) or (w >= 3840 and h >= 2160))
        is_1080p = (w >= 1080 and h >= 1920) or (w >= 1920 and h >= 1080)
        if is_4k:
            label = f"4K Ultra HD ({w}x{h}) · {fps}fps"
        elif is_1080p:
            label = f"Full HD 1080p ({w}x{h}) · {fps}fps"
        else:
            label = f"HD 720p ({w}x{h}) · {fps}fps"
        return {"width": w, "height": h, "fps": fps, "is4k": is_4k, "is1080p": is_1080p, "label": label}
    except Exception:
        return {"width": 1080, "height": 1920, "fps": 30, "is4k": False, "is1080p": True, "label": "Full HD 1080p"}


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

    video_meta = probe_video(nhay_path)

    return {
        "sessionId": sid,
        "offsetMs": r["offset_ms"],
        "confidenceLevel": r["confidence_level"],
        "confidenceRatio": r["confidence_ratio"],
        "driftMs": r["drift_ms"],
        "danceDuration": r["dance_duration"],
        "originalDuration": r["original_duration"],
        "videoMeta": video_meta,
    }


@app.post("/api/render")
async def render_video(
    sessionId: str = Form(...),
    offsetMs: int = Form(...),
    musicVol: int = Form(100),
    roomVol: int = Form(0),
    trimLeadIn: int = Form(1),
    trimStart: Optional[float] = Form(None),
    trimEnd: Optional[float] = Form(None),
    resolutionMode: str = Form("original"),  # "original" | "tiktok_1080p"
):
    """
    Render synced video with optional lead-in & outro trim and resolution mode.
    offsetMs > 0 : music starts offsetMs AFTER beginning of uncut dance video.
    trimStart    : start cut timestamp (seconds) in dance video timeline.
    trimEnd      : end cut timestamp (seconds) in dance video timeline.
    resolutionMode: 'tiktok_1080p' (Lanczos upscale + unsharp filter) or 'original'.
    """
    if not sessionId.isalnum():
        raise HTTPException(status_code=400, detail="sessionId không hợp lệ")
    sdir = UPLOADS_DIR / sessionId
    goc = next(iter(sdir.glob("goc.*")), None) if sdir.exists() else None
    nhay = next(iter(sdir.glob("nhay.*")), None) if sdir.exists() else None
    if not goc or not nhay:
        raise HTTPException(status_code=404, detail="Phiên làm việc đã hết hạn hoặc file đã bị xóa. Hãy quay lại bước 1 và chọn lại video.")

    off = offsetMs / 1000.0
    vm = max(0, min(150, musicVol)) / 100.0
    vr = max(0, min(100, roomVol)) / 100.0
    out_name = f"StyleFit_Synced_{sessionId}_{int(time.time())}.mp4"
    out_path = EXPORTS_DIR / out_name

    # Determine start cut (in dance video timeline)
    if trimStart is not None:
        trim_start = max(0.0, float(trimStart))
    elif bool(trimLeadIn) and off > 0:
        trim_start = off
    else:
        trim_start = 0.0

    # Determine end cut & duration
    trim_end = float(trimEnd) if trimEnd is not None and float(trimEnd) > trim_start else None
    duration = (trim_end - trim_start) if trim_end is not None else None

    # Audio alignment math:
    # In uncut dance video, original music position is (t - off).
    # At trimmed dance start (t = trim_start), original music position is (trim_start - off).
    music_seek = trim_start - off
    args = []

    # Dance video input
    if trim_start > 0:
        args += ["-ss", f"{trim_start:.3f}"]
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]
    args += ["-i", str(nhay)]

    # Music input
    if music_seek >= 0:
        if music_seek > 0.001:
            args += ["-ss", f"{music_seek:.3f}"]
        if duration is not None:
            args += ["-t", f"{duration:.3f}"]
        args += ["-i", str(goc)]
        music_chain = f"[1:a]volume={vm}"
    else:
        delay_ms = int(round(abs(music_seek) * 1000))
        if duration is not None:
            args += ["-t", f"{duration:.3f}"]
        args += ["-i", str(goc)]
        music_chain = f"[1:a]adelay={delay_ms}|{delay_ms},volume={vm}"

    # Audio mixing filter
    if vr > 0:
        fc = (f"{music_chain}[m];[0:a]volume={vr}[r];"
              f"[m][r]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        fc = f"{music_chain}[a]"

    # Video filters & encoding
    is_trimmed = (trim_start > 0) or (duration is not None)
    if resolutionMode == "tiktok_1080p":
        # Professional 1080x1920 portrait upscale with Lanczos filter and unsharp sharpening
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,unsharp=5:5:0.8:3:3:0.4"
        video_opts = ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p"]
    elif is_trimmed:
        # Re-encode is required for frame-accurate sub-second trimming
        video_opts = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    else:
        # Untrimmed stream copy
        video_opts = ["-c:v", "copy"]

    args += ["-filter_complex", fc, "-map", "0:v:0", "-map", "[a]"] + video_opts
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]
    args += ["-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(out_path)]

    dur = run_ffmpeg(args)
    return {
        "ok": True,
        "renderTimeSec": round(dur, 2),
        "fileSize": os.path.getsize(out_path),
        "offsetUsed": offsetMs,
        "trimStartUsed": round(trim_start, 3),
        "trimEndUsed": round(trim_end, 3) if trim_end is not None else None,
        "durationSec": round(duration, 2) if duration is not None else None,
        "resolutionMode": resolutionMode,
        "downloadUrl": f"/exports/{out_name}",
        "filename": out_name,
    }


@app.post("/api/lead")
async def register_lead(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    branch = data.get("branch") or "Thiên Lôi"
    session_time = data.get("time") or "Ca Chiều / Tối"
    goal = data.get("goal") or "Giảm mỡ & Học nhảy Step Dance"

    if not name or not phone:
        raise HTTPException(status_code=400, detail="Vui lòng nhập họ tên và số điện thoại")

    lead_entry = {
        "id": str(uuid.uuid4())[:8],
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "name": name,
        "phone": phone,
        "branch": branch,
        "sessionTime": session_time,
        "goal": goal,
    }

    leads_file = BASE_DIR / "leads.json"
    leads = []
    if leads_file.exists():
        try:
            leads = json.loads(leads_file.read_text(encoding="utf-8"))
        except Exception:
            leads = []
    leads.insert(0, lead_entry)
    leads_file.write_text(json.dumps(leads, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "message": f"Cảm ơn {name}! StyleFit đã nhận thông tin và sẽ gọi tư vấn trong 15 phút.",
    }


app.mount("/exports", StaticFiles(directory=str(EXPORTS_DIR)), name="exports")
app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8088)
