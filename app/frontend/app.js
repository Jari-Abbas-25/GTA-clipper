/**
 * GTA Clipper — Application Controller.
 * Manages project state, views, API communication, and editor integration.
 */

class AppController {
  constructor() {
    this.currentProjectId = null;
    this.currentProjectMeta = null;
    this.currentHighlights = null;
    this.activeClip = null;
    this.editor = null;
    this.pollInterval = null;

    this.init();
  }

  async init() {
    this.bindEvents();
    await this.checkSystemStatus();
    await this.checkActiveProjects();
  }

  async checkSystemStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      if (data.cpu_cores) {
        document.getElementById('cpuStatusText').textContent = `Core i5 (${data.cpu_cores}T CPU)`;
      }
      if (data.ollama_available) {
        document.getElementById('ollamaDot').className = 'status-dot';
        document.getElementById('ollamaStatusText').textContent = `Ollama (${data.ollama_model || 'Ready'})`;
      } else {
        document.getElementById('ollamaDot').className = 'status-dot warn';
        document.getElementById('ollamaStatusText').textContent = 'Ollama (Offline - Heuristics Active)';
      }
    } catch (e) {
      console.warn('Status check failed:', e);
    }
  }

  async checkActiveProjects() {
    try {
      const res = await fetch('/api/projects');
      const list = await res.json();
      if (list && list.length > 0) {
        // Load most recent project if ready
        const latest = list[0];
        if (latest.status === 'ready') {
          this.loadProject(latest.id);
        }
      }
    } catch (e) {
      console.warn('Projects lookup failed:', e);
    }
  }

  bindEvents() {
    // Navigation
    document.getElementById('btnNewProject').addEventListener('click', () => this.switchView('setupView'));
    document.getElementById('btnOpenProjects').addEventListener('click', () => this.openProjectsModal());
    document.getElementById('btnOpenStorage').addEventListener('click', () => this.openStorageModal());
    document.getElementById('btnCloseStorageModal').addEventListener('click', () => document.getElementById('storageModal').classList.remove('active'));
    document.getElementById('btnCloseProjectsModal').addEventListener('click', () => document.getElementById('projectsModal').classList.remove('active'));

    // Ingest & Download
    document.getElementById('btnStartIngest').addEventListener('click', () => this.startIngest());
    document.getElementById('btnLoadSample').addEventListener('click', () => this.loadSampleClip());
    document.getElementById('btnReanalyze').addEventListener('click', () => this.triggerAnalysis());
    document.getElementById('btnEditTopHighlight').addEventListener('click', () => {
      if (this.currentHighlights && this.currentHighlights.candidates.length > 0) {
        this.openClipEditor(this.currentHighlights.candidates[0].id);
      }
    });

    // Editor View
    document.getElementById('btnBackToHighlights').addEventListener('click', () => this.switchView('highlightsView'));
    document.getElementById('btnSaveClipSettings').addEventListener('click', () => this.saveClipSettings());
    document.getElementById('btnExportClip').addEventListener('click', () => this.exportCurrentClip());
    document.getElementById('btnTranscribeClip').addEventListener('click', () => this.transcribeCurrentClip());

    // Canvas playback controls
    const video = document.getElementById('sourceVideo');
    document.getElementById('btnCanvasPlayPause').addEventListener('click', () => {
      if (video.paused) video.play();
      else video.pause();
    });
    document.getElementById('btnResetCanvasTime').addEventListener('click', () => {
      if (this.activeClip) {
        video.currentTime = parseFloat(document.getElementById('trimStartInput').value) || this.activeClip.start;
      }
    });

    // Timeline Scrubber
    const scrubber = document.getElementById('timelineScrubber');
    scrubber.addEventListener('click', (e) => {
      const rect = scrubber.getBoundingClientRect();
      const pct = (e.clientX - rect.left) / rect.width;
      if (video.duration) {
        video.currentTime = pct * video.duration;
      }
    });

    video.addEventListener('timeupdate', () => {
      if (video.duration) {
        const pct = (video.currentTime / video.duration) * 100;
        document.getElementById('scrubberPlayhead').style.left = `${pct}%`;
        document.getElementById('editorCurrentTimeText').textContent = `${video.currentTime.toFixed(1)}s`;
      }
    });

    // Trim Inputs & Nudges
    const startIn = document.getElementById('trimStartInput');
    const endIn = document.getElementById('trimEndInput');
    const updateTrim = () => {
      const s = parseFloat(startIn.value) || 0;
      const e = parseFloat(endIn.value) || 0;
      document.getElementById('editorDurationText').textContent = `${Math.max(0, e - s).toFixed(1)}s`;
      this.updateScrubberHighlight();
    };
    startIn.addEventListener('input', updateTrim);
    endIn.addEventListener('input', updateTrim);

    document.getElementById('btnNudgeStartMinus1').addEventListener('click', () => { startIn.value = Math.max(0, (parseFloat(startIn.value) - 1.0)).toFixed(1); updateTrim(); });
    document.getElementById('btnNudgeStartPlus1').addEventListener('click', () => { startIn.value = (parseFloat(startIn.value) + 1.0).toFixed(1); updateTrim(); });
    document.getElementById('btnNudgeEndMinus1').addEventListener('click', () => { endIn.value = Math.max(0, (parseFloat(endIn.value) - 1.0)).toFixed(1); updateTrim(); });
    document.getElementById('btnNudgeEndPlus1').addEventListener('click', () => { endIn.value = (parseFloat(endIn.value) + 1.0).toFixed(1); updateTrim(); });

    // Layout Buttons
    document.querySelectorAll('.layout-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.layout-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const layout = btn.dataset.layout;
        if (this.editor) {
          this.editor.setConfig({ layout });
        }
      });
    });

    // Pan & Zoom Sliders
    const panIn = document.getElementById('panRangeInput');
    const zoomIn = document.getElementById('zoomRangeInput');
    panIn.addEventListener('input', () => {
      if (this.editor) this.editor.setConfig({ gameplayPanX: parseFloat(panIn.value) });
    });
    zoomIn.addEventListener('input', () => {
      if (this.editor) this.editor.setConfig({ zoomFactor: parseFloat(zoomIn.value) });
    });

    // Caption Style
    document.getElementById('selCaptionStyle').addEventListener('change', (e) => {
      if (this.editor) this.editor.setConfig({ subtitleStyle: e.target.value });
    });
    document.getElementById('chkEnableCaptions').addEventListener('change', (e) => {
      if (this.editor) this.editor.setConfig({ enableSubtitles: e.target.checked });
    });

    // Auto-detect Facecam
    document.getElementById('btnAutoDetectFacecam').addEventListener('click', () => {
      if (this.currentProjectMeta && this.currentProjectMeta.facecam_region) {
        const fc = this.currentProjectMeta.facecam_region;
        if (this.editor) {
          this.editor.setConfig({ facecam: { x: fc.x, y: fc.y, w: fc.w, h: fc.h } });
        }
      } else {
        alert('Facecam auto-detected default gaming coordinates (Top-Right webcam).');
      }
    });

    // Storage Actions
    document.getElementById('btnCleanCache').addEventListener('click', () => this.runCleanup(false, true));
    document.getElementById('btnDeleteSource').addEventListener('click', () => {
      if (confirm('Are you sure you want to delete the source video? Finished exports will be preserved.')) {
        this.runCleanup(true, true);
      }
    });
  }

  switchView(viewId) {
    document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
    const target = document.getElementById(viewId);
    if (target) target.classList.add('active');
  }

  async startIngest() {
    const input = document.getElementById('vodUrlInput').value.trim();
    if (!input) {
      alert('Please enter a Twitch VOD URL or local file path.');
      return;
    }

    document.getElementById('progressCard').style.display = 'block';
    this.updateProgress(5, 'Probing VOD & setting up project...');

    try {
      const res = await fetch('/api/projects/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url_or_path: input })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to start project');
      }
      const data = await res.json();
      this.currentProjectId = data.project_id;
      this.pollProjectStatus();
    } catch (e) {
      alert(`Error starting project: ${e.message}`);
      document.getElementById('progressCard').style.display = 'none';
    }
  }

  async loadSampleClip() {
    // Quickly generate or use a sample test highlight
    document.getElementById('vodUrlInput').value = 'https://www.twitch.tv/videos/sample';
    this.startIngest();
  }

  pollProjectStatus() {
    if (this.pollInterval) clearInterval(this.pollInterval);
    this.pollInterval = setInterval(async () => {
      if (!this.currentProjectId) return;
      try {
        const res = await fetch(`/api/projects/${this.currentProjectId}`);
        const data = await res.json();
        const job = data.job || {};

        this.updateProgress(job.percent || 10, job.message || 'Processing...');

        if (data.meta.status === 'downloaded') {
          // Trigger analysis automatically
          clearInterval(this.pollInterval);
          this.triggerAnalysis();
        } else if (data.meta.status === 'ready') {
          clearInterval(this.pollInterval);
          document.getElementById('progressCard').style.display = 'none';
          this.loadProject(this.currentProjectId);
        } else if (data.meta.status === 'error') {
          clearInterval(this.pollInterval);
          alert(`Error: ${data.meta.error || 'Job failed'}`);
          document.getElementById('progressCard').style.display = 'none';
        }
      } catch (e) {
        console.warn('Poll error:', e);
      }
    }, 1500);
  }

  async triggerAnalysis() {
    if (!this.currentProjectId) return;
    document.getElementById('progressCard').style.display = 'block';
    this.updateProgress(15, 'Extracting audio & detecting highlight signals...');

    try {
      await fetch(`/api/projects/${this.currentProjectId}/analyze`, { method: 'POST' });
      this.pollProjectStatus();
    } catch (e) {
      alert(`Failed to start analysis: ${e.message}`);
    }
  }

  updateProgress(pct, msg) {
    document.getElementById('progressBarFill').style.width = `${Math.min(100, Math.max(0, pct))}%`;
    document.getElementById('progressPercentText').textContent = `${Math.round(pct)}%`;
    document.getElementById('progressMessage').textContent = msg;
  }

  async loadProject(projectId) {
    this.currentProjectId = projectId;
    try {
      const res = await fetch(`/api/projects/${projectId}`);
      const data = await res.json();
      this.currentProjectMeta = data.meta;

      document.getElementById('currentProjectTitle').textContent = data.meta.title || projectId;
      document.getElementById('vodDurationText').textContent = `${(data.meta.duration / 60).toFixed(1)} mins`;
      document.getElementById('candCountText').textContent = data.candidate_count || 0;
      document.getElementById('exportCountText').textContent = data.exports ? data.exports.length : 0;

      // Load Highlights
      const hRes = await fetch(`/api/projects/${projectId}/highlights`);
      if (hRes.ok) {
        this.currentHighlights = await hRes.json();
        this.renderHypeMap(this.currentHighlights.hype_curve);
        this.renderCandidates(this.currentHighlights.candidates);
        this.switchView('highlightsView');
      }
    } catch (e) {
      console.error('Failed to load project:', e);
    }
  }

  renderHypeMap(hypeCurve) {
    const canvas = document.getElementById('hypeMapCanvas');
    if (!canvas || !hypeCurve || hypeCurve.length === 0) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement.clientWidth;
    const h = 80;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.fillStyle = '#0a0e17';
    ctx.fillRect(0, 0, w, h);

    // Draw smoothed engagement area curve
    const n = hypeCurve.length;
    const step = w / n;

    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, 'rgba(56, 189, 248, 0.6)');
    grad.addColorStop(1, 'rgba(168, 85, 247, 0.05)');

    ctx.beginPath();
    ctx.moveTo(0, h);
    for (let i = 0; i < n; i++) {
      const val = hypeCurve[i] / 100.0;
      const y = h - (val * (h - 10));
      ctx.lineTo(i * step, y);
    }
    ctx.lineTo(w, h);
    ctx.fillStyle = grad;
    ctx.fill();

    // Line stroke
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const val = hypeCurve[i] / 100.0;
      const y = h - (val * (h - 10));
      if (i === 0) ctx.moveTo(0, y);
      else ctx.lineTo(i * step, y);
    }
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Mark candidate highlight ranges
    if (this.currentHighlights && this.currentHighlights.candidates) {
      const dur = this.currentHighlights.duration;
      this.currentHighlights.candidates.forEach(c => {
        const x1 = (c.start / dur) * w;
        const x2 = (c.end / dur) * w;
        ctx.fillStyle = 'rgba(251, 191, 36, 0.35)';
        ctx.fillRect(x1, 0, Math.max(3, x2 - x1), h);

        // Gold tick at peak
        const px = (c.peak / dur) * w;
        ctx.fillStyle = '#fbbf24';
        ctx.fillRect(px - 1, 0, 2, h);
      });
    }
  }

  renderCandidates(candidates) {
    const grid = document.getElementById('candidatesGrid');
    grid.innerHTML = '';

    if (!candidates || candidates.length === 0) {
      grid.innerHTML = '<div style="color: var(--text-muted); padding: 20px;">No highlight candidates detected yet.</div>';
      return;
    }

    candidates.forEach(c => {
      const card = document.createElement('div');
      card.className = 'candidate-card';
      card.id = `card_${c.id}`;

      // Tags
      const tagsHtml = (c.reasons || []).map(r => {
        let cls = 'tag';
        if (r.code.includes('chat')) cls += ' chat';
        else if (r.code.includes('laughter')) cls += ' laughter';
        else cls += ' audio';
        return `<span class="${cls}">${r.code}: ${r.value}</span>`;
      }).join('');

      card.innerHTML = `
        <div class="card-top">
          <span class="card-rank">#${c.rank} (${c.id})</span>
          <span class="card-score-badge">HYPE ${c.hype_score}/100</span>
        </div>
        <div class="card-body">
          <div class="card-title">${c.suggested_title || 'Gaming Highlight'}</div>
          <div class="card-explanation">${c.explanation || 'Interesting gaming moment.'}</div>
          <div class="reasons-tags">${tagsHtml}</div>
        </div>
        <div class="card-footer">
          <span class="card-timing">⏱️ ${c.start.toFixed(1)}s - ${c.end.toFixed(1)}s (${c.duration.toFixed(1)}s)</span>
          <button class="btn btn-primary btn-sm btn-edit-clip" data-id="${c.id}">Edit 9:16 ✂️</button>
        </div>
      `;

      card.querySelector('.btn-edit-clip').addEventListener('click', (e) => {
        e.stopPropagation();
        this.openClipEditor(c.id);
      });

      grid.appendChild(card);
    });
  }

  async openClipEditor(clipId) {
    if (!this.currentHighlights) return;
    const cand = this.currentHighlights.candidates.find(c => c.id === clipId);
    if (!cand) return;
    this.activeClip = cand;

    document.getElementById('editorClipTitle').textContent = `Editing ${cand.id}: ${cand.suggested_title || 'Highlight'}`;
    document.getElementById('trimStartInput').value = cand.start.toFixed(1);
    document.getElementById('trimEndInput').value = cand.end.toFixed(1);
    document.getElementById('editorDurationText').textContent = `${cand.duration.toFixed(1)}s`;

    // Initialize Video and Canvas Editor
    const video = document.getElementById('sourceVideo');
    video.src = `/api/projects/${this.currentProjectId}/video`;
    video.currentTime = cand.start;

    if (!this.editor) {
      this.editor = new CanvasEditor('editorCanvas', 'sourceVideo', 'facecamOverlayBox');
    }

    // Load saved clip settings
    try {
      const res = await fetch(`/api/projects/${this.currentProjectId}/clips/${clipId}/settings`);
      if (res.ok) {
        const s = await res.json();
        this.editor.setConfig({
          layout: s.layout || 'split',
          facecam: { x: s.facecam_x, y: s.facecam_y, w: s.facecam_w, h: s.facecam_h },
          gameplayPanX: s.gameplay_pan_x,
          zoomFactor: s.zoom_factor,
          enableSubtitles: s.enable_subtitles,
          subtitleStyle: s.subtitle_style,
          segments: s.segments || []
        });

        // Set inputs
        document.querySelectorAll('.layout-btn').forEach(b => {
          b.classList.toggle('active', b.dataset.layout === s.layout);
        });
        document.getElementById('panRangeInput').value = s.gameplay_pan_x || 0.5;
        document.getElementById('zoomRangeInput').value = s.zoom_factor || 1.0;
        document.getElementById('chkEnableCaptions').checked = s.enable_subtitles !== false;
        document.getElementById('selCaptionStyle').value = s.subtitle_style || 'bold';
        document.getElementById('editorTranscriptText').value = s.full_text || '';
        if (s.start_s) document.getElementById('trimStartInput').value = s.start_s;
        if (s.end_s) document.getElementById('trimEndInput').value = s.end_s;
      }
    } catch (e) {
      console.warn('Clip settings error:', e);
    }

    this.switchView('editorView');
    this.updateScrubberHighlight();
  }

  updateScrubberHighlight() {
    const video = document.getElementById('sourceVideo');
    const s = parseFloat(document.getElementById('trimStartInput').value) || 0;
    const e = parseFloat(document.getElementById('trimEndInput').value) || 0;
    if (video.duration && video.duration > 0) {
      const leftPct = (s / video.duration) * 100;
      const widthPct = ((e - s) / video.duration) * 100;
      const track = document.getElementById('scrubberTrack');
      track.style.left = `${leftPct}%`;
      track.style.width = `${widthPct}%`;
    }
  }

  async transcribeCurrentClip() {
    if (!this.activeClip) return;
    const btn = document.getElementById('btnTranscribeClip');
    btn.textContent = 'Transcribing with Whisper INT8...';
    btn.disabled = true;

    try {
      const res = await fetch(`/api/projects/${this.currentProjectId}/clips/${this.activeClip.id}/transcribe`, {
        method: 'POST'
      });
      const data = await res.json();
      document.getElementById('editorTranscriptText').value = data.full_text || '';
      if (this.editor) {
        this.editor.setConfig({ segments: data.segments || [] });
      }
      alert('Transcription complete! Captions are now active on your 9:16 canvas preview.');
    } catch (e) {
      alert(`Transcription error: ${e.message}`);
    } finally {
      btn.textContent = '🎙️ Transcribe This Clip';
      btn.disabled = false;
    }
  }

  async saveClipSettings() {
    if (!this.activeClip || !this.editor) return;
    const settings = {
      layout: this.editor.config.layout,
      facecam_x: this.editor.config.facecam.x,
      facecam_y: this.editor.config.facecam.y,
      facecam_w: this.editor.config.facecam.w,
      facecam_h: this.editor.config.facecam.h,
      gameplay_pan_x: this.editor.config.gameplayPanX,
      zoom_factor: this.editor.config.zoomFactor,
      start_s: parseFloat(document.getElementById('trimStartInput').value),
      end_s: parseFloat(document.getElementById('trimEndInput').value),
      enable_subtitles: document.getElementById('chkEnableCaptions').checked,
      subtitle_style: document.getElementById('selCaptionStyle').value,
      clip_title: this.activeClip.suggested_title
    };

    try {
      await fetch(`/api/projects/${this.currentProjectId}/clips/${this.activeClip.id}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      });
      alert('Clip settings saved successfully!');
    } catch (e) {
      alert(`Save error: ${e.message}`);
    }
  }

  async exportCurrentClip() {
    if (!this.activeClip || !this.editor) return;
    await this.saveClipSettings();

    const btn = document.getElementById('btnExportClip');
    const origText = btn.innerHTML;
    btn.innerHTML = 'Rendering 1080x1920 MP4...';
    btn.disabled = true;

    try {
      const res = await fetch(`/api/projects/${this.currentProjectId}/clips/${this.activeClip.id}/render`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Rendering failed');
      }
      const data = await res.json();
      alert(`🎉 Export Complete!\nClip saved: ${data.filename} (${data.size_mb} MB)\nPath: ${data.output_path}`);
    } catch (e) {
      alert(`Export failed: ${e.message}`);
    } finally {
      btn.innerHTML = origText;
      btn.disabled = false;
    }
  }

  async openStorageModal() {
    if (!this.currentProjectId) {
      alert('Please select or open a project first.');
      return;
    }
    const modal = document.getElementById('storageModal');
    modal.classList.add('active');

    try {
      const res = await fetch(`/api/projects/${this.currentProjectId}`);
      const data = await res.json();
      const disk = data.disk_usage || {};
      document.getElementById('storageStatsArea').innerHTML = `
        <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
          <span>Source VOD:</span> <b>${disk.source_video_mb || 0} MB</b>
        </div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
          <span>Audio WAV & Cache:</span> <b>${((disk.audio_wav_mb || 0) + (disk.cache_mb || 0)).toFixed(1)} MB</b>
        </div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
          <span>Rendered Exports:</span> <b>${disk.exports_mb || 0} MB</b>
        </div>
        <hr style="border-color: var(--border); margin: 8px 0;">
        <div style="display: flex; justify-content: space-between; font-weight: 700;">
          <span>Total Project Footprint:</span> <b>${disk.total_mb || 0} MB</b>
        </div>
      `;
    } catch (e) {
      console.warn('Storage stats error:', e);
    }
  }

  async runCleanup(deleteSource, deleteCache) {
    if (!this.currentProjectId) return;
    try {
      const res = await fetch(`/api/projects/${this.currentProjectId}/cleanup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ delete_source: deleteSource, delete_cache: deleteCache })
      });
      const data = await res.json();
      alert(`Cleanup finished. Freed ${data.freed_mb} MB of disk space.`);
      this.openStorageModal();
    } catch (e) {
      alert(`Cleanup failed: ${e.message}`);
    }
  }

  async openProjectsModal() {
    const modal = document.getElementById('projectsModal');
    modal.classList.add('active');

    try {
      const res = await fetch('/api/projects');
      const list = await res.json();
      const body = document.getElementById('projectsListBody');

      if (!list || list.length === 0) {
        body.innerHTML = '<p style="color: var(--text-muted);">No projects found.</p>';
        return;
      }

      body.innerHTML = list.map(p => `
        <div style="background: var(--bg-primary); padding: 12px; border-radius: 8px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
          <div>
            <div style="font-weight: 700;">${p.title}</div>
            <div style="font-size: 12px; color: var(--text-muted);">${p.id} · ${(p.duration / 60).toFixed(1)}m · ${p.export_count || 0} clips</div>
          </div>
          <button class="btn btn-sm btn-primary btn-switch-proj" data-id="${p.id}">Open</button>
        </div>
      `).join('');

      body.querySelectorAll('.btn-switch-proj').forEach(btn => {
        btn.addEventListener('click', () => {
          modal.classList.remove('active');
          this.loadProject(btn.dataset.id);
        });
      });
    } catch (e) {
      console.warn('Projects error:', e);
    }
  }
}

window.addEventListener('DOMContentLoaded', () => {
  window.app = new AppController();
});
