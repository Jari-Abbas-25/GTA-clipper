/**
 * 9:16 Vertical Canvas Video Editor & Interactive Facecam Manipulator.
 * Renders in real-time synced to <video> playback.
 */

class CanvasEditor {
  constructor(canvasId, videoId, overlayBoxId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    this.video = document.getElementById(videoId);
    this.overlayBox = document.getElementById(overlayBoxId);

    // Canvas size (standard 9:16 preview: 360x640, scaling from 1080x1920)
    this.W = 360;
    this.H = 640;
    this.SPLIT_TOP = 256; // 40% of 640 (corresponds to 768px in 1920)

    // Current editing configuration
    this.config = {
      layout: 'split',
      facecam: { x: 0.72, y: 0.06, w: 0.24, h: 0.28 },
      gameplayPanX: 0.5,
      zoomFactor: 1.0,
      enableSubtitles: true,
      subtitleStyle: 'bold',
      fontSize: 22,
      primaryColor: '#ffffff',
      highlightColor: '#fbbf24',
      segments: []
    };

    this.rafId = null;
    this.isDragging = false;
    this.dragMode = 'move'; // 'move', 'nw', 'ne', 'sw', 'se'
    this.dragStart = { x: 0, y: 0 };
    this.initialBox = { x: 0, y: 0, w: 0, h: 0 };

    this.setupListeners();
    this.startRenderLoop();
  }

  setConfig(newConfig) {
    this.config = { ...this.config, ...newConfig };
    this.updateOverlayBoxPosition();
  }

  setupListeners() {
    // Sync render on video play/seek/timeupdate
    this.video.addEventListener('play', () => this.startRenderLoop());
    this.video.addEventListener('seeked', () => this.drawFrame());
    this.video.addEventListener('timeupdate', () => this.drawFrame());

    // Dragging overlay box
    if (this.overlayBox) {
      this.overlayBox.addEventListener('pointerdown', (e) => this.onPointerDown(e));
      window.addEventListener('pointermove', (e) => this.onPointerMove(e));
      window.addEventListener('pointerup', () => this.onPointerUp());
    }
  }

  startRenderLoop() {
    if (this.rafId) cancelAnimationFrame(this.rafId);
    const loop = () => {
      this.drawFrame();
      if (!this.video.paused && !this.video.ended) {
        this.rafId = requestAnimationFrame(loop);
      }
    };
    this.rafId = requestAnimationFrame(loop);
  }

  drawFrame() {
    const v = this.video;
    const ctx = this.ctx;
    const W = this.W;
    const H = this.H;

    ctx.fillStyle = '#0a0e17';
    ctx.fillRect(0, 0, W, H);

    if (v.readyState < 2 || !v.videoWidth || !v.videoHeight) {
      // Draw placeholder
      ctx.fillStyle = '#1e293b';
      ctx.font = '14px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Loading Video Frame...', W / 2, H / 2);
      return;
    }

    const vw = v.videoWidth;
    const vh = v.videoHeight;
    const layout = this.config.layout;

    if (layout === 'split') {
      // 1. Top Panel: Facecam (scaled to 360x256)
      const fc = this.config.facecam;
      const fx = Math.max(0, fc.x * vw);
      const fy = Math.max(0, fc.y * vh);
      const fw = Math.max(10, Math.min(vw - fx, fc.w * vw));
      const fh = Math.max(10, Math.min(vh - fy, fc.h * vh));

      // Draw facecam cover-cropped to top panel
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, W, this.SPLIT_TOP);
      ctx.clip();
      this.drawCoverImage(ctx, v, fx, fy, fw, fh, 0, 0, W, this.SPLIT_TOP);
      ctx.restore();

      // Divider line
      ctx.strokeStyle = '#24324a';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(0, this.SPLIT_TOP);
      ctx.lineTo(W, this.SPLIT_TOP);
      ctx.stroke();

      // 2. Bottom Panel: Gameplay (scaled to 360x384)
      const bottomH = H - this.SPLIT_TOP;
      const zoom = this.config.zoomFactor || 1.0;
      const gw = vw / zoom;
      const gh = vh / zoom;
      const gx = (vw - gw) * (this.config.gameplayPanX || 0.5);
      const gy = (vh - gh) / 2;

      ctx.save();
      ctx.beginPath();
      ctx.rect(0, this.SPLIT_TOP, W, bottomH);
      ctx.clip();
      this.drawCoverImage(ctx, v, gx, gy, gw, gh, 0, this.SPLIT_TOP, W, bottomH);
      ctx.restore();

    } else if (layout === 'fit') {
      // Centered 16:9 with blurred background
      ctx.save();
      ctx.filter = 'blur(12px) brightness(0.6)';
      this.drawCoverImage(ctx, v, 0, 0, vw, vh, 0, 0, W, H);
      ctx.restore();

      const scale = W / vw;
      const fh = vh * scale;
      const fy = (H - fh) / 2;
      ctx.drawImage(v, 0, 0, vw, vh, 0, fy, W, fh);

    } else if (layout === 'crop') {
      // 9:16 Full Screen Crop
      const zoom = this.config.zoomFactor || 1.0;
      const targetAspect = W / H;
      let ch = vh / zoom;
      let cw = ch * targetAspect;
      if (cw > vw) {
        cw = vw;
        ch = cw / targetAspect;
      }
      const cx = (vw - cw) * (this.config.gameplayPanX || 0.5);
      const cy = (vh - ch) / 2;
      ctx.drawImage(v, cx, cy, cw, ch, 0, 0, W, H);

    } else if (layout === 'pip') {
      // PiP: Gameplay base + floating webcam box
      this.drawCoverImage(ctx, v, 0, 0, vw, vh, 0, 0, W, H);

      const fc = this.config.facecam;
      const fx = Math.max(0, fc.x * vw);
      const fy = Math.max(0, fc.y * vh);
      const fw = Math.max(10, Math.min(vw - fx, fc.w * vw));
      const fh = Math.max(10, Math.min(vh - fy, fc.h * vh));

      const pw = W * fc.w * 1.5;
      const ph = H * fc.h * 1.0;
      const px = W * fc.x;
      const py = H * fc.y;

      // Box border & shadow
      ctx.shadowColor = 'rgba(0,0,0,0.7)';
      ctx.shadowBlur = 8;
      ctx.strokeStyle = '#fbbf24';
      ctx.lineWidth = 2;
      ctx.strokeRect(px, py, pw, ph);
      ctx.drawImage(v, fx, fy, fw, fh, px, py, pw, ph);
      ctx.shadowBlur = 0;
    }

    // 3. Draw Subtitles if enabled
    if (this.config.enableSubtitles && this.config.segments && this.config.segments.length > 0) {
      this.drawSubtitles(ctx);
    }
  }

  drawCoverImage(ctx, img, sx, sy, sw, sh, dx, dy, dw, dh) {
    const sRatio = sw / sh;
    const dRatio = dw / dh;
    let finalSw = sw;
    let finalSh = sh;
    let finalSx = sx;
    let finalSy = sy;

    if (sRatio > dRatio) {
      finalSw = sh * dRatio;
      finalSx = sx + (sw - finalSw) / 2;
    } else {
      finalSh = sw / dRatio;
      finalSy = sy + (sh - finalSh) / 2;
    }
    ctx.drawImage(img, finalSx, finalSy, finalSw, finalSh, dx, dy, dw, dh);
  }

  drawSubtitles(ctx) {
    const curTime = this.video.currentTime;
    const segments = this.config.segments;

    // Find active segment
    const activeSeg = segments.find(s => curTime >= s.start && curTime <= s.end);
    if (!activeSeg) return;

    const style = this.config.subtitleStyle || 'bold';
    const capY = this.config.layout === 'split' ? this.SPLIT_TOP + 30 : this.H - 120;
    const fontSize = this.config.fontSize || 22;

    ctx.save();
    ctx.font = `800 ${fontSize}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    if (style === 'bold' && activeSeg.words && activeSeg.words.length > 0) {
      // Find current word
      const words = activeSeg.words;
      const fullText = words.map(w => w.word.toUpperCase()).join(' ');
      const totalW = ctx.measureText(fullText).width;
      let startX = (this.W - totalW) / 2;

      ctx.textAlign = 'left';
      words.forEach(w => {
        const wordText = w.word.toUpperCase() + ' ';
        const wordW = ctx.measureText(wordText).width;
        const isSpoken = curTime >= w.start && curTime <= w.end;

        // Outline
        ctx.strokeStyle = '#000000';
        ctx.lineWidth = 5;
        ctx.lineJoin = 'round';
        ctx.strokeText(wordText, startX, capY);

        // Fill color: gold for active word, white for others
        ctx.fillStyle = isSpoken ? this.config.highlightColor : this.config.primaryColor;
        ctx.fillText(wordText, startX, capY);

        startX += wordW;
      });

    } else {
      // Clean Box or Minimal
      const text = activeSeg.text;
      const textW = ctx.measureText(text).width;

      if (style === 'clean') {
        ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
        ctx.fillRect((this.W - textW) / 2 - 12, capY - fontSize / 2 - 6, textW + 24, fontSize + 12);
      }

      ctx.strokeStyle = '#000000';
      ctx.lineWidth = 3;
      ctx.strokeText(text, this.W / 2, capY);
      ctx.fillStyle = this.config.primaryColor;
      ctx.fillText(text, this.W / 2, capY);
    }

    ctx.restore();
  }

  // Overlay Box Manipulation (Facecam drag & resize)
  updateOverlayBoxPosition() {
    if (!this.overlayBox) return;
    if (this.config.layout !== 'split' && this.config.layout !== 'pip') {
      this.overlayBox.classList.remove('active');
      return;
    }
    this.overlayBox.classList.add('active');

    // In split layout, the overlay box sits on the top panel (0 to SPLIT_TOP)
    const fc = this.config.facecam;
    const topH = this.config.layout === 'split' ? this.SPLIT_TOP : this.H;
    const topY = 0;

    const boxX = fc.x * this.W;
    const boxY = topY + fc.y * topH;
    const boxW = fc.w * this.W;
    const boxH = fc.h * topH;

    this.overlayBox.style.left = `${boxX}px`;
    this.overlayBox.style.top = `${boxY}px`;
    this.overlayBox.style.width = `${boxW}px`;
    this.overlayBox.style.height = `${boxH}px`;
  }

  onPointerDown(e) {
    e.preventDefault();
    this.isDragging = true;
    const target = e.target;
    if (target.classList.contains('handle')) {
      if (target.classList.contains('nw')) this.dragMode = 'nw';
      else if (target.classList.contains('ne')) this.dragMode = 'ne';
      else if (target.classList.contains('sw')) this.dragMode = 'sw';
      else if (target.classList.contains('se')) this.dragMode = 'se';
    } else {
      this.dragMode = 'move';
    }

    this.dragStart = { x: e.clientX, y: e.clientY };
    this.initialBox = { ...this.config.facecam };
  }

  onPointerMove(e) {
    if (!this.isDragging) return;
    const dx = (e.clientX - this.dragStart.x) / this.W;
    const topH = this.config.layout === 'split' ? this.SPLIT_TOP : this.H;
    const dy = (e.clientY - this.dragStart.y) / topH;

    const b = { ...this.initialBox };
    if (this.dragMode === 'move') {
      b.x = Math.max(0, Math.min(1.0 - b.w, b.x + dx));
      b.y = Math.max(0, Math.min(1.0 - b.h, b.y + dy));
    } else if (this.dragMode === 'se') {
      b.w = Math.max(0.1, Math.min(1.0 - b.x, b.w + dx));
      b.h = Math.max(0.1, Math.min(1.0 - b.y, b.h + dy));
    } else if (this.dragMode === 'nw') {
      const newX = Math.max(0, Math.min(b.x + b.w - 0.1, b.x + dx));
      const newY = Math.max(0, Math.min(b.y + b.h - 0.1, b.y + dy));
      b.w = b.w + (b.x - newX);
      b.h = b.h + (b.y - newY);
      b.x = newX;
      b.y = newY;
    }

    this.config.facecam = {
      x: Math.round(b.x * 1000) / 1000,
      y: Math.round(b.y * 1000) / 1000,
      w: Math.round(b.w * 1000) / 1000,
      h: Math.round(b.h * 1000) / 1000
    };

    this.updateOverlayBoxPosition();
    this.drawFrame();
  }

  onPointerUp() {
    this.isDragging = false;
  }
}

window.CanvasEditor = CanvasEditor;
