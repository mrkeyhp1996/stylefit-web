/* ==========================================================================
   STYLEFIT EMBEDDED AIRDROP SUITE CONTROLLER (drop-hub.js)
   Live P2P & HTTP File Sharing Hub inside StyleFit Studio Suite
   ========================================================================== */

(function () {
  'use strict';

  let hubRoomId = null;
  let hubPollInterval = null;
  let hubLastPollTime = 0;
  let hubReceivedFiles = new Set();
  let hubReceivedCount = 0;

  // Audio Chime synthesizer
  function playHubChime() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'sine';
      osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
      osc.frequency.setValueAtTime(880.00, ctx.currentTime + 0.1); // A5
      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.38);
      osc.start();
      osc.stop(ctx.currentTime + 0.38);
    } catch (e) {
      // AudioContext muted/unsupported
    }
  }

  // Format bytes
  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  // Generate safe 5-char room id
  function generateRoomId() {
    const chars = '23456789abcdefghjkmnpqrstuvwxyz';
    let id = 'sf-';
    for (let i = 0; i < 5; i++) {
      id += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return id;
  }

  // Public domain enforcement
  function getPublicDropUrl(roomId) {
    const host = window.location.hostname;
    if (host === 'localhost' || host === '127.0.0.1' || host.startsWith('192.168.') || host.startsWith('10.')) {
      return `https://stylefit.vn/drop.html?room=${roomId}`;
    }
    return `${window.location.origin}/drop.html?room=${roomId}`;
  }

  // Render QR Code with absolute reliability
  function renderHubQR(containerId, text, size = 190) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = '';

    // Primary: QRCodeJS library (canvas/image)
    if (typeof QRCode !== 'undefined') {
      try {
        new QRCode(el, {
          text: text,
          width: size,
          height: size,
          colorDark: '#0B0B0D',
          colorLight: '#FFFFFF',
          correctLevel: QRCode.CorrectLevel.M
        });
        return;
      } catch (err) {
        console.warn('[DropHub] QRCode class error, using API fallback:', err);
      }
    }

    // Fail-safe API fallback: Always works in all browsers
    const img = document.createElement('img');
    img.src = `https://api.qrserver.com/v1/create-qr-code/?size=${size}x${size}&margin=8&data=${encodeURIComponent(text)}`;
    img.alt = 'StyleFit AirDrop QR';
    img.style.width = `${size}px`;
    img.style.height = `${size}px`;
    img.style.display = 'block';
    img.style.borderRadius = '8px';
    el.appendChild(img);
  }

  // Initialize Hub
  function initDropHub() {
    if (hubRoomId) return; // already initialized

    // Retrieve or generate room ID for this studio session
    let saved = sessionStorage.getItem('sf_studio_room_id');
    if (!saved || !/^sf-[a-z0-9]+/i.test(saved)) {
      saved = generateRoomId();
      sessionStorage.setItem('sf_studio_room_id', saved);
    }
    hubRoomId = saved;

    const publicUrl = getPublicDropUrl(hubRoomId);

    // Update UI elements
    const badge = document.getElementById('suiteRoomBadge');
    if (badge) badge.textContent = 'Mã: ' + hubRoomId;

    const linkInput = document.getElementById('suiteRoomLinkInput');
    if (linkInput) linkInput.value = publicUrl;

    // Render QR Code immediately (0ms)
    renderHubQR('suiteQrCode', publicUrl, 190);

    // Setup Copy Buttons
    const btnCopy = document.getElementById('btnSuiteCopyLink');
    if (btnCopy) {
      btnCopy.onclick = () => {
        copyText(publicUrl, btnCopy, 'Đã chép!');
      };
    }

    const btnZalo = document.getElementById('btnSuiteShareZalo');
    if (btnZalo) {
      btnZalo.onclick = () => {
        copyText(publicUrl, btnZalo, '✅ Đã chép link Zalo!');
      };
    }

    // Start background polling for files uploaded via HTTP fallback
    startHubPolling(hubRoomId);
  }

  function copyText(text, btn, successLabel) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        const orig = btn.textContent;
        btn.textContent = successLabel;
        setTimeout(() => btn.textContent = orig, 2000);
      }).catch(() => fallbackCopy(text, btn, successLabel));
    } else {
      fallbackCopy(text, btn, successLabel);
    }
  }

  function fallbackCopy(text, btn, successLabel) {
    const input = document.getElementById('suiteRoomLinkInput');
    if (input) {
      input.select();
      document.execCommand('copy');
      const orig = btn.textContent;
      btn.textContent = successLabel;
      setTimeout(() => btn.textContent = orig, 2000);
    }
  }

  // Poll server for received files
  function startHubPolling(roomId) {
    if (hubPollInterval) clearInterval(hubPollInterval);
    hubLastPollTime = Math.floor(Date.now() / 1000) - 10;

    hubPollInterval = setInterval(async () => {
      try {
        const res = await fetch(`/api/drop/poll?room=${encodeURIComponent(roomId)}&since=${hubLastPollTime}`);
        if (!res.ok) return;
        const data = await res.json();
        if (data && data.status === 'ok') {
          if (data.server_time) hubLastPollTime = data.server_time;
          if (Array.isArray(data.files) && data.files.length > 0) {
            data.files.forEach(f => {
              const uniqueKey = `${f.name}_${f.size}_${f.timestamp}`;
              if (!hubReceivedFiles.has(uniqueKey)) {
                hubReceivedFiles.add(uniqueKey);
                onNewFileReceived(f);
              }
            });
          }
        }
      } catch (e) {
        // Silent poll retry
      }
    }, 1500);
  }

  // Handle incoming file
  function onNewFileReceived(fileInfo) {
    playHubChime();
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);

    const box = document.getElementById('suiteReceivedBox');
    const list = document.getElementById('suiteReceivedList');
    const countBadge = document.getElementById('suiteReceivedCount');

    if (box) box.style.display = 'block';

    hubReceivedCount++;
    if (countBadge) countBadge.textContent = `${hubReceivedCount} video`;

    if (!list) return;

    const item = document.createElement('div');
    item.className = 'received-file-card';

    const isVideo = /\.(mp4|mov|m4v|avi|webm)$/i.test(fileInfo.name);
    const icon = isVideo ? '🎬' : '📄';

    item.innerHTML = `
      <div class="rfc-left">
        <span class="rfc-icon">${icon}</span>
        <div class="rfc-info">
          <div class="rfc-title">${escapeHtml(fileInfo.name)}</div>
          <div class="rfc-meta">
            ${formatBytes(fileInfo.size)} • Từ: <strong style="color:var(--primary);">${escapeHtml(fileInfo.sender || 'Hội viên')}</strong> • ${new Date().toLocaleTimeString()}
          </div>
        </div>
      </div>
      <div class="rfc-actions">
        <button type="button" class="btn-rfc-sync" title="Đưa video này vào Tab Ghép Nhạc ngay lập tức">
          🎵 Ghép Nhạc Ngay
        </button>
        <a href="${fileInfo.url}" download="${fileInfo.name}" class="btn-rfc-download" title="Tải file video về máy tính">
          ⬇️ Tải Về
        </a>
      </div>
    `;

    // Action: One-Click load into Sync Tool
    const btnSync = item.querySelector('.btn-rfc-sync');
    if (btnSync) {
      btnSync.onclick = async () => {
        btnSync.disabled = true;
        btnSync.textContent = '⏳ Đang chuyển...';
        await loadDropFileToSyncTool(fileInfo.url, fileInfo.name);
        btnSync.disabled = false;
        btnSync.textContent = '🎵 Ghép Nhạc Ngay';
      };
    }

    list.insertBefore(item, list.firstChild);
  }

  // One-click bridge into Tab 1 (Ghép Nhạc)
  async function loadDropFileToSyncTool(fileUrl, fileName) {
    try {
      const res = await fetch(fileUrl);
      if (!res.ok) throw new Error('Không thể tải file từ server');
      const blob = await res.blob();
      const file = new File([blob], fileName, { type: blob.type || 'video/mp4' });

      if (typeof window.handleFileSelect === 'function') {
        await window.handleFileSelect('Nhay', file);
      }

      if (typeof window.switchSuiteTab === 'function') {
        window.switchSuiteTab('sync', null, true);
      }

      // Scroll smoothly to Step 1
      const studio = document.getElementById('studio-suite');
      if (studio) studio.scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
      alert('Không thể chuyển video sang Ghép Nhạc: ' + err.message);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag));
  }

  // Fullscreen QR Modal functions
  window.expandSuiteQR = function () {
    const modal = document.getElementById('suiteQrModal');
    if (!modal) return;
    const publicUrl = getPublicDropUrl(hubRoomId || 'sf-live');
    renderHubQR('suiteQrModalCanvas', publicUrl, 320);
    const codeEl = document.getElementById('suiteQrModalCode');
    if (codeEl) codeEl.textContent = hubRoomId;
    modal.classList.add('active');
  };

  window.closeSuiteQRModal = function () {
    const modal = document.getElementById('suiteQrModal');
    if (modal) modal.classList.remove('active');
  };

  // Close modal on ESC key
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') window.closeSuiteQRModal();
  });

  // Auto initialize when switching to Drop Tab, or on DOMContentLoaded
  document.addEventListener('DOMContentLoaded', () => {
    // If opened directly with #airdrop or #drop hash
    const hash = window.location.hash;
    if (hash === '#airdrop' || hash === '#drop') {
      initDropHub();
    }
  });

  // Hook into switchSuiteTab
  const origSwitch = window.switchSuiteTab;
  window.switchSuiteTab = function (tabKey, btn, autoScroll) {
    if (typeof origSwitch === 'function') {
      origSwitch(tabKey, btn, autoScroll);
    }
    if (tabKey === 'drop') {
      initDropHub();
    }
  };

  // Export
  window.initDropHub = initDropHub;
  window.loadDropFileToSyncTool = loadDropFileToSyncTool;

})();
