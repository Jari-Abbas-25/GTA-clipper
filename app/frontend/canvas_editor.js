/**
 * GTA Clipper — Advanced Interactive Canvas Video Editor.
 * Supports:
 * 1. Multi-Section Timeline Transitions (different layouts across time ranges)
 * 2. Independent Gameplay & Streamer element positioning, scaling, zoom, pan, borders, corner radii
 * 3. Aspect Ratio Switching: 9:16 Portrait (360x640) & 16:9 Landscape (640x360)
 * 4. Direct canvas drag-and-drop & corner resize handles for selected element
 * 5. Word-by-word active highlighted subtitles preview
 * 6. Real-time 60fps canvas rendering synchronized with <video> element
 */

class CanvasEditor {
  constructor(canvasId, videoId, overlayBoxId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    this.video = document.getElementById(videoId);
    this.overlayBox = document.getElementById(overlayBoxId);

    // Canvas preview dimensions
    this.aspectRatio = '9:16';
    this.W = 360;
    this.H = 640;

    // Timeline Sections & Global Config
    this.clipStart = 0.0;
    this.clipEnd = 30.0;
    this.sections = [];
    this.activeSectionIndex = 0;
    this.selectedElement = 'streamer'; // 'streamer' | 'gameplay' | null

    // Default Fallback Settings
    this.defaultSettings = {
      layout: 'split',
      aspect_ratio: '9:16',
      facecam_x: 0.72,
      facecam_y: 0.06,
      facecam_w: 0.24,
      facecam_h: 0.28,
      gameplay_pan_x: 0.5,
      zoom_factor: 1.0,
      enable_subtitles: true,
      subtitle_style: 'bold',
      font_size: 22,
      primary_color: '#ffffff',
      highlight_color: '#fbbf24',
      segments: [],
    };

    this.config = { ...this.defaultSettings };

    // Interaction state
    this.rafId = null;
    this.isDragging = false;
    this.dragTarget = null; // 'streamer' | 'gameplay'
    this.dragMode = 'move';  // 'move' | 'nw' | 'ne' | 'sw' | 'se'
    this.dragStart = { x: 0, y: 0 };
    this.initialProps = {};

    this.onSectionChanged = null;
    this.onPropertiesChanged = null;

    this.setupListeners();
    this.startRenderLoop();
  }

  // =========================================================================
  // Aspect Ratio & Layout Setup
  // =========================================================================

  setAspectRatio(aspect) {
    this.aspectRatio = aspect === '16:9' ? '16:9' : '9:16';
    if (this.aspectRatio === '16:9') {
      this.W = 640;
      this.H = 360;
    } else {
      this.W = 360;
      this.H = 640;
    }
    this.canvas.width = this.W;
    this.canvas.height = this.H;
    this.config.aspect_ratio = this.aspectRatio;
    this.updateOverlayBoxPosition();
    this.drawFrame();
  }

  setConfig(newConfig) {
    this.config = { ...this.config, ...newConfig };
    if (newConfig.aspect_ratio) {
      this.setAspectRatio(newConfig.aspect_ratio);
    }
    if (newConfig.start_s !== undefined) this.clipStart = parseFloat(newConfig.start_s);
    if (newConfig.end_s !== undefined) this.clipEnd = parseFloat(newConfig.end_s);

    if (newConfig.sections && Array.isArray(newConfig.sections) && newConfig.sections.length > 0) {
      this.sections = JSON.parse(JSON.stringify(newConfig.sections));
    } else if (this.sections.length === 0) {
      this.initDefaultSection();
    }

    this.updateOverlayBoxPosition();
    this.drawFrame();
  }

  initDefaultSection() {
    const dur = Math.max(5.0, this.clipEnd - this.clipStart);
    const layout = this.config.layout || 'split';
    const isSplit = layout === 'split';

    this.sections = [{
      id: 'sec_1',
      start: 0.0,
      end: dur,
      layout: layout,
      label: 'Main Edit',
      gameplay: {
        x: 0.0,
        y: isSplit ? 0.40 : 0.0,
        w: 1.0,
        h: isSplit ? 0.60 : 1.0,
        zoom: this.config.zoom_factor || 1.0,
        pan_x: this.config.gameplay_pan_x || 0.5,
        pan_y: 0.5,
        border_w: 0,
        border_color: '#24324a',
        corner_radius: 0,
      },
      streamer: {
        enabled: isSplit,
        x: 0.0,
        y: 0.0,
        w: 1.0,
        h: isSplit ? 0.40 : 0.25,
        zoom: 1.0,
        crop_x: this.config.facecam_x || 0.72,
        crop_y: this.config.facecam_y || 0.06,
        crop_w: this.config.facecam_w || 0.24,
        crop_h: this.config.facecam_h || 0.28,
        border_w: isSplit ? 2 : 0,
        border_color: '#24324a',
        corner_radius: 0,
        z_index: 2,
      },
      background: { type: 'blur', color: '#000000' },
    }];
    this.activeSectionIndex = 0;
  }

  // =========================================================================
  // Section Navigation & Timeline Operations
  // =========================================================================

  getActiveSection(curTime = null) {
    if (!this.sections || this.sections.length === 0) {
      this.initDefaultSection();
    }

    const t = curTime !== null ? curTime : (this.video ? (this.video.currentTime - this.clipStart) : 0.0);
    const relT = Math.max(0.0, t);

    const foundIdx = this.sections.findIndex(s => relT >= s.start && relT <= s.end);
    if (foundIdx !== -1) {
      if (this.activeSectionIndex !== foundIdx) {
        this.activeSectionIndex = foundIdx;
        if (this.onSectionChanged) this.onSectionChanged(foundIdx, this.sections[foundIdx]);
      }
      return this.sections[foundIdx];
    }

    const idx = Math.max(0, Math.min(this.sections.length - 1, this.activeSectionIndex));
    return this.sections[idx];
  }

  splitSectionAt(timeOffset) {
    const curSec = this.getActiveSection(timeOffset);
    if (!curSec) return false;

    const t = Math.max(curSec.start + 1.0, Math.min(curSec.end - 1.0, timeOffset));
    if (t <= curSec.start + 0.5 || t >= curSec.end - 0.5) {
      return false; // Minimum segment duration is 0.5s
    }

    const origEnd = curSec.end;
    curSec.end = parseFloat(t.toFixed(2));

    const newSec = JSON.parse(JSON.stringify(curSec));
    newSec.id = `sec_${Date.now()}`;
    newSec.start = parseFloat(t.toFixed(2));
    newSec.end = origEnd;
    newSec.label = `${curSec.label} (Split)`;

    this.sections.splice(this.activeSectionIndex + 1, 0, newSec);
    this.activeSectionIndex += 1;

    this.updateOverlayBoxPosition();
    this.drawFrame();
    if (this.onSectionChanged) this.onSectionChanged(this.activeSectionIndex, newSec);
    return true;
  }

  deleteActiveSection() {
    if (this.sections.length <= 1) {
      alert('Cannot delete the only remaining timeline section.');
      return false;
    }

    const idx = this.activeSectionIndex;
    const curSec = this.sections[idx];

    if (idx > 0) {
      this.sections[idx - 1].end = curSec.end;
      this.sections.splice(idx, 1);
      this.activeSectionIndex = idx - 1;
    } else {
      this.sections[idx + 1].start = curSec.start;
      this.sections.splice(idx, 1);
      this.activeSectionIndex = 0;
    }

    this.updateOverlayBoxPosition();
    this.drawFrame();
    if (this.onSectionChanged) this.onSectionChanged(this.activeSectionIndex, this.sections[this.activeSectionIndex]);
    return true;
  }

  setActiveSectionLayout(layoutName) {
    const sec = this.getActiveSection();
    if (!sec) return;

    sec.layout = layoutName;
    const isSplit = layoutName === 'split';
    const isPip = layoutName === 'pip';
    const isFit = layoutName === 'fit';
    const isCrop = layoutName === 'crop';

    if (isSplit) {
      sec.gameplay.y = 0.40;
      sec.gameplay.h = 0.60;
      sec.streamer.enabled = true;
      sec.streamer.x = 0.0;
      sec.streamer.y = 0.0;
      sec.streamer.w = 1.0;
      sec.streamer.h = 0.40;
    } else if (isPip) {
      sec.gameplay.y = 0.0;
      sec.gameplay.h = 1.0;
      sec.streamer.enabled = true;
      sec.streamer.x = 0.65;
      sec.streamer.y = 0.05;
      sec.streamer.w = 0.30;
      sec.streamer.h = 0.25;
      sec.streamer.corner_radius = 8;
      sec.streamer.border_w = 2;
    } else if (isFit) {
      sec.gameplay.y = 0.0;
      sec.gameplay.h = 1.0;
      sec.streamer.enabled = false;
      sec.background.type = 'blur';
    } else if (isCrop) {
      sec.gameplay.y = 0.0;
      sec.gameplay.h = 1.0;
      sec.streamer.enabled = false;
    }

    this.updateOverlayBoxPosition();
    this.drawFrame();
    if (this.onPropertiesChanged) this.onPropertiesChanged(sec);
  }

  applyAiEditSuggestions(suggestions) {
    if (!suggestions || !Array.isArray(suggestions) || suggestions.length === 0) return;
    this.sections = JSON.parse(JSON.stringify(suggestions));
    this.activeSectionIndex = 0;
    this.updateOverlayBoxPosition();
    this.drawFrame();
    if (this.onSectionChanged) this.onSectionChanged(0, this.sections[0]);
  }

  // =========================================================================
  // Canvas Rendering Loop
  // =========================================================================

  setupListeners() {
    this.video.addEventListener('play', () => this.startRenderLoop());
    this.video.addEventListener('seeked', () => this.drawFrame());
    this.video.addEventListener('timeupdate', () => this.drawFrame());

    // Canvas direct click for element selection
    this.canvas.addEventListener('pointerdown', (e) => this.onCanvasPointerDown(e));

    // Dragging overlay box handles
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
      ctx.fillStyle = '#1e293b';
      ctx.font = '14px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('Loading Video Frame...', W / 2, H / 2);
      return;
    }

    const vw = v.videoWidth;
    const vh = v.videoHeight;
    const curTime = v.currentTime - this.clipStart;
    const sec = this.getActiveSection(curTime);

    // 1. Draw Background
    if (sec.background && sec.background.type === 'blur') {
      ctx.save();
      ctx.filter = 'blur(16px) brightness(0.55)';
      this.drawCoverImage(ctx, v, 0, 0, vw, vh, 0, 0, W, H);
      ctx.restore();
    } else {
      ctx.fillStyle = (sec.background && sec.background.color) || '#000000';
      ctx.fillRect(0, 0, W, H);
    }

    // Determine rendering order by z-index
    const stZ = (sec.streamer && sec.streamer.z_index) || 2;
    const renderStreamerFirst = stZ < 1;

    if (renderStreamerFirst && sec.streamer && sec.streamer.enabled) {
      this.drawStreamerElement(ctx, v, vw, vh, sec.streamer, W, H);
    }

    // 2. Draw Gameplay Element
    this.drawGameplayElement(ctx, v, vw, vh, sec, W, H);

    if (!renderStreamerFirst && sec.streamer && sec.streamer.enabled) {
      this.drawStreamerElement(ctx, v, vw, vh, sec.streamer, W, H);
    }

    // 3. Draw Subtitles
    if (this.config.enable_subtitles && this.config.segments && this.config.segments.length > 0) {
      this.drawSubtitles(ctx, v.currentTime);
    }

    this.updateOverlayBoxPosition();
  }

  drawGameplayElement(ctx, v, vw, vh, sec, W, H) {
    const gp = sec.gameplay || {};
    const layout = sec.layout || 'split';

    const gx = Math.round((gp.x || 0.0) * W);
    const gy = Math.round((gp.y || 0.0) * H);
    const gw = Math.round((gp.w || 1.0) * W);
    const gh = Math.round((gp.h || 1.0) * H);
    const zoom = Math.max(1.0, gp.zoom || 1.0);
    const panX = gp.pan_x !== undefined ? gp.pan_x : 0.5;

    ctx.save();
    if (gp.corner_radius > 0) {
      this.roundRectPath(ctx, gx, gy, gw, gh, gp.corner_radius);
      ctx.clip();
    }

    if (layout === 'fit') {
      // 16:9 proportional fit inside gameplay box
      const scale = gw / vw;
      const fitH = vh * scale;
      const fitY = gy + (gh - fitH) / 2;
      ctx.drawImage(v, 0, 0, vw, vh, gx, fitY, gw, fitH);
    } else {
      // Cropped gameplay cover with pan & zoom
      const targetAspect = gw / Math.max(1, gh);
      let ch = vh / zoom;
      let cw = ch * targetAspect;
      if (cw > vw) {
        cw = vw;
        ch = cw / targetAspect;
      }
      const cx = (vw - cw) * panX;
      const cy = (vh - ch) / 2;
      ctx.drawImage(v, cx, cy, cw, ch, gx, gy, gw, gh);
    }

    ctx.restore();

    // Border
    if (gp.border_w > 0) {
      ctx.save();
      ctx.strokeStyle = gp.border_color || '#24324a';
      ctx.lineWidth = gp.border_w;
      if (gp.corner_radius > 0) {
        this.roundRectPath(ctx, gx, gy, gw, gh, gp.corner_radius);
        ctx.stroke();
      } else {
        ctx.strokeRect(gx, gy, gw, gh);
      }
      ctx.restore();
    }
  }

  drawStreamerElement(ctx, v, vw, vh, st, W, H) {
    const sx = Math.round(st.x * W);
    const sy = Math.round(st.y * H);
    const sw = Math.round(st.w * W);
    const sh = Math.round(st.h * H);

    const cx = Math.max(0, (st.crop_x || 0.72) * vw);
    const cy = Math.max(0, (st.crop_y || 0.06) * vh);
    const cw = Math.max(32, Math.min(vw - cx, (st.crop_w || 0.24) * vw));
    const ch = Math.max(32, Math.min(vh - cy, (st.crop_h || 0.28) * vh));

    ctx.save();
    if (st.corner_radius > 0) {
      this.roundRectPath(ctx, sx, sy, sw, sh, st.corner_radius);
      ctx.clip();
    }

    this.drawCoverImage(ctx, v, cx, cy, cw, ch, sx, sy, sw, sh);
    ctx.restore();

    // Border
    if (st.border_w > 0) {
      ctx.save();
      ctx.strokeStyle = st.border_color || '#fbbf24';
      ctx.lineWidth = st.border_w;
      if (st.corner_radius > 0) {
        this.roundRectPath(ctx, sx, sy, sw, sh, st.corner_radius);
        ctx.stroke();
      } else {
        ctx.strokeRect(sx, sy, sw, sh);
      }
      ctx.restore();
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

  roundRectPath(ctx, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
    ctx.lineTo(x + radius, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
  }

  drawSubtitles(ctx, absTime) {
    const segments = this.config.segments;
    const activeSeg = segments.find(s => absTime >= s.start && absTime <= s.end);
    if (!activeSeg) return;

    const style = this.config.subtitle_style || 'bold';
    const capY = this.H - 90;
    const fontSize = this.config.font_size || 22;

    ctx.save();
    ctx.font = `800 ${fontSize}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    if (style === 'bold' && activeSeg.words && activeSeg.words.length > 0) {
      const words = activeSeg.words;
      const fullText = words.map(w => w.word.toUpperCase()).join(' ');
      const totalW = ctx.measureText(fullText).width;
      let startX = (this.W - totalW) / 2;

      ctx.textAlign = 'left';
      words.forEach(w => {
        const wordText = w.word.toUpperCase() + ' ';
        const wordW = ctx.measureText(wordText).width;
        const isSpoken = absTime >= w.start && absTime <= w.end;

        ctx.strokeStyle = '#000000';
        ctx.lineWidth = 5;
        ctx.lineJoin = 'round';
        ctx.strokeText(wordText, startX, capY);

        ctx.fillStyle = isSpoken ? (this.config.highlight_color || '#fbbf24') : (this.config.primary_color || '#ffffff');
        ctx.fillText(wordText, startX, capY);

        startX += wordW;
      });
    } else {
      const text = activeSeg.text;
      const textW = ctx.measureText(text).width;

      if (style === 'clean') {
        ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
        ctx.fillRect((this.W - textW) / 2 - 12, capY - fontSize / 2 - 6, textW + 24, fontSize + 12);
      }

      ctx.strokeStyle = '#000000';
      ctx.lineWidth = 4;
      ctx.strokeText(text, this.W / 2, capY);
      ctx.fillStyle = this.config.primary_color || '#ffffff';
      ctx.fillText(text, this.W / 2, capY);
    }

    ctx.restore();
  }

  // =========================================================================
  // Canvas Interactive Selection & Dragging
  // =========================================================================

  onCanvasPointerDown(e) {
    const rect = this.canvas.getBoundingClientRect();
    const clickX = (e.clientX - rect.left) / rect.width;
    const clickY = (e.clientY - rect.top) / rect.height;

    const sec = this.getActiveSection();
    if (!sec) return;

    // Check if clicked inside streamer element
    if (sec.streamer && sec.streamer.enabled) {
      const st = sec.streamer;
      if (clickX >= st.x && clickX <= st.x + st.w && clickY >= st.y && clickY <= st.y + st.h) {
        this.selectedElement = 'streamer';
        this.updateOverlayBoxPosition();
        if (this.onPropertiesChanged) this.onPropertiesChanged(sec);
        return;
      }
    }

    // Default select gameplay
    this.selectedElement = 'gameplay';
    this.updateOverlayBoxPosition();
    if (this.onPropertiesChanged) this.onPropertiesChanged(sec);
  }

  updateOverlayBoxPosition() {
    if (!this.overlayBox) return;
    const sec = this.getActiveSection();
    if (!sec) {
      this.overlayBox.classList.remove('active');
      return;
    }

    let target = null;
    if (this.selectedElement === 'streamer' && sec.streamer && sec.streamer.enabled) {
      target = sec.streamer;
      this.overlayBox.style.borderColor = target.border_color || '#fbbf24';
    } else if (this.selectedElement === 'gameplay' && sec.gameplay) {
      target = sec.gameplay;
      this.overlayBox.style.borderColor = '#38bdf8';
    }

    if (!target) {
      this.overlayBox.classList.remove('active');
      return;
    }

    this.overlayBox.classList.add('active');
    const boxX = Math.round(target.x * this.W);
    const boxY = Math.round(target.y * this.H);
    const boxW = Math.round(target.w * this.W);
    const boxH = Math.round(target.h * this.H);

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

    const sec = this.getActiveSection();
    const elem = this.selectedElement === 'streamer' ? sec.streamer : sec.gameplay;
    this.dragStart = { x: e.clientX, y: e.clientY };
    this.initialProps = { ...elem };
  }

  onPointerMove(e) {
    if (!this.isDragging) return;
    const sec = this.getActiveSection();
    const elem = this.selectedElement === 'streamer' ? sec.streamer : sec.gameplay;
    if (!elem) return;

    const dx = (e.clientX - this.dragStart.x) / this.W;
    const dy = (e.clientY - this.dragStart.y) / this.H;

    const b = { ...this.initialProps };
    if (this.dragMode === 'move') {
      b.x = Math.max(0.0, Math.min(1.0 - b.w, b.x + dx));
      b.y = Math.max(0.0, Math.min(1.0 - b.h, b.y + dy));
    } else if (this.dragMode === 'se') {
      b.w = Math.max(0.1, Math.min(1.0 - b.x, b.w + dx));
      b.h = Math.max(0.1, Math.min(1.0 - b.y, b.h + dy));
    } else if (this.dragMode === 'nw') {
      const newX = Math.max(0.0, Math.min(b.x + b.w - 0.1, b.x + dx));
      const newY = Math.max(0.0, Math.min(b.y + b.h - 0.1, b.y + dy));
      b.w = b.w + (b.x - newX);
      b.h = b.h + (b.y - newY);
      b.x = newX;
      b.y = newY;
    }

    elem.x = Math.round(b.x * 1000) / 1000;
    elem.y = Math.round(b.y * 1000) / 1000;
    elem.w = Math.round(b.w * 1000) / 1000;
    elem.h = Math.round(b.h * 1000) / 1000;

    this.updateOverlayBoxPosition();
    this.drawFrame();
    if (this.onPropertiesChanged) this.onPropertiesChanged(sec);
  }

  onPointerUp() {
    this.isDragging = false;
  }
}

window.CanvasEditor = CanvasEditor;
