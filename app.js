/**
 * STYLEFIT MUSIC SYNC - APP CONTROLLER
 * Orchestrates UI, Web Audio Preview, Waveform Canvas, and Export Pipeline
 */

// Application State
const state = {
  fileGoc: null,
  fileNhay: null,
  bufferGoc: null,
  bufferNhay: null,
  urlNhayVideo: null,
  autoOffsetMs: 0,
  currentOffsetMs: 0,
  confidence: 0,
  gocWave: null,
  nhayWave: null,
  isPlaying: false,
  audioSourceNode: null,
  audioGainGoc: null,
  audioGainNhay: null,
  syncEngine: new StyleFitSyncEngine(),
  exportBlob: null,
  sessionId: null,
  danceDuration: 0,
  originalDuration: 0,
  trimStartSec: 0,
  trimEndSec: 0,
  resolutionMode: 'tiktok_1080p',
  trimPreviewTimer: null
};

// DOM Elements
const el = {
  inAppBanner: document.getElementById('inAppBanner'),
  step1: document.getElementById('step1'),
  step2: document.getElementById('step2'),
  step3: document.getElementById('step3'),
  stepNav1: document.getElementById('stepNavItem1'),
  stepNav2: document.getElementById('stepNavItem2'),
  stepNav3: document.getElementById('stepNavItem3'),
  
  dropGoc: document.getElementById('dropGoc'),
  dropNhay: document.getElementById('dropNhay'),
  inputGoc: document.getElementById('inputGoc'),
  inputNhay: document.getElementById('inputNhay'),
  dropContentGoc: document.getElementById('dropContentGoc'),
  dropContentNhay: document.getElementById('dropContentNhay'),
  previewGoc: document.getElementById('previewGoc'),
  previewNhay: document.getElementById('previewNhay'),
  fileNameGoc: document.getElementById('fileNameGoc'),
  fileNameNhay: document.getElementById('fileNameNhay'),
  fileMetaGoc: document.getElementById('fileMetaGoc'),
  fileMetaNhay: document.getElementById('fileMetaNhay'),
  btnStartAnalysis: document.getElementById('btnStartAnalysis'),

  statusIcon: document.getElementById('statusIcon'),
  statusTitle: document.getElementById('statusTitle'),
  statusDesc: document.getElementById('statusDesc'),
  confidenceBadge: document.getElementById('confidenceBadge'),

  waveformCanvas: document.getElementById('waveformCanvas'),
  playhead: document.getElementById('playhead'),
  offsetInput: document.getElementById('offsetInput'),

  previewVideo: document.getElementById('previewVideo'),
  btnOverlayPlay: document.getElementById('btnOverlayPlay'),
  btnPlayPause: document.getElementById('btnPlayPause'),
  playIcon: document.getElementById('playIcon'),
  playText: document.getElementById('playText'),
  currentTimeText: document.getElementById('currentTimeText'),
  durationTimeText: document.getElementById('durationTimeText'),
  musicVolume: document.getElementById('musicVolume'),
  roomVolume: document.getElementById('roomVolume'),
  musicVolText: document.getElementById('musicVolText'),
  roomVolText: document.getElementById('roomVolText'),

  // Trimming Card elements
  trimCard: document.getElementById('trimCard'),
  trimStartToggle: document.getElementById('trimStartToggle'),
  trimStartHint: document.getElementById('trimStartHint'),
  trimStartControls: document.getElementById('trimStartControls'),
  trimStartInput: document.getElementById('trimStartInput'),
  trimEndToggle: document.getElementById('trimEndToggle'),
  trimEndHint: document.getElementById('trimEndHint'),
  trimEndControls: document.getElementById('trimEndControls'),
  trimEndInput: document.getElementById('trimEndInput'),
  trimSummaryTitle: document.getElementById('trimSummaryTitle'),
  trimSummaryDur: document.getElementById('trimSummaryDur'),
  trimSummaryBadges: document.getElementById('trimSummaryBadges'),

  // Resolution mode elements
  resCardTiktok: document.getElementById('resCardTiktok'),
  resCardOriginal: document.getElementById('resCardOriginal'),
  detectedVideoBadge: document.getElementById('detectedVideoBadge'),
  resTitleOriginal: document.getElementById('resTitleOriginal'),
  resDescOriginal: document.getElementById('resDescOriginal'),
  badgeOriginalMaster: document.getElementById('badgeOriginalMaster'),

  // Step 3 Export elements
  exportProgressBox: document.getElementById('exportProgressBox'),
  exportResultBox: document.getElementById('exportResultBox'),
  exportStatusTitle: document.getElementById('exportStatusTitle'),
  exportStatusDesc: document.getElementById('exportStatusDesc'),
  exportSpinner: document.getElementById('exportSpinner'),
  exportRetry: document.getElementById('exportRetry'),
  progressBarFill: document.getElementById('progressBarFill'),
  progressPctText: document.getElementById('progressPctText'),
  finalVideo: document.getElementById('finalVideo'),
  btnDownload: document.getElementById('btnDownload'),
  btnShare: document.getElementById('btnShare')
};

// ==========================================
// 1. INITIALIZATION & IN-APP DETECTION
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
  checkInAppBrowser();
  setupDragAndDrop();
  setupFileInputs();
  initCanvasResize();
});

function checkInAppBrowser() {
  const ua = navigator.userAgent || navigator.vendor || window.opera;
  const isInApp = /TikTok|musical_ly|FBAN|FBAV|Instagram|Zalo|Line/i.test(ua);
  if (isInApp && el.inAppBanner) {
    el.inAppBanner.classList.remove('hidden');
  }
}

function closeInAppBanner() {
  if (el.inAppBanner) el.inAppBanner.classList.add('hidden');
}

// ==========================================
// 2. FILE HANDLING & DRAG-AND-DROP
// ==========================================
function setupDragAndDrop() {
  ['Goc', 'Nhay'].forEach(type => {
    const dropZone = el['drop' + type];
    const fileInput = el['input' + type];

    ['dragenter', 'dragover'].forEach(name => {
      dropZone.addEventListener(name, (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach(name => {
      dropZone.addEventListener(name, (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
      });
    });

    dropZone.addEventListener('drop', (e) => {
      const files = e.dataTransfer.files;
      if (files && files.length > 0) {
        handleFileSelect(type, files[0]);
      }
    });
  });
}

function setupFileInputs() {
  el.inputGoc.addEventListener('change', (e) => {
    if (e.target.files.length > 0) handleFileSelect('Goc', e.target.files[0]);
  });
  el.inputNhay.addEventListener('change', (e) => {
    if (e.target.files.length > 0) handleFileSelect('Nhay', e.target.files[0]);
  });
}

function changeFile(type, event) {
  event.stopPropagation();
  el['input' + type].click();
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatSeconds(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
}

async function handleFileSelect(type, file) {
  state['file' + type] = file;
  
  el['fileName' + type].textContent = file.name;
  el['fileMeta' + type].textContent = `Đang đọc... · ${formatBytes(file.size)}`;
  el['dropContent' + type].classList.add('hidden');
  el['preview' + type].classList.remove('hidden');

  // If it is dance video, create URL for preview player
  if (type === 'Nhay') {
    if (state.urlNhayVideo) URL.revokeObjectURL(state.urlNhayVideo);
    state.urlNhayVideo = URL.createObjectURL(file);
    el.previewVideo.src = state.urlNhayVideo;
  }

  // Decode audio in background
  try {
    const buffer = await state.syncEngine.decodeFile(file);
    state['buffer' + type] = buffer;
    el['fileMeta' + type].textContent = `${formatSeconds(buffer.duration)} · ${formatBytes(file.size)}`;
  } catch (err) {
    console.warn(`Lỗi đọc audio track từ file ${type}:`, err);
    el['fileMeta' + type].textContent = `File hợp lệ · ${formatBytes(file.size)}`;
  }

  // Check if both files ready -> Auto start analysis without requiring button click!
  if (state.fileGoc && state.fileNhay) {
    el.btnStartAnalysis.disabled = false;
    el.btnStartAnalysis.innerHTML = '<span class="btn-icon">⚡</span><span>Đang Tự Động Phân Tích...</span>';
    // Automatically trigger analysis
    setTimeout(() => {
      startAnalysis();
    }, 400);
  }
}

// ==========================================
// 3. STEP TRANSITION & ANALYSIS
// ==========================================
async function startAnalysis() {
  if (!state.fileGoc || !state.fileNhay) return;

  // Switch to Step 2
  el.step1.classList.add('hidden');
  el.step2.classList.remove('hidden');
  el.stepNav1.classList.remove('active');
  el.stepNav1.classList.add('completed');
  el.stepNav2.classList.add('active');

  // LOCK Preview Player while calculating so user cannot play un-synced audio!
  el.btnPlayPause.disabled = true;
  el.btnPlayPause.style.opacity = '0.6';
  el.btnPlayPause.style.cursor = 'not-allowed';
  el.playIcon.textContent = '⏳';
  el.playText.textContent = 'Đang dò nhịp... (chờ 1-2s)';
  el.btnOverlayPlay.style.display = 'none';

  el.statusIcon.textContent = '⏳';
  el.statusTitle.textContent = 'Đang phân tích bước sóng & nhịp điệu...';
  el.statusDesc.textContent = 'Hệ thống đang trích xuất nhịp bass để tìm thời điểm khớp chuẩn xác...';
  el.confidenceBadge.textContent = 'Đang đo';
  el.confidenceBadge.className = 'status-badge';

  try {
    // Decode audio locally only for waveform + in-browser preview
    if (!state.bufferGoc) state.bufferGoc = await state.syncEngine.decodeFile(state.fileGoc);
    if (!state.bufferNhay) state.bufferNhay = await state.syncEngine.decodeFile(state.fileNhay);
    state.gocWave = state.syncEngine.extractWaveformPeaks(state.bufferGoc, 500);
    state.nhayWave = state.syncEngine.extractWaveformPeaks(state.bufferNhay, 500);

    // Real detection runs on the server over the WHOLE video (any lead-in length)
    el.statusDesc.textContent = 'Đang tải video lên máy chủ và dò toàn bộ video để tìm điểm nhạc bắt đầu...';
    const fd = new FormData();
    fd.append('fileGoc', state.fileGoc);
    fd.append('fileNhay', state.fileNhay);
    const resp = await fetch('/api/analyze', { method: 'POST', body: fd });
    if (!resp.ok) {
      let msg = resp.statusText;
      try { msg = (await resp.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    const r = await resp.json();

    state.sessionId = r.sessionId;
    state.autoOffsetMs = Math.round(r.offsetMs);
    state.currentOffsetMs = state.autoOffsetMs;
    state.confidence = r.confidenceLevel;
    state.danceDuration = Number(r.danceDuration) || (el.previewVideo.duration || 60);
    state.originalDuration = Number(r.originalDuration) || (state.bufferGoc ? state.bufferGoc.duration : 60);
    el.offsetInput.value = state.currentOffsetMs;

    // Initialize smart auto trimming for lead-in and outro
    initTrimControls();

    // Handle detected video resolution & fps from phone camera
    if (r.videoMeta) {
      state.videoMeta = r.videoMeta;
      if (el.detectedVideoBadge) {
        el.detectedVideoBadge.style.display = 'inline-flex';
        el.detectedVideoBadge.textContent = `📱 Camera: ${r.videoMeta.label}`;
      }
      if (r.videoMeta.is4k) {
        if (el.resTitleOriginal) el.resTitleOriginal.textContent = `Giữ Trọn 4K Ultra HD (${r.videoMeta.fps}fps) Gốc`;
        if (el.resDescOriginal) {
          el.resDescOriginal.textContent = `Giữ trọn vẹn 100% độ phân giải 4K đỉnh cao của iPhone (${r.videoMeta.width}x${r.videoMeta.height} · ${r.videoMeta.fps}fps). Không bị hạ bất kỳ pixel nào.`;
        }
        selectResolutionMode('original');
      } else if (r.videoMeta.is1080p) {
        if (el.resTitleOriginal) el.resTitleOriginal.textContent = `Giữ Nguyên Full HD 1080p (${r.videoMeta.fps}fps)`;
        selectResolutionMode('original');
      }
    }

    const secs = (Math.abs(state.currentOffsetMs) / 1000).toFixed(2);
    const where = state.currentOffsetMs >= 0
      ? `Nhạc bắt đầu ở giây thứ ${secs} của video bạn quay`
      : `Video gốc có ${secs}s đầu mà video của bạn không có`;

    if (r.confidenceLevel === 'high') {
      el.statusIcon.textContent = '🟢';
      el.statusTitle.textContent = `Đã tìm thấy điểm khớp: ${where}`;
      el.statusDesc.textContent = 'Hãy bấm "Nghe thử" để kiểm tra bằng tai. Có thể tinh chỉnh ±10ms nếu cần.';
      el.confidenceBadge.textContent = 'Độ tin cậy: Cao';
      el.confidenceBadge.className = 'status-badge success';
    } else if (r.confidenceLevel === 'medium') {
      el.statusIcon.textContent = '🟡';
      el.statusTitle.textContent = `Có thể khớp: ${where}`;
      el.statusDesc.textContent = 'Độ tin cậy trung bình (tiếng loa khá nhỏ/ồn). Hãy nghe thử kỹ và tinh chỉnh bằng các nút ±.';
      el.confidenceBadge.textContent = 'Độ tin cậy: Vừa';
      el.confidenceBadge.className = 'status-badge';
    } else {
      el.statusIcon.textContent = '🔴';
      el.statusTitle.textContent = 'Chưa chắc chắn — cần căn tay';
      el.statusDesc.textContent = 'Video nhảy có thể không thu được tiếng nhạc, hoặc 2 video khác bài. Hãy nghe thử và căn bằng các nút ±.';
      el.confidenceBadge.textContent = 'Độ tin cậy: Thấp';
      el.confidenceBadge.className = 'status-badge';
    }
    if (r.driftMs !== null && Math.abs(r.driftMs) > 80) {
      el.statusDesc.textContent += ` ⚠️ Nhạc trong video của bạn lệch dần ${Math.round(r.driftMs)}ms từ đầu đến cuối (có thể là bản nhạc nhanh/chậm hơn bản gốc).`;
    }

    renderWaveforms();
    setupPreviewDurations();

    // UNLOCK Preview Player - now safe to play synced video!
    el.btnPlayPause.disabled = false;
    el.btnPlayPause.style.opacity = '1';
    el.btnPlayPause.style.cursor = 'pointer';
    el.playIcon.textContent = '▶';
    el.playText.textContent = 'Nghe Thử Đồng Bộ';
    el.btnOverlayPlay.style.display = 'flex';

  } catch (err) {
    console.error('Lỗi phân tích sync:', err);
    state.sessionId = null;
    state.autoOffsetMs = 0;
    state.currentOffsetMs = 0;
    el.offsetInput.value = 0;
    el.statusIcon.textContent = '🔴';
    el.statusTitle.textContent = 'Không phân tích được tự động';
    el.statusDesc.textContent = String(err.message || err) + ' — Hãy quay lại bước 1 và thử lại.';
    el.confidenceBadge.textContent = 'Lỗi';
    el.confidenceBadge.className = 'status-badge';
    renderWaveforms();
    setupPreviewDurations();

    // UNLOCK in fallback state
    el.btnPlayPause.disabled = false;
    el.btnPlayPause.style.opacity = '1';
    el.btnPlayPause.style.cursor = 'pointer';
    el.playIcon.textContent = '▶';
    el.playText.textContent = 'Nghe Thử';
    el.btnOverlayPlay.style.display = 'flex';
  }
}

// ==========================================
// 4. WAVEFORM CANVAS RENDERING
// ==========================================
function initCanvasResize() {
  window.addEventListener('resize', () => {
    if (state.gocWave && !el.step2.classList.contains('hidden')) {
      renderWaveforms();
    }
  });
}

function renderWaveforms() {
  const canvas = el.waveformCanvas;
  const wrap = canvas.parentElement;
  canvas.width = wrap.clientWidth * window.devicePixelRatio;
  canvas.height = wrap.clientHeight * window.devicePixelRatio;

  const ctx = canvas.getContext('2d');
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;

  ctx.clearRect(0, 0, w, h);

  // Background grid lines
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
  ctx.lineWidth = 1;
  for (let x = 0; x < w; x += 50) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  ctx.beginPath();
  ctx.moveTo(0, h / 2);
  ctx.lineTo(w, h / 2);
  ctx.stroke();

  // Shared timeline: dance video starts at t=0, original music starts at t=offset.
  const nhayDur = state.bufferNhay ? state.bufferNhay.duration : 60;
  const gocDur = state.bufferGoc ? state.bufferGoc.duration : 60;
  const offSec = state.currentOffsetMs / 1000;
  const t0 = Math.min(0, offSec);
  const t1 = Math.max(nhayDur, offSec + gocDur);
  state.timeline = { t0, t1 };
  const px = (t) => ((t - t0) / (t1 - t0)) * w;

  // Wave 1: Original Music (Orange) - Top half, starts at t = offset
  if (state.gocWave) {
    ctx.fillStyle = '#FE7409';
    const bins = state.gocWave.length;
    const barWidth = Math.max(1, (gocDur / (t1 - t0)) * w / bins);
    for (let i = 0; i < bins; i++) {
      const barH = state.gocWave[i] * (h * 0.42);
      ctx.fillRect(px(offSec + (i / bins) * gocDur), (h / 2) - barH, Math.max(1, barWidth - 0.5), barH);
    }
  }

  // Wave 2: Dance video audio (Cyan) - Bottom half, starts at t = 0
  if (state.nhayWave) {
    ctx.fillStyle = '#00E5FF';
    const bins = state.nhayWave.length;
    const barWidth = Math.max(1, (nhayDur / (t1 - t0)) * w / bins);
    for (let i = 0; i < bins; i++) {
      const barH = state.nhayWave[i] * (h * 0.42);
      ctx.fillRect(px((i / bins) * nhayDur), h / 2, Math.max(1, barWidth - 0.5), barH);
    }
  }
}

// ==========================================
// 5. NUDGE & OFFSET ADJUSTMENTS
// ==========================================
function adjustOffset(deltaMs) {
  state.currentOffsetMs += deltaMs;
  el.offsetInput.value = state.currentOffsetMs;
  onOffsetChanged();
}

function onOffsetInputChange() {
  const val = parseInt(el.offsetInput.value, 10);
  if (!isNaN(val)) {
    state.currentOffsetMs = val;
    onOffsetChanged();
  }
}

function resetToAutoOffset() {
  state.currentOffsetMs = state.autoOffsetMs;
  el.offsetInput.value = state.currentOffsetMs;
  onOffsetChanged();
}

function onOffsetChanged() {
  renderWaveforms();
  if (typeof updateTrimSummary === 'function') {
    updateTrimSummary();
  }
  // If playing, restart preview at current position with new offset
  if (state.isPlaying) {
    const curTime = el.previewVideo.currentTime;
    stopAudioPreview();
    startAudioPreview(curTime);
  }
}

// ==========================================
// 6. SYNCHRONIZED PREVIEW PLAYER
// ==========================================
function setupPreviewDurations() {
  el.previewVideo.addEventListener('loadedmetadata', () => {
    el.durationTimeText.textContent = formatSeconds(el.previewVideo.duration);
  });
  el.previewVideo.addEventListener('timeupdate', () => {
    el.currentTimeText.textContent = formatSeconds(el.previewVideo.currentTime);
    updatePlayheadPosition();
  });
  el.previewVideo.addEventListener('ended', () => {
    stopPreview();
  });
}

function updatePlayheadPosition() {
  if (!el.previewVideo.duration || !state.timeline) return;
  const { t0, t1 } = state.timeline;
  const pct = ((el.previewVideo.currentTime - t0) / (t1 - t0)) * 100;
  el.playhead.style.display = 'block';
  el.playhead.style.left = Math.max(0, Math.min(100, pct)) + '%';
}

function togglePlayPreview() {
  if (state.isPlaying) {
    stopPreview();
  } else {
    startPreview();
  }
}

function startPreview() {
  state.isPlaying = true;
  el.playIcon.textContent = '⏸';
  el.playText.textContent = 'Tạm Dừng';
  el.btnOverlayPlay.style.display = 'none';

  const startTime = el.previewVideo.currentTime;
  el.previewVideo.play();
  startAudioPreview(startTime);
}

function stopPreview() {
  state.isPlaying = false;
  el.playIcon.textContent = '▶';
  el.playText.textContent = 'Nghe Thử Đồng Bộ';
  el.btnOverlayPlay.style.display = 'flex';

  el.previewVideo.pause();
  stopAudioPreview();
}

function seekPreview(time) {
  el.previewVideo.currentTime = time;
  if (state.isPlaying) {
    stopAudioPreview();
    startAudioPreview(time);
  }
}

function startAudioPreview(videoCurrentTime) {
  const ctx = state.syncEngine.getAudioContext();
  if (!state.bufferGoc) return;

  // Convention (same as server): offset > 0 => music starts `offset` AFTER the start of the dance video.
  // dance[t] ~ original[t - offset]  =>  position in original = videoTime - offset
  const offsetSec = state.currentOffsetMs / 1000;
  const gocAudioPosition = videoCurrentTime - offsetSec;

  if (gocAudioPosition >= state.bufferGoc.duration) return;

  // Create Source Node
  state.audioSourceNode = ctx.createBufferSource();
  state.audioSourceNode.buffer = state.bufferGoc;

  // Gain Node for Music Volume
  state.audioGainGoc = ctx.createGain();
  const musicVol = parseInt(el.musicVolume.value, 10) / 100;
  state.audioGainGoc.gain.value = musicVol;

  state.audioSourceNode.connect(state.audioGainGoc);
  state.audioGainGoc.connect(ctx.destination);

  if (gocAudioPosition >= 0) {
    state.audioSourceNode.start(0, gocAudioPosition);
  } else {
    // Delay music start if video started earlier
    state.audioSourceNode.start(ctx.currentTime + Math.abs(gocAudioPosition), 0);
  }
}

function stopAudioPreview() {
  if (state.audioSourceNode) {
    try { state.audioSourceNode.stop(); } catch (e) {}
    state.audioSourceNode.disconnect();
    state.audioSourceNode = null;
  }
}

function updateAudioVolumes() {
  const musicVol = parseInt(el.musicVolume.value, 10);
  const roomVol = parseInt(el.roomVolume.value, 10);

  el.musicVolText.textContent = musicVol + '%';
  el.roomVolText.textContent = roomVol + '%';

  if (state.audioGainGoc) {
    state.audioGainGoc.gain.value = musicVol / 100;
  }
  // Video element volume handles room audio
  el.previewVideo.muted = (roomVol === 0);
  el.previewVideo.volume = roomVol / 100;
}

// ==========================================
// 6.5. TRIMMING & RESOLUTION CONTROLS
// ==========================================
function initTrimControls() {
  const danceDur = state.danceDuration || (el.previewVideo && el.previewVideo.duration ? el.previewVideo.duration : 60);
  const origDur = state.originalDuration || (state.bufferGoc ? state.bufferGoc.duration : 60);
  const offSec = state.currentOffsetMs / 1000;

  // 1. Auto Start: if offSec > 0.3s, start at offSec. Else start at 0s.
  if (offSec > 0.3) {
    state.trimStartSec = Math.round(offSec * 100) / 100;
    if (el.trimStartToggle) el.trimStartToggle.checked = true;
    if (el.trimStartHint) el.trimStartHint.textContent = `Bỏ ${state.trimStartSec.toFixed(2)}s đứng chờ trước khi nhạc vào`;
  } else {
    state.trimStartSec = 0.0;
    if (el.trimStartToggle) el.trimStartToggle.checked = false;
    if (el.trimStartHint) el.trimStartHint.textContent = `Không có đoạn chờ đầu (bắt đầu từ 0s)`;
  }
  if (el.trimStartInput) el.trimStartInput.value = state.trimStartSec.toFixed(1);

  // 2. Auto End: when original music ends in dance video = offSec + origDur
  const musicEndInDance = offSec + origDur;
  if (danceDur - musicEndInDance > 0.5 && musicEndInDance > 2.0) {
    state.trimEndSec = Math.min(danceDur, Math.round(musicEndInDance * 100) / 100);
    if (el.trimEndToggle) el.trimEndToggle.checked = true;
    const extraTail = (danceDur - state.trimEndSec).toFixed(1);
    if (el.trimEndHint) el.trimEndHint.textContent = `Bỏ ${extraTail}s đoạn thừa sau khi hết nhạc`;
  } else {
    state.trimEndSec = Math.round(danceDur * 100) / 100;
    if (el.trimEndToggle) el.trimEndToggle.checked = false;
    if (el.trimEndHint) el.trimEndHint.textContent = `Giữ trọn vẹn đến hết video`;
  }
  if (el.trimEndInput) el.trimEndInput.value = state.trimEndSec.toFixed(1);

  updateTrimUIState();
  updateTrimSummary();
}

function updateTrimUIState() {
  const startActive = el.trimStartToggle && el.trimStartToggle.checked;
  const endActive = el.trimEndToggle && el.trimEndToggle.checked;

  if (el.trimStartControls) {
    el.trimStartControls.style.opacity = startActive ? '1' : '0.4';
    el.trimStartControls.style.pointerEvents = startActive ? 'auto' : 'none';
  }
  if (el.trimEndControls) {
    el.trimEndControls.style.opacity = endActive ? '1' : '0.4';
    el.trimEndControls.style.pointerEvents = endActive ? 'auto' : 'none';
  }
}

function onTrimToggleChange() {
  updateTrimUIState();
  updateTrimSummary();
}

function onTrimInputChange() {
  const danceDur = state.danceDuration || (el.previewVideo && el.previewVideo.duration ? el.previewVideo.duration : 60);
  let s = parseFloat(el.trimStartInput ? el.trimStartInput.value : 0) || 0;
  let e = parseFloat(el.trimEndInput ? el.trimEndInput.value : danceDur) || danceDur;

  s = Math.max(0, Math.min(danceDur - 1, s));
  e = Math.max(s + 1, Math.min(danceDur, e));

  state.trimStartSec = Math.round(s * 10) / 10;
  state.trimEndSec = Math.round(e * 10) / 10;

  if (el.trimStartInput) el.trimStartInput.value = state.trimStartSec.toFixed(1);
  if (el.trimEndInput) el.trimEndInput.value = state.trimEndSec.toFixed(1);

  updateTrimSummary();
}

function adjustTrimStart(delta) {
  const danceDur = state.danceDuration || (el.previewVideo && el.previewVideo.duration ? el.previewVideo.duration : 60);
  let s = state.trimStartSec + delta;
  s = Math.max(0, Math.min(state.trimEndSec - 0.5, s));
  state.trimStartSec = Math.round(s * 10) / 10;
  if (el.trimStartInput) el.trimStartInput.value = state.trimStartSec.toFixed(1);
  if (el.trimStartToggle) el.trimStartToggle.checked = true;
  updateTrimUIState();
  updateTrimSummary();
}

function adjustTrimEnd(delta) {
  const danceDur = state.danceDuration || (el.previewVideo && el.previewVideo.duration ? el.previewVideo.duration : 60);
  let e = state.trimEndSec + delta;
  e = Math.max(state.trimStartSec + 0.5, Math.min(danceDur, e));
  state.trimEndSec = Math.round(e * 10) / 10;
  if (el.trimEndInput) el.trimEndInput.value = state.trimEndSec.toFixed(1);
  if (el.trimEndToggle) el.trimEndToggle.checked = true;
  updateTrimUIState();
  updateTrimSummary();
}

function setTrimStartPreset(type) {
  const offSec = Math.max(0, state.currentOffsetMs / 1000);
  if (type === 'auto') {
    state.trimStartSec = Math.round(offSec * 10) / 10;
    if (el.trimStartToggle) el.trimStartToggle.checked = true;
  } else if (type === 'zero') {
    state.trimStartSec = 0.0;
    if (el.trimStartToggle) el.trimStartToggle.checked = false;
  }
  if (el.trimStartInput) el.trimStartInput.value = state.trimStartSec.toFixed(1);
  updateTrimUIState();
  updateTrimSummary();
}

function setTrimEndPreset(type) {
  const danceDur = state.danceDuration || (el.previewVideo && el.previewVideo.duration ? el.previewVideo.duration : 60);
  const origDur = state.originalDuration || (state.bufferGoc ? state.bufferGoc.duration : 60);
  const offSec = state.currentOffsetMs / 1000;
  if (type === 'auto') {
    const musicEnd = Math.min(danceDur, Math.max(1, offSec + origDur));
    state.trimEndSec = Math.round(musicEnd * 10) / 10;
    if (el.trimEndToggle) el.trimEndToggle.checked = true;
  } else if (type === 'full') {
    state.trimEndSec = Math.round(danceDur * 10) / 10;
    if (el.trimEndToggle) el.trimEndToggle.checked = false;
  }
  if (el.trimEndInput) el.trimEndInput.value = state.trimEndSec.toFixed(1);
  updateTrimUIState();
  updateTrimSummary();
}

function resetTrimToAuto() {
  initTrimControls();
}

function updateTrimSummary() {
  const danceDur = state.danceDuration || (el.previewVideo && el.previewVideo.duration ? el.previewVideo.duration : 60);
  const startActive = el.trimStartToggle && el.trimStartToggle.checked;
  const endActive = el.trimEndToggle && el.trimEndToggle.checked;

  const actualStart = startActive ? state.trimStartSec : 0;
  const actualEnd = endActive ? state.trimEndSec : danceDur;
  const netDuration = Math.max(0, actualEnd - actualStart);

  if (el.trimSummaryDur) {
    el.trimSummaryDur.textContent = `${netDuration.toFixed(1)}s (từ ${actualStart.toFixed(1)}s ➔ ${actualEnd.toFixed(1)}s)`;
  }

  if (el.trimSummaryBadges) {
    let badges = [];
    if (startActive && actualStart > 0.1) {
      badges.push(`<span class="trim-badge">✂️ Đã cắt ${actualStart.toFixed(1)}s chờ đầu</span>`);
    } else {
      badges.push(`<span class="trim-badge" style="color:var(--text-dim);border-color:var(--border-subtle)">🎬 Giữ từ 0s</span>`);
    }

    const cutTail = danceDur - actualEnd;
    if (endActive && cutTail > 0.1) {
      badges.push(`<span class="trim-badge">✂️ Đã cắt ${cutTail.toFixed(1)}s đuôi</span>`);
    } else {
      badges.push(`<span class="trim-badge" style="color:var(--text-dim);border-color:var(--border-subtle)">🎬 Giữ đến hết video</span>`);
    }
    el.trimSummaryBadges.innerHTML = badges.join(' ');
  }
}

function previewTrimmedRange() {
  const danceDur = state.danceDuration || (el.previewVideo && el.previewVideo.duration ? el.previewVideo.duration : 60);
  const startActive = el.trimStartToggle && el.trimStartToggle.checked;
  const endActive = el.trimEndToggle && el.trimEndToggle.checked;

  const actualStart = startActive ? state.trimStartSec : 0;
  const actualEnd = endActive ? state.trimEndSec : danceDur;

  seekPreview(actualStart);
  if (!state.isPlaying) startPreview();

  if (state.trimPreviewTimer) clearTimeout(state.trimPreviewTimer);
  const durMs = (actualEnd - actualStart) * 1000;
  state.trimPreviewTimer = setTimeout(() => {
    if (state.isPlaying) stopPreview();
  }, Math.max(500, durMs));
}

function selectResolutionMode(mode) {
  state.resolutionMode = mode;
  if (el.resCardTiktok) el.resCardTiktok.classList.toggle('active', mode === 'tiktok_1080p');
  if (el.resCardOriginal) el.resCardOriginal.classList.toggle('active', mode === 'original');
  const radio = document.querySelector(`input[name="resMode"][value="${mode}"]`);
  if (radio) radio.checked = true;
}

// ==========================================
// 7. STEP 3: EXPORT PIPELINE
// ==========================================
function goToStep3() {
  stopPreview();

  el.step2.classList.add('hidden');
  el.step3.classList.remove('hidden');
  el.stepNav2.classList.remove('active');
  el.stepNav2.classList.add('completed');
  el.stepNav3.classList.add('active');

  runExportPipeline();
}

async function runExportPipeline() {
  if (el.exportProgressBox) el.exportProgressBox.classList.remove('hidden');
  if (el.exportResultBox) el.exportResultBox.classList.add('hidden');
  if (el.exportRetry) el.exportRetry.classList.add('hidden');

  const sign = state.currentOffsetMs > 0 ? '+' : '';
  const isTiktokMode = (state.resolutionMode === 'tiktok_1080p');
  
  if (el.exportStatusTitle) {
    el.exportStatusTitle.textContent = isTiktokMode 
      ? 'Đang ghép nhạc & nâng nét 1080p TikTok Ready...' 
      : 'Đang ghép âm thanh chất lượng cao vào video...';
  }
  if (el.exportStatusDesc) {
    el.exportStatusDesc.textContent = `Độ lệch: ${sign}${state.currentOffsetMs} ms. Đang xử lý...`;
  }

  let pct = 10;
  if (el.progressBarFill) el.progressBarFill.style.width = pct + '%';
  if (el.progressPctText) el.progressPctText.textContent = pct + '%';

  const timer = setInterval(() => {
    if (pct < 92) {
      pct += (pct < 60 ? 4 : 2);
      if (el.progressBarFill) el.progressBarFill.style.width = pct + '%';
      if (el.progressPctText) el.progressPctText.textContent = pct + '%';
      
      if (pct > 30 && pct < 65 && el.exportStatusDesc) {
        el.exportStatusDesc.textContent = 'Đang căn nhịp chuẩn từng mili-giây và loại bỏ tạp âm phòng...';
      } else if (pct >= 65 && el.exportStatusDesc) {
        el.exportStatusDesc.textContent = isTiktokMode
          ? 'Đang lọc nét viền Unsharp & scale 1080x1920 chuẩn TikTok...'
          : 'Đang kết xuất luồng video... Sắp hoàn tất!';
      }
    }
  }, 600);

  try {
    if (!state.sessionId) throw new Error('Chưa có phiên làm việc. Hãy quay lại bước 1 và chọn lại video.');
    
    const startActive = el.trimStartToggle && el.trimStartToggle.checked;
    const endActive = el.trimEndToggle && el.trimEndToggle.checked;
    const trimStartVal = startActive ? state.trimStartSec : 0.0;

    const formData = new FormData();
    formData.append('sessionId', state.sessionId);
    formData.append('offsetMs', state.currentOffsetMs);
    formData.append('musicVol', el.musicVolume ? el.musicVolume.value : 100);
    formData.append('roomVol', el.roomVolume ? el.roomVolume.value : 0);
    formData.append('trimLeadIn', startActive ? '1' : '0');
    formData.append('trimStart', trimStartVal);
    if (endActive) {
      formData.append('trimEnd', state.trimEndSec);
    }
    formData.append('resolutionMode', state.resolutionMode || 'tiktok_1080p');

    const response = await fetch('/api/render', { method: 'POST', body: formData });
    clearInterval(timer);

    if (!response.ok) {
      let msg = response.statusText;
      try { msg = (await response.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }

    const data = await response.json();
    if (el.progressBarFill) el.progressBarFill.style.width = '100%';
    if (el.progressPctText) el.progressPctText.textContent = '100%';
    if (el.exportStatusDesc) el.exportStatusDesc.textContent = 'Xuất video hoàn tất thành công!';
    setTimeout(() => onExportComplete(data.downloadUrl, data.filename), 400);

  } catch (err) {
    clearInterval(timer);
    console.error('Lỗi xuất video:', err);
    if (el.exportStatusTitle) el.exportStatusTitle.textContent = '⚠️ Không xuất được video';
    if (el.exportStatusDesc) el.exportStatusDesc.textContent = String(err.message || err) + ' — Bấm nút bên dưới để thử lại.';
    if (el.exportResultBox) el.exportResultBox.classList.add('hidden');
    if (el.progressBarFill) el.progressBarFill.style.width = '0%';
    if (el.progressPctText) el.progressPctText.textContent = '';
    if (el.exportRetry) el.exportRetry.classList.remove('hidden');
  }
}

function onExportComplete(downloadUrl, filename) {
  el.exportProgressBox.classList.add('hidden');
  el.exportResultBox.classList.remove('hidden');

  el.finalVideo.src = downloadUrl;
  el.btnDownload.href = downloadUrl;
  el.btnDownload.setAttribute('download', filename || `StyleFit_Synced_${Date.now()}.mp4`);
}

async function shareVideo() {
  if (navigator.share) {
    try {
      await navigator.share({
        title: 'Video StyleFit Step Dance đã ghép nhạc chuẩn',
        text: 'Video ghép nhạc tự động bằng StyleFit Ghép Nhạc!',
        url: window.location.href
      });
    } catch (err) {
      console.log('Share canceled or not supported:', err);
    }
  } else {
    // Fallback: trigger download directly
    el.btnDownload.click();
  }
}

function resetAll() {
  stopPreview();
  location.reload();
}
