import os
import time
import uuid
import subprocess
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

BASE_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = BASE_DIR / "exports"
UPLOADS_DIR = BASE_DIR / "uploads"

EXPORTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="StyleFit Music Sync Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/render")
async def render_video(
    fileGoc: UploadFile = File(None),
    fileNhay: UploadFile = File(None),
    offsetMs: int = Form(260),
    musicVol: int = Form(100),
    roomVol: int = Form(0)
):
    try:
        req_id = uuid.uuid4().hex[:8]
        timestamp = int(time.time())
        out_filename = f"StyleFit_Synced_{req_id}_{timestamp}.mp4"
        out_path = EXPORTS_DIR / out_filename

        # If files are uploaded directly
        if fileGoc and fileNhay:
            goc_path = UPLOADS_DIR / f"goc_{req_id}_{fileGoc.filename}"
            nhay_path = UPLOADS_DIR / f"nhay_{req_id}_{fileNhay.filename}"

            with open(goc_path, "wb") as f:
                f.write(await fileGoc.read())
            with open(nhay_path, "wb") as f:
                f.write(await fileNhay.read())
        else:
            # Fallback to test video pair in system if testing
            goc_path = Path(r"C:\StyleFit-Test-Videos\cap1-goc.mp4")
            nhay_path = Path(r"C:\StyleFit-Test-Videos\cap1-nhay.mp4")

        # Audio filter construction based on offset and volumes
        # offsetMs = 260 means music delayed by 260ms to match dance moves
        abs_offset = abs(offsetMs)
        vol_music = musicVol / 100.0
        vol_room = roomVol / 100.0

        if roomVol > 0:
            # Mix room audio with music
            if offsetMs >= 0:
                audio_filter = (
                    f"[1:a]adelay={abs_offset}|{abs_offset},volume={vol_music}[m];"
                    f"[0:a]volume={vol_room}[r];"
                    f"[m][r]amix=inputs=2:duration=first[a]"
                )
            else:
                audio_filter = (
                    f"[1:a]atrim=start={abs_offset/1000.0},asetpts=PTS-STARTPTS,volume={vol_music}[m];"
                    f"[0:a]volume={vol_room}[r];"
                    f"[m][r]amix=inputs=2:duration=first[a]"
                )
            cmd = (
                f'ffmpeg -y -i "{nhay_path}" -i "{goc_path}" '
                f'-filter_complex "{audio_filter}" -map 0:v:0 -map "[a]" '
                f'-c:v copy -c:a aac -b:a 192k -shortest "{out_path}"'
            )
        else:
            # Pure clean original music
            if offsetMs >= 0:
                cmd = (
                    f'ffmpeg -y -i "{nhay_path}" -i "{goc_path}" '
                    f'-map 0:v:0 -map 1:a:0 -c:v copy '
                    f'-af "adelay={abs_offset}|{abs_offset},volume={vol_music}" '
                    f'-c:a aac -b:a 192k -shortest "{out_path}"'
                )
            else:
                cmd = (
                    f'ffmpeg -y -i "{nhay_path}" -ss {abs_offset/1000.0} -i "{goc_path}" '
                    f'-map 0:v:0 -map 1:a:0 -c:v copy '
                    f'-af "volume={vol_music}" '
                    f'-c:a aac -b:a 192k -shortest "{out_path}"'
                )

        print(f"Executing: {cmd}")
        t0 = time.time()
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        dur = time.time() - t0

        if res.returncode != 0:
            print("FFmpeg error:", res.stderr)
            raise HTTPException(status_code=500, detail="Lỗi xử lý FFmpeg: " + res.stderr[:200])

        file_size = os.path.getsize(out_path)
        print(f"Rendered {out_filename} in {dur:.2f}s ({file_size} bytes)")

        return {
            "ok": True,
            "renderTimeSec": round(dur, 2),
            "fileSize": file_size,
            "offsetUsed": offsetMs,
            "downloadUrl": f"/exports/{out_filename}",
            "filename": out_filename
        }

    except Exception as e:
        print("API Error:", e)
        raise HTTPException(status_code=500, detail=str(e))

# Mount exports directory
app.mount("/exports", StaticFiles(directory=str(EXPORTS_DIR)), name="exports")

# Mount main web app static files
app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8088)
