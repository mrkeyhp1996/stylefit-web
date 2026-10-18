import os
import re
import sys
import time
import uuid
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import yt_dlp
from fastapi import HTTPException

# Cấu hình logging
logger = logging.getLogger("media_downloader")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _fh = logging.FileHandler(Path(__file__).resolve().parent / "downloader.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_fh)

BASE_DIR = Path(__file__).resolve().parent
TEMP_DOWNLOADS_DIR = BASE_DIR / "temp_downloads"
TEMP_DOWNLOADS_DIR.mkdir(exist_ok=True)

# Giới hạn thời lượng: 90 phút (5400 giây)
MAX_DURATION_SECONDS = 90 * 60

# Giới hạn xử lý đồng thời tối đa 3 tác vụ để bảo vệ CPU Mini PC & Pi Node
download_semaphore = asyncio.Semaphore(3)

# Danh sách domain được hỗ trợ
SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be",
    "soundcloud.com", "on.soundcloud.com",
    "facebook.com", "fb.watch", "fb.com"
]

def sanitize_filename(name: str) -> str:
    """Loại bỏ các ký tự không hợp lệ cho tên file trên Windows và HTTP header."""
    # Thay thế các ký tự đặc biệt hay gặp trên Facebook Reels / bài đăng
    clean = name.replace("｜", "-").replace("|", "-")
    clean = re.sub(r'[\\/*?:"<>|\n\r\t]', " ", clean)
    # Loại bỏ emoji và ký tự Unicode mở rộng gây lỗi filesystem Windows
    clean = re.sub(r'[\U00010000-\U0010ffff\uD800-\uDBFF\uDC00-\uDFFF\u2600-\u26FF\u2700-\u27BF]', "", clean)
    clean = re.sub(r'\s+', " ", clean).strip()
    return clean[:60] if clean else "StyleFit_Download"

def format_duration(seconds: Optional[int]) -> str:
    """Định dạng giây thành mm:ss hoặc hh:mm:ss"""
    if not seconds:
        return "N/A"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def detect_platform(url: str) -> str:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "soundcloud.com" in u or "on.soundcloud.com" in u:
        return "soundcloud"
    if "facebook.com" in u or "fb.watch" in u or "fb.com" in u:
        return "facebook"
    return "unknown"

def validate_url(url: str):
    if not url or not isinstance(url, str):
        raise HTTPException(status_code=400, detail="Vui lòng nhập đường link hợp lệ.")
    url = url.strip()
    platform = detect_platform(url)
    if platform == "unknown":
        raise HTTPException(
            status_code=400,
            detail="Nền tảng chưa được hỗ trợ. Vui lòng dán link từ YouTube, Facebook hoặc SoundCloud."
        )
    return url, platform

def extract_media_info_sync(url: str, platform: str) -> Dict[str, Any]:
    """Trích xuất thông tin nhanh không tải file (mất ~1-2s)."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False,
        'noplaylist': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError("Không thể lấy dữ liệu từ link này.")

            # Nếu là playlist, lấy video đầu tiên
            if "entries" in info:
                entries = [e for e in info.get("entries", []) if e]
                if not entries:
                    raise HTTPException(status_code=400, detail="Danh sách phát rỗng hoặc không tìm thấy bài hát nào.")
                info = entries[0]

            # Kiểm tra nếu là livestream đang phát trực tiếp
            is_live = info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming")
            if is_live:
                raise HTTPException(
                    status_code=400,
                    detail="Không thể tải video đang phát trực tiếp (Livestream). Vui lòng chọn video đã kết thúc phát sóng!"
                )

            duration = info.get("duration", 0) or 0
            if duration > MAX_DURATION_SECONDS:
                mins = round(duration / 60, 1)
                raise HTTPException(
                    status_code=400,
                    detail=f"Thời lượng video/bài hát là {mins} phút, vượt quá giới hạn tối đa 90 phút của hệ thống."
                )

            title = info.get("title", "Bài hát / Video")
            uploader = info.get("uploader") or info.get("channel") or info.get("artist") or "Tác giả"
            thumbnail = info.get("thumbnail") or ""
            
            # Phân loại định dạng có thể tải
            formats = info.get("formats", [])
            max_height = 0
            max_width = 0
            has_video = False
            has_hd = False
            for f in formats:
                h = f.get("height")
                w = f.get("width")
                if h and isinstance(h, int) and h > max_height:
                    max_height = h
                if w and isinstance(w, int) and w > max_width:
                    max_width = w
                if f.get("vcodec") and f.get("vcodec") != "none":
                    has_video = True
                if f.get("format_id") in ("sd", "hd"):
                    has_video = True
                if f.get("format_id") == "hd":
                    has_hd = True

            effective_max = max(max_height, max_width)

            audio_options = [
                {
                    "format_id": "audio_320",
                    "label": "MP3 - 320 kbps",
                    "sublabel": "Chuẩn phòng tập / Âm thanh sắc nét nhất",
                    "type": "audio",
                    "ext": "mp3",
                    "badge": "KHUYÊN DÙNG"
                },
                {
                    "format_id": "audio_128",
                    "label": "MP3 - 128 kbps",
                    "sublabel": "Tiết kiệm dung lượng bộ nhớ",
                    "type": "audio",
                    "ext": "mp3",
                    "badge": "TIẾT KIỆM"
                },
                {
                    "format_id": "audio_m4a",
                    "label": "M4A / AAC",
                    "sublabel": "Chuẩn tối ưu cho thiết bị Apple iOS",
                    "type": "audio",
                    "ext": "m4a",
                    "badge": ""
                }
            ]

            video_options = []
            if platform in ("youtube", "facebook") and (has_video or effective_max > 0):
                if effective_max >= 1080:
                    video_options.append({
                        "format_id": "video_1080",
                        "label": "MP4 - 1080p Full HD",
                        "sublabel": "Hình ảnh siêu nét, mượt mà",
                        "type": "video",
                        "ext": "mp4",
                        "badge": "FULL HD"
                    })
                if effective_max >= 720 or has_hd:
                    video_options.append({
                        "format_id": "video_720",
                        "label": "MP4 - 720p HD",
                        "sublabel": "Chuẩn xem mượt trên mọi điện thoại",
                        "type": "video",
                        "ext": "mp4",
                        "badge": "PHỔ BIẾN"
                    })
                video_options.append({
                    "format_id": "video_360",
                    "label": "MP4 - 360p",
                    "sublabel": "Dung lượng siêu nhẹ, tải nhanh",
                    "type": "video",
                    "ext": "mp4",
                    "badge": ""
                })

            return {
                "ok": True,
                "url": url,
                "platform": platform,
                "title": title,
                "uploader": uploader,
                "thumbnail": thumbnail,
                "duration": duration,
                "duration_formatted": format_duration(duration),
                "audio_options": audio_options,
                "video_options": video_options
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi extract info cho {url}: {e}")
        err_msg = str(e)
        err_lower = err_msg.lower()
        if any(k in err_lower for k in ("private", "sign in", "login", "members-only")):
            raise HTTPException(status_code=400, detail="Video hoặc bài hát này ở chế độ riêng tư, cần đăng nhập hoặc dành cho hội viên.")
        if any(k in err_lower for k in ("unavailable", "not found", "404", "does not exist", "isn't available")):
            raise HTTPException(status_code=400, detail="Không tìm thấy nội dung hoặc đường link đã bị xóa / không còn tồn tại trên nền tảng.")
        if any(k in err_lower for k in ("unsupported url", "invalid url", "no media")):
            raise HTTPException(status_code=400, detail="Đường link không đúng định dạng hoặc không có media hợp lệ.")
        clean_err = re.sub(r'^(ERROR:\s*)+', '', err_msg).strip()
        raise HTTPException(status_code=400, detail=f"Không thể phân tích liên kết: {clean_err[:150]}")


async def get_media_info(url: str) -> Dict[str, Any]:
    clean_url, platform = validate_url(url)
    return await asyncio.to_thread(extract_media_info_sync, clean_url, platform)


def download_media_sync(url: str, format_id: str) -> tuple[Path, str, str]:
    """Tải và chuyển đổi file sang định dạng yêu cầu (chạy trong worker thread)."""
    clean_url, platform = validate_url(url)
    task_id = f"sf_{uuid.uuid4().hex[:10]}"
    output_dir = TEMP_DOWNLOADS_DIR / task_id
    output_dir.mkdir(parents=True, exist_ok=True)

    common_opts = {
        'paths': {'home': str(output_dir)},
        'outtmpl': {'default': 'media.%(ext)s'},
        'windowsfilenames': True,
        'restrictfilenames': True,
        'trim_file_name': 50,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }

    # Cấu hình yt-dlp theo từng định dạng
    if format_id == "audio_320":
        ydl_opts = {
            **common_opts,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
        }
        media_type = "audio/mpeg"
        final_ext = "mp3"

    elif format_id == "audio_128":
        ydl_opts = {
            **common_opts,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
        }
        media_type = "audio/mpeg"
        final_ext = "mp3"

    elif format_id == "audio_m4a":
        ydl_opts = {
            **common_opts,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
            }],
        }
        media_type = "audio/mp4"
        final_ext = "m4a"

    elif format_id == "video_1080":
        ydl_opts = {
            **common_opts,
            'format': 'bestvideo[height<=1080]+bestaudio/bestvideo[width<=1080]+bestaudio/hd/best',
            'merge_output_format': 'mp4',
        }
        media_type = "video/mp4"
        final_ext = "mp4"

    elif format_id == "video_720":
        ydl_opts = {
            **common_opts,
            'format': 'bestvideo[height<=720]+bestaudio/bestvideo[width<=720]+bestaudio/hd/best',
            'merge_output_format': 'mp4',
        }
        media_type = "video/mp4"
        final_ext = "mp4"

    elif format_id == "video_360":
        ydl_opts = {
            **common_opts,
            'format': 'bestvideo[height<=360]+bestaudio/bestvideo[width<=360]+bestaudio/sd/best[height<=360]/best[width<=360]/best',
            'merge_output_format': 'mp4',
        }
        media_type = "video/mp4"
        final_ext = "mp4"

    else:
        raise HTTPException(status_code=400, detail="Định dạng yêu cầu không hợp lệ.")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            raw_title = info.get("title", "StyleFit_Download")

        # Tìm file đã xuất hiện trong thư mục tạm
        created_files = list(output_dir.glob(f"*.{final_ext}"))
        if not created_files:
            # Tìm file bất kỳ nếu đuôi khác
            created_files = [f for f in output_dir.iterdir() if f.is_file()]

        if not created_files:
            raise RuntimeError("Quá trình xuất file không tạo ra tệp kết quả.")

        target_file = created_files[0]
        safe_name = sanitize_filename(raw_title) + f".{final_ext}"
        return target_file, safe_name, media_type

    except Exception as e:
        shutil.rmtree(output_dir, ignore_errors=True)
        logger.error(f"Lỗi tải file {clean_url} dạng {format_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Không thể tải media: {str(e)[:200]}")


async def download_media(url: str, format_id: str) -> tuple[Path, str, str]:
    """Giới hạn tối đa 3 tác vụ tải đồng thời để bảo vệ Mini PC."""
    try:
        cleanup_temp_downloads()
    except Exception:
        pass
    async with download_semaphore:
        return await asyncio.to_thread(download_media_sync, url, format_id)


def cleanup_temp_downloads():
    """Xóa các thư mục tạm tải về nếu đã tồn tại quá 15 phút."""
    now = time.time()
    for item in TEMP_DOWNLOADS_DIR.iterdir():
        try:
            if now - item.stat().st_mtime > 900:  # 15 phút
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
        except Exception:
            pass
