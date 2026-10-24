"""
StyleFit sync finder.

Convention (used everywhere, UI + server):
    offset_ms > 0  -> the original music must START `offset_ms` AFTER the beginning
                      of the dance video (dance video has extra lead-in before the music).
    offset_ms < 0  -> the original music must be TRIMMED by |offset_ms| from its start
                      (original has extra lead-in the dance video does not contain).

i.e. dance[t] ~= original[t - offset].
"""
import subprocess
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from scipy import signal

SR = 8000


def decode_audio(path, sr=SR):
    """Decode any media file to mono float32 at `sr` using ffmpeg with maximum multi-thread speed."""
    cmd = ["ffmpeg", "-v", "error", "-threads", "0", "-i", str(path), "-vn", "-sn", "-ac", "1",
           "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True)
    # If ffmpeg returned non-zero due to truncated end, but still decoded at least 2 seconds of audio, keep it!
    if not out.stdout or (out.returncode != 0 and len(out.stdout) < sr * 4 * 2):
        err_msg = out.stderr.decode(errors="replace")[:200]
        raise RuntimeError(f"Không đọc được âm thanh: {err_msg}")
    return np.frombuffer(out.stdout, dtype=np.float32).copy()


def _prep(x, sr=SR):
    """Band-pass (music body) filter robust to phone mic room reverb & EQ."""
    sos = signal.butter(4, [120, 3200], btype="band", fs=sr, output="sos")
    x = signal.sosfiltfilt(sos, x)
    x = x - np.mean(x)
    return x


def extract_peaks(samples, num_bins=500):
    """Compute normalized peak amplitudes (0.0 to 1.0) for visual waveform display."""
    if len(samples) == 0:
        return [0.0] * num_bins
    bin_size = len(samples) // num_bins
    if bin_size == 0:
        return [round(float(abs(s)), 3) for s in samples[:num_bins]]
    matrix = np.abs(samples[:num_bins * bin_size]).reshape((num_bins, bin_size))
    peaks = np.max(matrix, axis=1)
    m = float(np.max(peaks)) if np.max(peaks) > 0 else 1.0
    return [round(float(p / m), 3) for p in peaks]


def _safe_local_lag(a, b, a_start, win, expected_lag, search):
    """Locally estimate lag around expected_lag for dance window [a_start, a_start+win)."""
    seg = a[a_start:a_start + win]
    b_start = a_start - expected_lag - search
    b_end = a_start + win - expected_lag + search
    if b_start < 0 or b_end > len(b):
        return None
    b_seg = b[b_start:b_end]
    if len(b_seg) < win + search:
        return None
    nfft = 1 << int(np.ceil(np.log2(len(seg) + len(b_seg))))
    S = np.fft.rfft(seg, nfft)
    B = np.fft.rfft(b_seg, nfft)
    R = S * np.conj(B)
    R_phat = R / (np.abs(R)**0.5 + 1e-9)
    cc = np.fft.irfft(R_phat, nfft)
    lags = np.arange(-(len(b_seg) - 1), len(seg))
    cc = np.concatenate((cc[nfft - (len(b_seg) - 1):], cc[:len(seg)]))
    k = int(np.argmax(cc))
    rel_lag = int(lags[k])
    return expected_lag + search + rel_lag


def _drift(a, b, lag, sr, win_s=12, search_s=0.3):
    win = int(win_s * sr)
    search = int(search_s * sr)
    n, m = len(a), len(b)
    lo = max(0, lag)
    hi = min(n, m + lag)
    if hi - lo < win * 2 + sr:
        return None
    l1 = _safe_local_lag(a, b, lo + sr, win, lag, search)
    l2 = _safe_local_lag(a, b, hi - win - sr, win, lag, search)
    if l1 is None or l2 is None:
        return None
    return float((l2 - l1) / sr * 1000.0)


def find_offset(dance_path, original_path, sr=SR):
    """
    Robust multi-feature audio synchronizer for dance videos in gym environments.
    Combines:
      1) Partial-whitened bandpass cross-correlation (fine acoustic detail)
      2) Rhythmic low-frequency envelope correlation (tempo/drums, reverb-immune)
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_dance = pool.submit(decode_audio, dance_path, sr)
        f_orig  = pool.submit(decode_audio, original_path, sr)
        dance_raw = f_dance.result()
        orig_raw  = f_orig.result()

    # 1. Bandpass filter 120 - 3200 Hz
    dance_band = _prep(dance_raw, sr)
    orig_band  = _prep(orig_raw, sr)

    n, m = len(dance_band), len(orig_band)
    nfft = 1 << int(np.ceil(np.log2(n + m)))
    D_band = np.fft.rfft(dance_band, nfft)
    O_band = np.fft.rfft(orig_band, nfft)
    R_band = D_band * np.conj(O_band)

    # Partial PHAT whitening (beta = 0.5)
    R_phat = R_band / (np.abs(R_band)**0.5 + 1e-9)
    cc_band = np.fft.irfft(R_phat, nfft)
    lags = np.arange(-(m - 1), n)
    cc_band = np.concatenate((cc_band[nfft - (m - 1):], cc_band[:n]))

    # Overlap bounds
    a0 = np.maximum(0, lags)
    a1 = np.minimum(n, m + lags)
    overlap = a1 - a0
    min_overlap = max(6.0 * sr, min(n, m) * 0.20)
    valid = overlap >= min_overlap

    # Overlap weighting so small boundary edge slivers cannot falsely beat full-clip overlap
    overlap_weight = (overlap[valid] / min(n, m)) ** 0.5
    score_band = np.full(len(lags), -np.inf)
    score_band[valid] = cc_band[valid] * overlap_weight

    # 2. Rhythmic energy envelope correlation (15 Hz lowpass)
    sos_lp = signal.butter(3, 15.0, btype="low", fs=sr, output="sos")
    dance_env = signal.sosfiltfilt(sos_lp, np.abs(dance_band))
    orig_env  = signal.sosfiltfilt(sos_lp, np.abs(orig_band))
    dance_env = (dance_env - np.mean(dance_env)) / (np.std(dance_env) + 1e-9)
    orig_env  = (orig_env - np.mean(orig_env)) / (np.std(orig_env) + 1e-9)

    D_env = np.fft.rfft(dance_env, nfft)
    O_env = np.fft.rfft(orig_env, nfft)
    cc_env = np.fft.irfft(D_env * np.conj(O_env), nfft)
    cc_env = np.concatenate((cc_env[nfft - (m - 1):], cc_env[:n]))

    score_env = np.full(len(lags), -np.inf)
    score_env[valid] = (cc_env[valid] / np.sqrt(n * m)) * overlap_weight

    # Standardize and fuse scores
    s_std = float(np.std(score_band[valid])) + 1e-9
    e_std = float(np.std(score_env[valid])) + 1e-9
    score_band_norm = (score_band - float(np.mean(score_band[valid]))) / s_std
    score_env_norm  = (score_env - float(np.mean(score_env[valid]))) / e_std

    combined = np.full(len(lags), -np.inf)
    combined[valid] = score_band_norm[valid] * 0.6 + score_env_norm[valid] * 0.4

    best = int(np.argmax(combined))
    best_lag = int(lags[best])

    # Guard window (400ms) to ensure adjacent dance beat does not count as competing peak
    guard = int(0.4 * sr)
    mask = np.abs(lags - best_lag) > guard
    second_idx = int(np.argmax(combined[mask & valid]))
    peak = float(combined[best])
    second = float(combined[mask & valid][second_idx]) if np.any(mask & valid) else 0.0
    ratio = float(peak / (second + 1e-9))

    max_env_r = float(np.max(score_env[valid]))
    peak_zscore = float(score_band_norm[best])

    # Sub-sample refinement via quadratic interpolation
    if 0 < best < len(combined) - 1 and np.isfinite(combined[best - 1]) and np.isfinite(combined[best + 1]):
        y0, y1, y2 = combined[best - 1], combined[best], combined[best + 1]
        den = (y0 - 2 * y1 + y2)
        frac = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    else:
        frac = 0.0
    offset_ms = float((best_lag + frac) / sr * 1000.0)

    # Drift check
    drift_ms = None
    try:
        drift_ms = _drift(dance_band, orig_band, best_lag, sr)
    except Exception:
        pass

    # True Headphones Mode detection:
    # ONLY trigger if the audio correlation is completely flat noise across all lags
    # (i.e. zero speaker music in the room, dancer wore earbuds)
    is_headphones = bool(max_env_r < 0.12 and ratio < 1.15 and peak_zscore < 3.5)
    if is_headphones:
        level = "headphones"
    elif ratio >= 1.35 and max_env_r >= 0.20:
        level = "high"
    elif ratio >= 1.18 or max_env_r >= 0.18:
        level = "medium"
    else:
        level = "low"

    return {
        "offset_ms": round(offset_ms, 1),
        "raw_offset_ms": round(offset_ms, 1),
        "confidence_ratio": round(ratio, 2),
        "confidence_level": level,
        "is_headphones": is_headphones,
        "drift_ms": None if drift_ms is None else round(drift_ms, 1),
        "dance_duration": round(float(len(dance_raw) / sr), 2),
        "original_duration": round(float(len(orig_raw) / sr), 2),
        "dance_peaks": extract_peaks(dance_raw, 500),
        "original_peaks": extract_peaks(orig_raw, 500),
    }
