import os
import sys
import re
import time
import uuid
import shutil
import asyncio
import subprocess
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent

if sys.stdout is None:
    try:
        sys.stdout = open(BASE_DIR / "server.log", "a", encoding="utf-8", buffering=1)
    except Exception:
        pass

if sys.stderr is None:
    try:
        sys.stderr = open(BASE_DIR / "server.log", "a", encoding="utf-8", buffering=1)
    except Exception:
        pass

try:
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel
from urllib.parse import quote

from syncfinder import find_offset
from media_downloader import get_media_info, download_media, cleanup_temp_downloads

BASE_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = BASE_DIR / "exports"
UPLOADS_DIR = BASE_DIR / "uploads"
EXPORTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

KEEP_SECONDS = 2 * 3600  # delete user files after 2 hours (privacy + disk)
BLOCKED_PREFIXES = ("/uploads", "/server.py", "/syncfinder.py", "/.git", "/__pycache__")

# High-performance encoding (CPU i5 12 threads)
LOW_PRIORITY = 0

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
    try:
        cleanup_temp_downloads()
    except Exception:
        pass


def run_ffmpeg(args):
    cmd = ["ffmpeg", "-y", "-threads", "0", "-v", "error"] + args
    print("FFMPEG:", " ".join(cmd))
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
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


@app.get("/api/upload_status")
async def upload_status(sessionId: str, fileType: str):
    """Check already uploaded chunks to support resumable uploads."""
    if not sessionId.isalnum() or fileType not in ("goc", "nhay"):
        raise HTTPException(status_code=400, detail="Thông số không hợp lệ")
    sdir = UPLOADS_DIR / sessionId
    if not sdir.exists():
        return {"completed": False, "uploadedChunks": []}
    
    # Check if final file already assembled
    for f in sdir.glob(f"{fileType}.*"):
        if f.is_file():
            return {"completed": True, "uploadedChunks": []}
            
    chunks_dir = sdir / f"chunks_{fileType}"
    if not chunks_dir.exists():
        return {"completed": False, "uploadedChunks": []}
        
    parts = []
    for p in chunks_dir.glob("*.part"):
        try:
            parts.append(int(p.stem))
        except ValueError:
            pass
    return {"completed": False, "uploadedChunks": sorted(parts)}


@app.post("/api/upload_chunk")
async def upload_chunk(
    sessionId: str = Form(...),
    fileType: str = Form(...),
    fileName: str = Form(...),
    chunkIndex: int = Form(...),
    totalChunks: int = Form(...),
    chunk: UploadFile = File(...)
):
    """
    Receive 10MB file chunk to bypass Cloudflare 100MB body limit safely on mobile networks.
    Reassembles into the final goc/nhay file once all chunks arrive.
    """
    if not sessionId.isalnum():
        raise HTTPException(status_code=400, detail="sessionId không hợp lệ")
    if fileType not in ("goc", "nhay"):
        raise HTTPException(status_code=400, detail="fileType không hợp lệ")

    sdir = UPLOADS_DIR / sessionId
    sdir.mkdir(parents=True, exist_ok=True)

    # If final assembled file already exists, return completed immediately
    for f in sdir.glob(f"{fileType}.*"):
        if f.is_file():
            return {
                "ok": True,
                "done": True,
                "fileType": fileType,
                "chunkIndex": chunkIndex,
                "totalChunks": totalChunks,
                "size": f.stat().st_size
            }

    chunks_dir = sdir / f"chunks_{fileType}"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    part_file = chunks_dir / f"{chunkIndex:05d}.part"
    with open(part_file, "wb") as f:
        while content := await chunk.read(1024 * 1024):
            f.write(content)

    parts = sorted(list(chunks_dir.glob("*.part")))
    if len(parts) == totalChunks:
        ext = Path(fileName).suffix or (".mp3" if fileType == "goc" else ".mp4")
        if ext.lower() not in [".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".webm"]:
            ext = ".mp4" if fileType == "nhay" else ".mp3"
        dest_file = sdir / f"{fileType}{ext}"

        if not dest_file.exists():
            def _assemble():
                if dest_file.exists():
                    return
                with open(dest_file, "wb") as outfile:
                    for p in parts:
                        if p.exists():
                            with open(p, "rb") as infile:
                                shutil.copyfileobj(infile, outfile)
                shutil.rmtree(chunks_dir, ignore_errors=True)

            await asyncio.to_thread(_assemble)

        if dest_file.exists():
            return {
                "ok": True,
                "done": True,
                "fileType": fileType,
                "chunkIndex": chunkIndex,
                "totalChunks": totalChunks,
                "size": dest_file.stat().st_size
            }

    return {
        "ok": True,
        "done": False,
        "fileType": fileType,
        "chunkIndex": chunkIndex,
        "totalChunks": totalChunks
    }


@app.post("/api/analyze")
async def analyze(
    sessionId: Optional[str] = Form(None),
    fileGoc: Optional[UploadFile] = File(None),
    fileNhay: Optional[UploadFile] = File(None)
):
    """
    Analyze dance and music audio offset.
    Supports either pre-uploaded chunks (via sessionId) or direct files (<15MB).
    Returns offset, drift, video metadata, and 500 visual waveform peaks.
    """
    asyncio.create_task(asyncio.to_thread(cleanup_old_files))

    if sessionId and sessionId.isalnum():
        sid = sessionId
        sdir = UPLOADS_DIR / sid
        if not sdir.exists():
            raise HTTPException(status_code=404, detail="Phiên làm việc không tồn tại hoặc đã hết hạn.")
        goc_path = next(iter(sdir.glob("goc.*")), None)
        nhay_path = next(iter(sdir.glob("nhay.*")), None)
        if not goc_path or not nhay_path:
            raise HTTPException(status_code=400, detail="Chưa nhận đủ file nhạc gốc và video nhảy.")
    elif fileGoc and fileNhay:
        sid = uuid.uuid4().hex[:12]
        sdir = UPLOADS_DIR / sid
        sdir.mkdir(parents=True, exist_ok=True)
        ext_g = Path(fileGoc.filename or "goc.mp4").suffix or ".mp4"
        ext_n = Path(fileNhay.filename or "nhay.mp4").suffix or ".mp4"
        goc_path = sdir / f"goc{ext_g}"
        nhay_path = sdir / f"nhay{ext_n}"
        await save_upload(fileGoc, goc_path)
        await save_upload(fileNhay, nhay_path)
    else:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp file hoặc sessionId hợp lệ.")

    try:
        r = await asyncio.to_thread(find_offset, nhay_path, goc_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    video_meta = await asyncio.to_thread(probe_video, nhay_path)

    return {
        "sessionId": sid,
        "offsetMs": r["offset_ms"],
        "rawOffsetMs": r.get("raw_offset_ms"),
        "confidenceLevel": r["confidence_level"],
        "confidenceRatio": r["confidence_ratio"],
        "isHeadphones": r.get("is_headphones", False),
        "driftMs": r["drift_ms"],
        "danceDuration": r["dance_duration"],
        "originalDuration": r["original_duration"],
        "dancePeaks": r.get("dance_peaks"),
        "originalPeaks": r.get("original_peaks"),
        "videoMeta": video_meta,
    }


def assemble_smart_partial(parts, dest_path):
    """
    Assembles a partial MP4 file from head parts and optional tail part (where moov atom resides).
    If moov atom is in tail, shifts stco/co64 entries by moov_size so FFmpeg can decode audio seamlessly!
    """
    head_parts = [p for p in parts if int(p.stem) < 5]
    tail_parts = [p for p in parts if int(p.stem) >= 5]
    tail_p = tail_parts[-1] if tail_parts else None

    head_bytes = bytearray()
    for p in head_parts:
        if p.exists():
            with open(p, "rb") as f:
                head_bytes.extend(f.read())

    if tail_p and tail_p.exists():
        with open(tail_p, "rb") as f:
            tail_bytes = f.read()

        moov_idx = tail_bytes.rfind(b"moov")
        if moov_idx >= 4:
            moov_start = moov_idx - 4
            moov_size = int.from_bytes(tail_bytes[moov_start:moov_start+4], "big")
            moov_bytes = tail_bytes[moov_start:moov_start+moov_size]

            if len(moov_bytes) >= 8 and len(head_bytes) >= 16:
                ftyp_size = int.from_bytes(head_bytes[0:4], "big")
                offset = ftyp_size
                if len(head_bytes) > offset + 8 and head_bytes[offset+4:offset+8] == b"wide":
                    offset += int.from_bytes(head_bytes[offset:offset+4], "big")

                shift = moov_size
                moov_arr = bytearray(moov_bytes)

                # Adjust 32-bit chunk offsets (stco)
                p_idx = 0
                while True:
                    pos = moov_arr.find(b"stco", p_idx)
                    if pos == -1:
                        break
                    entry_count = int.from_bytes(moov_arr[pos+8:pos+12], "big")
                    for i in range(entry_count):
                        e_pos = pos + 12 + i * 4
                        if e_pos + 4 <= len(moov_arr):
                            old_val = int.from_bytes(moov_arr[e_pos:e_pos+4], "big")
                            moov_arr[e_pos:e_pos+4] = (old_val + shift).to_bytes(4, "big")
                    p_idx = pos + 4

                # Adjust 64-bit chunk offsets (co64)
                p_idx = 0
                while True:
                    pos = moov_arr.find(b"co64", p_idx)
                    if pos == -1:
                        break
                    entry_count = int.from_bytes(moov_arr[pos+8:pos+12], "big")
                    for i in range(entry_count):
                        e_pos = pos + 12 + i * 8
                        if e_pos + 8 <= len(moov_arr):
                            old_val = int.from_bytes(moov_arr[e_pos:e_pos+8], "big")
                            moov_arr[e_pos:e_pos+8] = (old_val + shift).to_bytes(8, "big")
                    p_idx = pos + 4

                faststart_data = head_bytes[:offset] + moov_arr + head_bytes[offset:]
                with open(dest_path, "wb") as f:
                    f.write(faststart_data)
                return

    with open(dest_path, "wb") as f:
        f.write(head_bytes)


@app.post("/api/analyze_fast")
async def analyze_fast(sessionId: str = Form(...)):
    """
    Fast Sync: Analyzes offset using the first 15MB (up to 5 chunks) of the dance video + tail chunk (moov).
    Returns offset in 0.3-0.5s so user can enter Studio and hear preview immediately,
    while remaining chunks upload in background.
    """
    if not sessionId.isalnum():
        raise HTTPException(status_code=400, detail="sessionId không hợp lệ")

    sdir = UPLOADS_DIR / sessionId
    if not sdir.exists():
        raise HTTPException(status_code=404, detail="Phiên làm việc không tồn tại")

    goc_path = next(iter(sdir.glob("goc.*")), None)
    if not goc_path:
        raise HTTPException(status_code=400, detail="Chưa nhận được file nhạc gốc")

    # If full assembled file already exists
    nhay_path = next(iter(sdir.glob("nhay.*")), None)
    if nhay_path and nhay_path.is_file():
        r = await asyncio.to_thread(find_offset, nhay_path, goc_path)
        video_meta = await asyncio.to_thread(probe_video, nhay_path)
        return {
            "ok": True,
            "fastSync": False,
            "sessionId": sessionId,
            "offsetMs": r["offset_ms"],
            "rawOffsetMs": r.get("raw_offset_ms"),
            "confidenceLevel": r["confidence_level"],
            "confidenceRatio": r["confidence_ratio"],
            "isHeadphones": r.get("is_headphones", False),
            "dancePeaks": r.get("dance_peaks"),
            "originalPeaks": r.get("original_peaks"),
            "videoMeta": video_meta,
        }

    chunks_dir = sdir / "chunks_nhay"
    if not chunks_dir.exists():
        raise HTTPException(status_code=400, detail="Chưa có dữ liệu video")

    parts = sorted(list(chunks_dir.glob("*.part")))
    if len(parts) == 0:
        raise HTTPException(status_code=400, detail="Chưa có lát cắt video")

    temp_head = sdir / "temp_head.mov"
    await asyncio.to_thread(assemble_smart_partial, parts, temp_head)

    try:
        r = await asyncio.to_thread(find_offset, temp_head, goc_path)
        video_meta = await asyncio.to_thread(probe_video, temp_head)
        return {
            "ok": True,
            "fastSync": True,
            "sessionId": sessionId,
            "offsetMs": r["offset_ms"],
            "rawOffsetMs": r.get("raw_offset_ms"),
            "confidenceLevel": r["confidence_level"],
            "confidenceRatio": r["confidence_ratio"],
            "isHeadphones": r.get("is_headphones", False),
            "dancePeaks": r.get("dance_peaks"),
            "originalPeaks": r.get("original_peaks"),
            "videoMeta": video_meta,
        }
    except Exception as e:
        err_msg = str(e).encode('ascii', errors='replace').decode('ascii')
        print(f"Fast sync fallback needed: {err_msg}")
        return {"ok": False, "fallbackNeeded": True, "detail": err_msg}
    finally:
        if temp_head.exists():
            try:
                temp_head.unlink()
            except Exception:
                pass


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
        vmeta = await asyncio.to_thread(probe_video, nhay)
        w, h = vmeta.get("width", 0), vmeta.get("height", 0)
        if w == 1080 and h == 1920 and not is_trimmed:
            # Already 1080x1920 portrait and not trimmed -> stream copy (instant 0.2s)
            video_opts = ["-c:v", "copy"]
        elif w == 1080 and h == 1920 and is_trimmed:
            # Already 1080x1920 portrait -> re-encode frame-accurate without scaling filter (much faster)
            video_opts = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-tune", "fastdecode", "-pix_fmt", "yuv420p"]
        else:
            # Scale & pad to 1080x1920 portrait
            vf = "scale=1080:1920:force_original_aspect_ratio=decrease:flags=bicubic,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
            video_opts = ["-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-tune", "fastdecode", "-pix_fmt", "yuv420p"]
    elif is_trimmed:
        # Re-encode frame-accurate with ultrafast speed & pristine quality
        video_opts = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-tune", "fastdecode", "-pix_fmt", "yuv420p"]
    else:
        # Untrimmed stream copy (instant 0.2s)
        video_opts = ["-c:v", "copy"]

    args += ["-filter_complex", fc, "-map", "0:v:0", "-map", "[a]"] + video_opts
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]
    args += ["-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(out_path)]

    dur = await asyncio.to_thread(run_ffmpeg, args)
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


@app.get("/exports/{filename}")
async def get_export(filename: str, download: Optional[bool] = False):
    """
    Download or stream rendered video with byte-range and Content-Disposition support.
    download=True sends attachment header to prevent browser aborts on mobile / Cloudflare tunnel.
    """
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Tên file không hợp lệ")
    file_path = EXPORTS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File video không tồn tại hoặc đã hết hạn")

    disp = "attachment" if download else "inline"
    return FileResponse(
        path=str(file_path),
        filename=filename if download else None,
        media_type="video/mp4",
        content_disposition_type=disp,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600"
        }
    )


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """Direct forced-attachment download link."""
    return await get_export(filename, download=True)


class MediaInfoPayload(BaseModel):
    url: str


@app.post("/api/downloader/info")
async def api_downloader_info(payload: MediaInfoPayload):
    """Lấy thông tin và danh sách định dạng hỗ trợ tải cho video/bài hát."""
    return await get_media_info(payload.url)


@app.get("/api/downloader/download")
async def api_downloader_download(url: str, format_id: str):
    """Tải và chuyển đổi media, stream trực tiếp về máy khách hàng kèm header attachment."""
    file_path, filename, media_type = await download_media(url, format_id)

    def cleanup_task():
        try:
            if file_path.exists():
                file_path.unlink()
            parent = file_path.parent
            if parent.exists() and not any(parent.iterdir()):
                shutil.rmtree(parent, ignore_errors=True)
        except Exception:
            pass

    import unicodedata
    ascii_name = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii').strip()
    if not ascii_name:
        ascii_name = f"StyleFit_Download.{filename.split('.')[-1]}"
    quoted_name = quote(filename)

    return FileResponse(
        path=str(file_path),
        filename=ascii_name,
        media_type=media_type,
        content_disposition_type="attachment",
        background=BackgroundTask(cleanup_task),
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted_name}',
            "Cache-Control": "no-store, no-cache, must-revalidate",
        }
    )


# ==============================================================================
# STYLEFIT DROP - DIRECT HTTP FALLBACK & POLLING
# ==============================================================================
drop_rooms = {}  # room_id -> list of file records

@app.post("/api/drop/upload")
async def api_drop_upload(
    room: str = Form(...),
    sender_name: str = Form("Thiết bị đối tác"),
    file: UploadFile = File(...)
):
    """Fallback trực tiếp: Nhận file tải lên từ điện thoại khi WebRTC P2P không kết nối được."""
    try:
        room_clean = re.sub(r'[^a-zA-Z0-9_-]', '', room)
        safe_filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', file.filename or 'video.mp4')
        dest_filename = f"drop_{room_clean}_{int(time.time())}_{safe_filename}"
        dest_path = UPLOADS_DIR / dest_filename
        
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = dest_path.stat().st_size
        file_url = f"/api/drop/file/{dest_filename}"
        
        file_info = {
            "name": file.filename or safe_filename,
            "size": file_size,
            "url": file_url,
            "sender": sender_name,
            "timestamp": int(time.time())
        }
        
        if room_clean not in drop_rooms:
            drop_rooms[room_clean] = []
        drop_rooms[room_clean].append(file_info)
        
        if len(drop_rooms[room_clean]) > 50:
            drop_rooms[room_clean] = drop_rooms[room_clean][-50:]
            
        print(f"[StyleFit Drop] Received file {file_info['name']} ({file_size} bytes) for room {room_clean}")
        return JSONResponse({"status": "ok", "file": file_info})
    except Exception as e:
        print(f"[StyleFit Drop Error] api_drop_upload: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/api/drop/poll")
async def api_drop_poll(room: str, since: int = 0):
    """Polling lấy danh sách file nhận được cho room."""
    room_clean = re.sub(r'[^a-zA-Z0-9_-]', '', room)
    files = drop_rooms.get(room_clean, [])
    new_files = [f for f in files if f.get("timestamp", 0) > since]
    return JSONResponse({"status": "ok", "files": new_files, "server_time": int(time.time())})

@app.get("/api/drop/file/{filename}")
async def api_drop_file(filename: str):
    """Tải file drop đã nhận."""
    safe_name = Path(filename).name
    file_path = UPLOADS_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File không tồn tại")
    return FileResponse(path=str(file_path), filename=safe_name, media_type="application/octet-stream")


app.mount("/exports", StaticFiles(directory=str(EXPORTS_DIR)), name="exports")
app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8088)
