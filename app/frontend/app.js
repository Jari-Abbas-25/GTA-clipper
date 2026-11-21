/**
 * GTA Clipper — Application Controller.
 * Manages project state, views, multi-platform video ingestion (Twitch & YouTube),
 * AI provider configuration, and editor integration.
 */

class AppController {
  constructor() {
    this.currentProjectId = null;
    this.currentProjectMeta = null;
    this.currentHighlights = null;
    this.activeClip = null;
    this.editor = null;
    this.pollInterval = null;
    this.probeTimeout = null;
    this.lastRenderedFilename = null;

    this.init();
  }

  async init() {
    this.bindEvents();
    await this.checkSystemStatus();
    await this.loadAiConfig();
    await this.loadDashboardProjects();
    // Do NOT automatically load any project or switch view away from setup dashboard!
  }

  // =========================================================================
  // System & AI Status
  // =========================================================================

  async checkSystemStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      if (data.cpu_cores) {
        document.getElementById('cpuStatusText').textContent = `Core i5 (${data.cpu_cores}T CPU)`;
      }
      this.updateAiHeaderPill(data.ai_mode, data.ai_provider, data.ollama_model);
    } catch (e) {
      console.warn('Status check failed:', e);
    }
  }

  updateAiHeaderPill(mode, provider, model) {
    const dot = document.getElementById('aiDot');
    const text = document.getElementById('aiStatusText');

    if (mode === 'api') {
      dot.className = 'status-dot';
      const pName = provider === 'deepseek' ? 'DeepSeek' : 'OpenRouter';
      text.textContent = `AI: ${pName} API`;
    } else {
      if (provider === 'ollama' && model) {
        dot.className = 'status-dot';
        text.textContent = `AI: Ollama (${model})`;
      } else {
        dot.className = 'status-dot warn';
        text.textContent = 'AI: Local Heuristics';
      }
    }
  }

  // =========================================================================
  // Dashboard Projects List (Clean Empty State & Genuine User Projects)
  // =========================================================================

  async loadDashboardProjects() {
    const container = document.getElementById('dashboardProjectsArea');
    try {
      const res = await fetch('/api/projects');
      const projects = await res.json();

      if (!projects || projects.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon">🎮</div>
            <div class="empty-state-title">No Projects Yet</div>
            <p>Paste a Twitch VOD or YouTube video URL above to detect highlights and generate 9:16 clips.</p>
          </div>
        `;
        return;
      }

      container.innerHTML = projects.map(p => {
        const plat = (p.platform || 'twitch').toLowerCase();
        const platClass = plat === 'youtube' ? 'youtube' : (plat === 'local' ? 'local' : 'twitch');
        const platLabel = plat === 'youtube' ? 'YouTube' : (plat === 'local' ? 'Local' : 'Twitch');
        const durMin = p.duration ? `${(p.duration / 60).toFixed(1)} mins` : '-- mins';
        const exportsCount = p.export_count || 0;

        return `
          <div class="project-card-row">
            <div class="project-card-left">
              <span class="tag ${platClass}">${platLabel}</span>
              <div>
                <div style="font-weight: 700; font-size: 14px; margin-bottom: 2px;">${p.title || p.id}</div>
                <div style="font-size: 12px; color: var(--text-muted);">
                  ⏱️ ${durMin} • 🎬 ${exportsCount} clip(s) • Status: <strong>${p.status}</strong>
                </div>
              </div>
            </div>
            <button class="btn btn-sm btn-primary btn-open-dash-proj" data-id="${p.id}">
              Open Highlights →
            </button>
          </div>
        `;
      }).join('');

      container.querySelectorAll('.btn-open-dash-proj').forEach(btn => {
        btn.addEventListener('click', () => this.loadProject(btn.dataset.id));
      });

    } catch (e) {
      container.innerHTML = '<div style="color: var(--text-muted); font-size: 13px;">Failed to load project list.</div>';
    }
  }

  // =========================================================================
  // Event Binding
  // =========================================================================

  bindEvents() {
    // Navigation
    document.getElementById('btnNewProject').addEventListener('click', () => {
      this.switchView('setupView');
      this.loadDashboardProjects();
    });
    document.getElementById('btnOpenProjects').addEventListener('click', () => this.openProjectsModal());
    document.getElementById('btnOpenStorage').addEventListener('click', () => this.openStorageModal());
    document.getElementById('btnCloseStorageModal').addEventListener('click', () => document.getElementById('storageModal').classList.remove('active'));
    document.getElementById('btnCloseProjectsModal').addEventListener('click', () => document.getElementById('projectsModal').classList.remove('active'));

    // URL Input & Live Platform Detection
    const urlInput = document.getElementById('vodUrlInput');
    urlInput.addEventListener('input', () => this.handleUrlInput(urlInput.value));

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
    document.getElementById('btnSaveAsNative').addEventListener('click', () => this.saveAsNativeDialog());

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

    // AI Settings Modal
    document.getElementById('btnAiSettings').addEventListener('click', () => this.openAiModal());
    document.getElementById('aiStatusPill').addEventListener('click', () => this.openAiModal());
    document.getElementById('btnCloseAiModal').addEventListener('click', () => document.getElementById('aiSettingsModal').classList.remove('active'));
    document.getElementById('btnCancelAiModal').addEventListener('click', () => document.getElementById('aiSettingsModal').classList.remove('active'));

    document.getElementById('tabBtnLocalAi').addEventListener('click', () => this.switchAiTab('local'));
    document.getElementById('tabBtnApiAi').addEventListener('click', () => this.switchAiTab('api'));

    document.getElementById('btnRefreshOllamaModels').addEventListener('click', () => this.refreshOllamaModels());
    document.getElementById('btnResetApiUrl').addEventListener('click', () => this.resetApiUrlDefault());
    document.getElementById('selApiProvider').addEventListener('change', () => this.handleApiProviderChange());
    document.getElementById('btnToggleApiKey').addEventListener('click', () => this.toggleApiKeyVisibility());
    document.getElementById('btnTestAiConnection').addEventListener('click', () => this.testAiConnection());
    document.getElementById('btnSaveAiConfig').addEventListener('click', () => this.saveAiConfiguration());
  }

  switchView(viewId) {
    document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
    const target = document.getElementById(viewId);
    if (target) target.classList.add('active');
  }

  // =========================================================================
  // Multi-Platform URL Detection & Probe
  // =========================================================================

  handleUrlInput(val) {
    const clean = val.trim();
    const badge = document.getElementById('platformBadge');
    const previewCard = document.getElementById('videoPreviewCard');

    if (!clean) {
      badge.textContent = 'Detecting URL...';
      badge.className = 'platform-indicator';
      previewCard.style.display = 'none';
      return;
    }

    if (clean.includes('twitch.tv') || /^\d{6,}$/.test(clean)) {
      badge.textContent = '🟣 Twitch VOD';
      badge.className = 'platform-indicator twitch';
    } else if (clean.includes('youtube.com') || clean.includes('youtu.be')) {
      badge.textContent = '🔴 YouTube Video';
      badge.className = 'platform-indicator youtube';
    } else {
      badge.textContent = '📁 Local File';
      badge.className = 'platform-indicator local';
    }

    // Debounce probe to preview video info
    if (this.probeTimeout) clearTimeout(this.probeTimeout);
    if (clean.startsWith('http') || clean.length > 5) {
      this.probeTimeout = setTimeout(() => this.probeVideo(clean), 700);
    }
  }

  async probeVideo(url) {
    try {
      const res = await fetch('/api/probe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url_or_path: url })
      });
      if (!res.ok) return;

      const data = await res.json();
      const card = document.getElementById('videoPreviewCard');
      document.getElementById('previewTitle').textContent = data.title || 'Untitled Video';
      document.getElementById('previewUploader').textContent = data.uploader || 'Creator';
      document.getElementById('previewDuration').textContent = data.duration ? `${(data.duration / 60).toFixed(1)} mins` : '-- mins';

      const tag = document.getElementById('previewPlatformBadge');
      tag.textContent = data.platform.toUpperCase();
      tag.className = `tag ${data.platform}`;

      const thumb = document.getElementById('previewThumbnail');
      if (data.thumbnail) {
        thumb.src = data.thumbnail;
        thumb.style.display = 'block';
      } else {
        thumb.style.display = 'none';
      }

      card.style.display = 'flex';
    } catch (e) {
      // Ignore background probe failure
    }
  }

  // =========================================================================
  // Ingest & Background Progress
  // =========================================================================

  async startIngest() {
    const input = document.getElementById('vodUrlInput').value.trim();
    if (!input) {
      alert('Please enter a Twitch VOD URL or YouTube video URL.');
      return;
    }

    document.getElementById('progressCard').style.display = 'block';
    this.updateProgress(5, 'Probing video & setting up project...');

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
    // Explicit offline demonstration trigger
    document.getElementById('progressCard').style.display = 'block';
    this.updateProgress(50, 'Loading sample GTA 6 highlight fixture...');

    try {
      const res = await fetch('/api/projects/create-demo', { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to create demo project');
      }
      const data = await res.json();
      this.currentProjectId = data.project_id;
      document.getElementById('progressCard').style.display = 'none';
      await this.loadProject(data.project_id);
    } catch (e) {
      alert(`Failed to load sample clip: ${e.message}`);
      document.getElementById('progressCard').style.display = 'none';
    }
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
          // Trigger analysis automatically after download completes
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

  // =========================================================================
  // Load Project Highlights
  // =========================================================================

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

      // Platform & Chat Tag
      const plat = (data.meta.platform || 'twitch').toLowerCase();
      const pTag = document.getElementById('highlightPlatformTag');
      pTag.textContent = plat.toUpperCase();
      pTag.className = `tag ${plat}`;

      const chatText = document.getElementById('chatStatusText');
      if (data.meta.chat_status === 'downloaded') {
        chatText.textContent = `Replay (${data.meta.chat_message_count || 0} msgs)`;
      } else {
        chatText.textContent = 'None (Audio-Only Mode)';
      }

      document.getElementById('aiProviderUsedText').textContent = (data.meta.ai_provider || 'Heuristics').toUpperCase();

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

    if (this.currentHighlights && this.currentHighlights.candidates) {
      const dur = this.currentHighlights.duration;
      this.currentHighlights.candidates.forEach(c => {
        const x1 = (c.start / dur) * w;
        const x2 = (c.end / dur) * w;
        ctx.fillStyle = 'rgba(251, 191, 36, 0.35)';
        ctx.fillRect(x1, 0, Math.max(3, x2 - x1), h);

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

  // =========================================================================
  // Clip Editor
  // =========================================================================

  async openClipEditor(clipId) {
    if (!this.currentHighlights) return;
    const cand = this.currentHighlights.candidates.find(c => c.id === clipId);
    if (!cand) return;
    this.activeClip = cand;

    document.getElementById('editorClipTitle').textContent = `Editing ${cand.id}: ${cand.suggested_title || 'Highlight'}`;
    document.getElementById('trimStartInput').value = cand.start.toFixed(1);
    document.getElementById('trimEndInput').value = cand.end.toFixed(1);
    document.getElementById('editorDurationText').textContent = `${cand.duration.toFixed(1)}s`;
    document.getElementById('exportSuccessBar').style.display = 'none';

    const video = document.getElementById('sourceVideo');
    video.src = `/api/projects/${this.currentProjectId}/video`;
    video.currentTime = cand.start;

    if (!this.editor) {
      this.editor = new CanvasEditor('editorCanvas', 'sourceVideo', 'facecamOverlayBox');
    }

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
      this.lastRenderedFilename = data.filename;

      // Reveal export success bar with Save As and Download actions
      const bar = document.getElementById('exportSuccessBar');
      document.getElementById('exportedFilename').textContent = data.filename;
      document.getElementById('exportedSize').textContent = `${data.size_mb} MB`;
      document.getElementById('exportSavedPathText').textContent = `Default export: ${data.output_path}`;

      const dlBtn = document.getElementById('btnDownloadExport');
      dlBtn.href = `/api/exports/${this.currentProjectId}/${data.filename}?download=true`;

      bar.style.display = 'flex';
      alert(`🎉 Render Complete!\nClip: ${data.filename} (${data.size_mb} MB)\nUse 'Save As' below to select your desired folder on disk.`);
    } catch (e) {
      alert(`Export failed: ${e.message}`);
    } finally {
      btn.innerHTML = origText;
      btn.disabled = false;
    }
  }

  async saveAsNativeDialog() {
    if (!this.currentProjectId || !this.activeClip) return;
    try {
      const res = await fetch(`/api/exports/${this.currentProjectId}/${this.activeClip.id}/save-dialog`, {
        method: 'POST'
      });
      const data = await res.json();
      if (data.status === 'saved') {
        document.getElementById('exportSavedPathText').textContent = `Saved to: ${data.path}`;
        alert(`🎉 Successfully saved clip to:\n${data.path}`);
      }
    } catch (e) {
      alert(`Save As failed: ${e.message}`);
    }
  }

  // =========================================================================
  // AI Settings Modal
  // =========================================================================

  async openAiModal() {
    const modal = document.getElementById('aiSettingsModal');
    modal.classList.add('active');
    await this.loadAiConfig();
    this.refreshOllamaModels();
  }

  switchAiTab(tab) {
    const localBtn = document.getElementById('tabBtnLocalAi');
    const apiBtn = document.getElementById('tabBtnApiAi');
    const localContent = document.getElementById('tabContentLocalAi');
    const apiContent = document.getElementById('tabContentApiAi');

    if (tab === 'local') {
      localBtn.classList.add('active');
      apiBtn.classList.remove('active');
      localContent.style.display = 'block';
      apiContent.style.display = 'none';
    } else {
      apiBtn.classList.add('active');
      localBtn.classList.remove('active');
      apiContent.style.display = 'block';
      localContent.style.display = 'none';
    }
  }

  async loadAiConfig() {
    try {
      const res = await fetch('/api/ai/config');
      const cfg = await res.json();

      this.switchAiTab(cfg.mode === 'api' ? 'api' : 'local');

      // Local
      document.getElementById('aiOllamaUrlInput').value = cfg.ollama_url || 'http://localhost:11434';

      // API
      document.getElementById('selApiProvider').value = cfg.provider === 'openrouter' ? 'openrouter' : 'deepseek';
      this.handleApiProviderChange();

      if (cfg.provider === 'openrouter') {
        document.getElementById('aiApiUrlInput').value = cfg.openrouter_url || 'https://openrouter.ai/api/v1';
        document.getElementById('aiApiModelInput').value = cfg.openrouter_model || 'deepseek/deepseek-chat';
        document.getElementById('aiApiKeyInput').value = cfg.openrouter_key_masked || '';
      } else {
        document.getElementById('aiApiUrlInput').value = cfg.deepseek_url || 'https://api.deepseek.com/v1';
        document.getElementById('aiApiModelInput').value = cfg.deepseek_model || 'deepseek-chat';
        document.getElementById('aiApiKeyInput').value = cfg.deepseek_key_masked || '';
      }

      this.updateAiHeaderPill(cfg.mode, cfg.provider, cfg.ollama_model);
    } catch (e) {
      console.warn('AI config load failed:', e);
    }
  }

  handleApiProviderChange() {
    const prov = document.getElementById('selApiProvider').value;
    const urlIn = document.getElementById('aiApiUrlInput');
    const modelIn = document.getElementById('aiApiModelInput');
    const hint = document.getElementById('apiModelHint');

    if (prov === 'deepseek') {
      urlIn.value = 'https://api.deepseek.com/v1';
      modelIn.value = 'deepseek-chat';
      hint.innerHTML = 'Default: <code>deepseek-chat</code>';
    } else {
      urlIn.value = 'https://openrouter.ai/api/v1';
      modelIn.value = 'deepseek/deepseek-chat';
      hint.innerHTML = 'Default: <code>deepseek/deepseek-chat</code> or <code>meta-llama/llama-3.2-3b-instruct:free</code>';
    }
  }

  resetApiUrlDefault() {
    const prov = document.getElementById('selApiProvider').value;
    document.getElementById('aiApiUrlInput').value = prov === 'deepseek' ? 'https://api.deepseek.com/v1' : 'https://openrouter.ai/api/v1';
  }

  toggleApiKeyVisibility() {
    const keyIn = document.getElementById('aiApiKeyInput');
    keyIn.type = keyIn.type === 'password' ? 'text' : 'password';
  }

  async refreshOllamaModels() {
    const badge = document.getElementById('ollamaStatusBadge');
    const sel = document.getElementById('selOllamaModel');
    const url = document.getElementById('aiOllamaUrlInput').value.trim();

    badge.textContent = 'Probing...';
    badge.className = 'tag';

    try {
      const res = await fetch(`/api/ai/ollama/models?url=${encodeURIComponent(url)}`);
      const data = await res.json();

      if (data.online) {
        badge.textContent = `Online (${data.models.length} models)`;
        badge.className = 'tag local';

        if (data.models && data.models.length > 0) {
          sel.innerHTML = data.models.map(m => `<option value="${m}">${m} ${m === data.recommended ? '(Recommended)' : ''}</option>`).join('');
          if (data.recommended) sel.value = data.recommended;
        } else {
          sel.innerHTML = '<option value="">(No models installed - heuristics will run)</option>';
        }
      } else {
        badge.textContent = 'Offline (Heuristics Active)';
        badge.className = 'tag';
        sel.innerHTML = '<option value="">(Ollama daemon not running)</option>';
      }
    } catch (e) {
      badge.textContent = 'Offline';
    }
  }

  async testAiConnection() {
    const prov = document.getElementById('selApiProvider').value;
    const url = document.getElementById('aiApiUrlInput').value.trim();
    const model = document.getElementById('aiApiModelInput').value.trim();
    const key = document.getElementById('aiApiKeyInput').value.trim();
    const statusText = document.getElementById('aiTestResult');

    statusText.textContent = 'Testing connection...';
    statusText.style.color = 'var(--text-muted)';

    try {
      const res = await fetch('/api/ai/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: prov, base_url: url, model: model, api_key: key })
      });
      const data = await res.json();
      if (data.success) {
        statusText.textContent = `✅ ${data.message}`;
        statusText.style.color = 'var(--accent-green)';
      } else {
        statusText.textContent = `⚠️ ${data.message}`;
        statusText.style.color = 'var(--accent-red)';
      }
    } catch (e) {
      statusText.textContent = `Error: ${e.message}`;
      statusText.style.color = 'var(--accent-red)';
    }
  }

  async saveAiConfiguration() {
    const isApi = document.getElementById('tabBtnApiAi').classList.contains('active');
    const prov = isApi ? document.getElementById('selApiProvider').value : 'ollama';

    const payload = {
      mode: isApi ? 'api' : 'local',
      provider: prov
    };

    if (isApi) {
      if (prov === 'deepseek') {
        payload.deepseek_url = document.getElementById('aiApiUrlInput').value.trim();
        payload.deepseek_model = document.getElementById('aiApiModelInput').value.trim();
        const key = document.getElementById('aiApiKeyInput').value.trim();
        if (key && !key.includes('****')) payload.deepseek_key = key;
      } else {
        payload.openrouter_url = document.getElementById('aiApiUrlInput').value.trim();
        payload.openrouter_model = document.getElementById('aiApiModelInput').value.trim();
        const key = document.getElementById('aiApiKeyInput').value.trim();
        if (key && !key.includes('****')) payload.openrouter_key = key;
      }
    } else {
      payload.ollama_url = document.getElementById('aiOllamaUrlInput').value.trim();
      payload.ollama_model = document.getElementById('selOllamaModel').value;
    }

    try {
      const res = await fetch('/api/ai/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      alert('AI Configuration saved successfully!');
      document.getElementById('aiSettingsModal').classList.remove('active');
      this.updateAiHeaderPill(data.config.mode, data.config.provider, data.config.ollama_model);
    } catch (e) {
      alert(`Save error: ${e.message}`);
    }
  }

  // =========================================================================
  // Storage Modal
  // =========================================================================

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

  // =========================================================================
  // Projects Modal
  // =========================================================================

  async openProjectsModal() {
    const modal = document.getElementById('projectsModal');
    modal.classList.add('active');

    try {
      const res = await fetch('/api/projects');
      const list = await res.json();
      const body = document.getElementById('projectsListBody');

      if (!list || list.length === 0) {
        body.innerHTML = '<p style="color: var(--text-muted); padding: 12px;">No projects found.</p>';
        return;
      }

      body.innerHTML = list.map(p => {
        const plat = (p.platform || 'twitch').toLowerCase();
        const platClass = plat === 'youtube' ? 'youtube' : (plat === 'local' ? 'local' : 'twitch');
        return `
          <div style="background: var(--bg-primary); padding: 12px; border-radius: 8px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
            <div>
              <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                <span class="tag ${platClass}">${plat.toUpperCase()}</span>
                <strong>${p.title || p.id}</strong>
              </div>
              <div style="font-size: 12px; color: var(--text-muted);">${(p.duration / 60).toFixed(1)} mins • ${p.export_count || 0} exports</div>
            </div>
            <button class="btn btn-sm btn-primary btn-switch-proj" data-id="${p.id}">Open</button>
          </div>
        `;
      }).join('');

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
