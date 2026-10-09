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
import numpy as np
from scipy import signal

SR = 8000


def decode_audio(path, sr=SR):
    """Decode any media file to mono float32 at `sr` using ffmpeg with maximum multi-thread speed."""
    cmd = ["ffmpeg", "-v", "error", "-threads", "0", "-i", str(path), "-vn", "-sn", "-ac", "1",
           "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError("Không đọc được âm thanh: " + out.stderr.decode(errors="ignore")[:200])
    return np.frombuffer(out.stdout, dtype=np.float32).copy()


def _prep(x, sr=SR, beta=0.7):
    """Band-pass (music body) then partial spectral whitening (robust to room reverb/speaker EQ)."""
    sos = signal.butter(4, [120, 3400], btype="band", fs=sr, output="sos")
    x = signal.sosfiltfilt(sos, x)
    x = x - np.mean(x)
    return x


def _norm_xcorr(a, b, sr=SR, min_overlap_s=6.0, beta=0.7):
    """
    Full-range normalised cross-correlation of a (dance) against b (original).
    lag L (samples) means a[t] ~ b[t - L].  Returns lags (samples) and score array.
    """
    n, m = len(a), len(b)
    nfft = 1 << int(np.ceil(np.log2(n + m)))
    A = np.fft.rfft(a, nfft)
    B = np.fft.rfft(b, nfft)
    R = A * np.conj(B)
    # partial PHAT weighting: |R|^-beta
    R = R / (np.abs(R) ** beta + 1e-9)
    cc = np.fft.irfft(R, nfft)

    lags = np.arange(-(m - 1), n)
    cc = np.concatenate((cc[nfft - (m - 1):], cc[:n]))  # index aligned with lags

    # normalise by overlap energy so long overlaps don't win by size alone
    ca = np.concatenate(([0.0], np.cumsum(a * a)))
    cb = np.concatenate(([0.0], np.cumsum(b * b)))
    a0 = np.maximum(0, lags)
    a1 = np.minimum(n, m + lags)
    b0 = a0 - lags
    b1 = a1 - lags
    overlap = a1 - a0
    valid = overlap >= int(min_overlap_s * sr)
    ea = ca[np.clip(a1, 0, n)] - ca[np.clip(a0, 0, n)]
    eb = cb[np.clip(b1, 0, m)] - cb[np.clip(b0, 0, m)]
    # Energy floor: windows that are (nearly) silent must not win just because we divide by ~0.
    ea = ea + 0.25 * (ca[-1] / max(n, 1)) * overlap
    eb = eb + 0.25 * (cb[-1] / max(m, 1)) * overlap
    score = np.full(len(lags), -np.inf)
    score[valid] = cc[valid] / (np.sqrt(ea[valid] * eb[valid]) + 1e-9) * np.sqrt(overlap[valid])
    return lags, score


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


def find_offset(dance_path, original_path, sr=SR):
    """Return dict(offset_ms, confidence, drift_ms, dance_peaks, original_peaks...)."""
    dance_raw = decode_audio(dance_path, sr)
    orig_raw = decode_audio(original_path, sr)
    dance = _prep(dance_raw, sr)
    orig = _prep(orig_raw, sr)

    lags, score = _norm_xcorr(dance, orig, sr)
    best = int(np.argmax(score))
    best_lag = int(lags[best])

    # confidence: main peak vs best peak that is > 150 ms away
    guard = int(0.15 * sr)
    mask = np.abs(lags - best_lag) > guard
    second = float(np.max(score[mask & np.isfinite(score)])) if np.any(mask & np.isfinite(score)) else 0.0
    peak = float(score[best])
    ratio = peak / (second + 1e-9)

    # quadratic refine around the peak (sub-sample)
    if 0 < best < len(score) - 1 and np.isfinite(score[best - 1]) and np.isfinite(score[best + 1]):
        y0, y1, y2 = score[best - 1], score[best], score[best + 1]
        den = (y0 - 2 * y1 + y2)
        frac = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    else:
        frac = 0.0
    offset_ms = (best_lag + frac) / sr * 1000.0

    # drift check: re-measure offset locally on a 20s window near the start & near the end of the overlap
    drift_ms = None
    try:
        drift_ms = _drift(dance, orig, best_lag, sr)
    except Exception:
        pass

    if ratio >= 1.35:
        level = "high"
    elif ratio >= 1.15:
        level = "medium"
    else:
        level = "low"

    return {
        "offset_ms": round(offset_ms, 1),
        "confidence_ratio": round(ratio, 2),
        "confidence_level": level,
        "drift_ms": None if drift_ms is None else round(drift_ms, 1),
        "dance_duration": round(len(dance) / sr, 2),
        "original_duration": round(len(orig) / sr, 2),
        "dance_peaks": extract_peaks(dance_raw, 500),
        "original_peaks": extract_peaks(orig_raw, 500),
    }


def _local_lag(a, b, a_start, win, expected_lag, search, sr):
    """Locally estimate lag around expected_lag for dance window [a_start, a_start+win)."""
    seg = a[a_start:a_start + win]
    b_start = a_start - expected_lag - search
    b_end = a_start + win - expected_lag + search
    pad_l = max(0, -b_start)
    b_seg = b[max(0, b_start):min(len(b), b_end)]
    if len(b_seg) < win or len(seg) < win:
        return None
    n = len(seg) + len(b_seg)
    nfft = 1 << int(np.ceil(np.log2(n)))
    cc = np.fft.irfft(np.fft.rfft(seg, nfft) * np.conj(np.fft.rfft(b_seg, nfft)), nfft)
    cc = np.concatenate((cc[nfft - (len(b_seg) - 1):], cc[:len(seg)]))
    lags = np.arange(-(len(b_seg) - 1), len(seg))
    k = int(np.argmax(cc))
    # lag relative: seg[t] ~ b_seg[t - l]; global lag = l + (a_start - b_global_start)
    b_glob_start = max(0, b_start)
    return int(lags[k]) + (a_start - b_glob_start) - 0  # global lag in samples


def _drift(a, b, lag, sr, win_s=18, search_s=0.4):
    win = int(win_s * sr)
    search = int(search_s * sr)
    n, m = len(a), len(b)
    lo = max(0, lag)
    hi = min(n, m + lag)
    if hi - lo < win * 2 + sr:
        return None
    l1 = _local_lag(a, b, lo + sr, win, lag, search, sr)
    l2 = _local_lag(a, b, hi - win - sr, win, lag, search, sr)
    if l1 is None or l2 is None:
        return None
    return (l2 - l1) / sr * 1000.0
