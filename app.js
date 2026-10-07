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
  exportBlob: null
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
  trimLeadIn: document.getElementById('trimLeadIn'),
  exportRetry: document.getElementById('exportRetry'),

  exportProgressBox: document.getElementById('exportProgressBox'),
  exportResultBox: document.getElementById('exportResultBox'),
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

  // Check if both files ready
  if (state.fileGoc && state.fileNhay) {
    el.btnStartAnalysis.disabled = false;
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
    el.offsetInput.value = state.currentOffsetMs;

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
  el.exportProgressBox.classList.remove('hidden');
  el.exportResultBox.classList.add('hidden');
  const sign = state.currentOffsetMs > 0 ? '+' : '';
  el.exportStatusTitle.textContent = 'Đang ghép âm thanh vào video...';
  el.exportStatusDesc.textContent = 'Độ lệch áp dụng: ' + sign + state.currentOffsetMs + ' ms. Vui lòng chờ vài giây...';

  let pct = 15;
  el.progressBarFill.style.width = pct + '%';
  el.progressPctText.textContent = pct + '%';

  const timer = setInterval(() => {
    if (pct < 90) {
      pct += 5;
      el.progressBarFill.style.width = pct + '%';
      el.progressPctText.textContent = pct + '%';
    }
  }, 400);

  try {
    if (!state.sessionId) throw new Error('Chưa có phiên làm việc. Hãy quay lại bước 1 và chọn lại video.');
    const formData = new FormData();
    formData.append('sessionId', state.sessionId);
    formData.append('offsetMs', state.currentOffsetMs);
    formData.append('musicVol', el.musicVolume.value);
    formData.append('roomVol', el.roomVolume.value);
    formData.append('trimLeadIn', el.trimLeadIn && el.trimLeadIn.checked ? '1' : '0');

    const response = await fetch('/api/render', { method: 'POST', body: formData });
    clearInterval(timer);

    if (!response.ok) {
      let msg = response.statusText;
      try { msg = (await response.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }

    const data = await response.json();
    el.progressBarFill.style.width = '100%';
    el.progressPctText.textContent = '100%';
    setTimeout(() => onExportComplete(data.downloadUrl, data.filename), 300);

  } catch (err) {
    clearInterval(timer);
    console.error('Lỗi xuất video:', err);
    el.exportStatusTitle.textContent = '⚠️ Không xuất được video';
    el.exportStatusDesc.textContent = String(err.message || err) + ' — Bấm "Ghép một video khác" để thử lại.';
    el.exportResultBox.classList.add('hidden');
    el.progressBarFill.style.width = '0%';
    el.progressPctText.textContent = '';
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
