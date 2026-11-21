/**
 * GTA Clipper — Advanced Application Controller.
 * Manages project state, views, multi-platform video ingestion (Twitch & YouTube),
 * First-Launch AI Configuration, Real AI Highlight Detection Tuning,
 * Timeline-based Multi-Section Editing, and External Destination Exporting.
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
    this.lastRenderedPath = null;
    this.lastRenderedFilename = null;
    this.aiConfig = null;

    this.init();
  }

  async init() {
    this.bindEvents();
    await this.checkSystemStatus();
    await this.loadAiConfig();
    await this.loadDashboardProjects();

    // Check First-Launch AI Setup: if not configured, show initial setup modal BEFORE anything else
    if (!this.aiConfig || !this.aiConfig.configured) {
      this.openFirstLaunchModal();
    }
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

  async loadAiConfig() {
    try {
      const res = await fetch('/api/ai/config');
      this.aiConfig = await res.json();
      return this.aiConfig;
    } catch (e) {
      console.warn('Load AI config error:', e);
      return null;
    }
  }

  // =========================================================================
  // First-Launch AI Setup Screen (Mandatory Onboarding)
  // =========================================================================

  openFirstLaunchModal() {
    const modal = document.getElementById('aiFirstLaunchModal');
    modal.classList.add('active');
    this.refreshFirstLaunchOllama();
  }

  async refreshFirstLaunchOllama() {
    const badge = document.getElementById('flOllamaBadge');
    const sel = document.getElementById('flOllamaModelSelect');
    const url = document.getElementById('flOllamaUrlInput').value.trim();

    badge.textContent = 'Probing...';
    badge.className = 'tag';

    try {
      const res = await fetch(`/api/ai/ollama/models?url=${encodeURIComponent(url)}`);
      const data = await res.json();

      if (data.online) {
        badge.textContent = `Online (${data.models.length} models)`;
        badge.className = 'tag local';

        if (data.model_details && data.model_details.length > 0) {
          sel.innerHTML = data.model_details.map(m => {
            const recText = m.recommended ? ' ★ RECOMMENDED' : '';
            return `<option value="${m.name}">${m.name} — ${m.size} (${m.ram})${recText}</option>`;
          }).join('');
          if (data.recommended) sel.value = data.recommended;
          this.updateFirstLaunchModelInfo(sel.value, data.specs);
        } else {
          sel.innerHTML = '<option value="">(No models installed - rule-based heuristics will run)</option>';
        }
      } else {
        badge.textContent = 'Offline (Heuristics Active)';
        badge.className = 'tag';
        sel.innerHTML = '<option value="">(Ollama daemon offline - heuristics active)</option>';
      }
    } catch (e) {
      badge.textContent = 'Offline';
    }
  }

  updateFirstLaunchModelInfo(modelName, specs) {
    const info = document.getElementById('flModelReqInfo');
    if (!specs || !modelName) return;
    const spec = specs[modelName];
    if (spec) {
      info.textContent = `Selected: ${modelName} | Size: ${spec.size} | RAM: ${spec.ram} — ${spec.desc}`;
    }
  }

  async testFirstLaunchApi() {
    const prov = document.getElementById('flApiProviderSelect').value;
    const model = document.getElementById('flApiModelInput').value.trim();
    const key = document.getElementById('flApiKeyInput').value.trim();
    const statusText = document.getElementById('flTestStatusText');

    statusText.textContent = 'Testing connection...';
    statusText.style.color = 'var(--text-muted)';

    try {
      const res = await fetch('/api/ai/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: prov, model: model, api_key: key })
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

  async saveFirstLaunchConfig() {
    const isApi = document.getElementById('firstLaunchTabApi').classList.contains('active');
    const prov = isApi ? document.getElementById('flApiProviderSelect').value : 'ollama';

    const payload = {
      mode: isApi ? 'api' : 'local',
      provider: prov,
      configured: true
    };

    if (isApi) {
      if (prov === 'deepseek') {
        payload.deepseek_model = document.getElementById('flApiModelInput').value.trim();
        const key = document.getElementById('flApiKeyInput').value.trim();
        if (key && !key.includes('****')) payload.deepseek_key = key;
      } else {
        payload.openrouter_model = document.getElementById('flApiModelInput').value.trim();
        const key = document.getElementById('flApiKeyInput').value.trim();
        if (key && !key.includes('****')) payload.openrouter_key = key;
      }
    } else {
      payload.ollama_url = document.getElementById('flOllamaUrlInput').value.trim();
      payload.ollama_model = document.getElementById('flOllamaModelSelect').value;
    }

    try {
      const res = await fetch('/api/ai/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      this.aiConfig = data.config;
      document.getElementById('aiFirstLaunchModal').classList.remove('active');
      this.updateAiHeaderPill(data.config.mode, data.config.provider, data.config.ollama_model);
      alert('AI Configuration complete! You can now paste your VOD or YouTube URL.');
    } catch (e) {
      alert(`Save error: ${e.message}`);
    }
  }

  // =========================================================================
  // Dashboard & Projects List
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
            <p>Paste a Twitch VOD or YouTube video URL above to detect highlights and generate clips.</p>
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

    // First-Launch Modal Tabs & Actions
    document.getElementById('firstLaunchTabLocal').addEventListener('click', () => {
      document.getElementById('firstLaunchTabLocal').classList.add('active');
      document.getElementById('firstLaunchTabApi').classList.remove('active');
      document.getElementById('firstLaunchContentLocal').style.display = 'block';
      document.getElementById('firstLaunchContentApi').style.display = 'none';
    });
    document.getElementById('firstLaunchTabApi').addEventListener('click', () => {
      document.getElementById('firstLaunchTabApi').classList.add('active');
      document.getElementById('firstLaunchTabLocal').classList.remove('active');
      document.getElementById('firstLaunchContentApi').style.display = 'block';
      document.getElementById('firstLaunchContentLocal').style.display = 'none';
    });
    document.getElementById('btnFlTestConnection').addEventListener('click', () => this.testFirstLaunchApi());
    document.getElementById('btnSaveFirstLaunchAi').addEventListener('click', () => this.saveFirstLaunchConfig());

    // URL Input & Probe
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

    // Editor View Navigation & Header Actions
    document.getElementById('btnBackToHighlights').addEventListener('click', () => this.switchView('highlightsView'));
    document.getElementById('btnSaveClipSettings').addEventListener('click', () => this.saveClipSettings());
    document.getElementById('btnOpenExportModal').addEventListener('click', () => this.openExportModal());
    document.getElementById('btnCloseExportModal').addEventListener('click', () => document.getElementById('exportModal').classList.remove('active'));
    document.getElementById('btnCancelExportModal').addEventListener('click', () => document.getElementById('exportModal').classList.remove('active'));
    document.getElementById('btnBrowseExportDest').addEventListener('click', () => this.browseExportDestination());
    document.getElementById('btnStartRenderExport').addEventListener('click', () => this.startRenderExport());
    document.getElementById('btnOpenExportFolder').addEventListener('click', () => this.openExportFolder());
    document.getElementById('btnSaveAsNative').addEventListener('click', () => this.saveAsNativeDialog());

    // Aspect Ratio Switching
    document.getElementById('btnAspect916').addEventListener('click', () => this.setEditorAspect('9:16'));
    document.getElementById('btnAspect169').addEventListener('click', () => this.setEditorAspect('16:9'));

    // Canvas playback controls
    const video = document.getElementById('sourceVideo');
    document.getElementById('btnCanvasPlayPause').addEventListener('click', () => {
      if (video.paused) video.play();
      else video.pause();
    });
    document.getElementById('btnResetCanvasTime').addEventListener('click', () => {
      if (this.editor) {
        video.currentTime = this.editor.clipStart;
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
      if (video.duration && this.editor) {
        const pct = (video.currentTime / video.duration) * 100;
        document.getElementById('scrubberPlayhead').style.left = `${pct}%`;
        const relTime = Math.max(0.0, video.currentTime - this.editor.clipStart);
        document.getElementById('editorCurrentTimeText').textContent = `${relTime.toFixed(1)}s`;
        this.renderTimelineSections();
      }
    });

    // Multi-Section Timeline Operations
    document.getElementById('btnSplitSection').addEventListener('click', () => {
      if (this.editor) {
        const curOffset = Math.max(0.0, video.currentTime - this.editor.clipStart);
        const ok = this.editor.splitSectionAt(curOffset);
        if (ok) {
          this.renderTimelineSections();
          this.syncPropertiesPanel();
        } else {
          alert('Cannot split section here. Place playhead at least 1s inside a section.');
        }
      }
    });

    document.getElementById('btnDeleteSection').addEventListener('click', () => {
      if (this.editor) {
        if (confirm('Delete the active timeline section and merge with adjacent?')) {
          this.editor.deleteActiveSection();
          this.renderTimelineSections();
          this.syncPropertiesPanel();
        }
      }
    });

    document.getElementById('btnAiSuggestEdits').addEventListener('click', () => this.generateAiSuggestionsForClip());
    document.getElementById('btnResetSections').addEventListener('click', () => {
      if (this.editor && confirm('Reset timeline to a single uniform layout?')) {
        this.editor.initDefaultSection();
        this.renderTimelineSections();
        this.syncPropertiesPanel();
      }
    });

    document.getElementById('btnApplySecTrim').addEventListener('click', () => {
      if (this.editor) {
        const sec = this.editor.getActiveSection();
        if (sec) {
          sec.start = parseFloat(document.getElementById('secStartInput').value) || 0.0;
          sec.end = parseFloat(document.getElementById('secEndInput').value) || 30.0;
          this.editor.drawFrame();
          this.renderTimelineSections();
        }
      }
    });

    // Clip Window Trim
    const startIn = document.getElementById('trimStartInput');
    const endIn = document.getElementById('trimEndInput');
    const updateTrim = () => {
      const s = parseFloat(startIn.value) || 0;
      const e = parseFloat(endIn.value) || 0;
      document.getElementById('editorDurationText').textContent = `${Math.max(0, e - s).toFixed(1)}s`;
      if (this.editor) {
        this.editor.clipStart = s;
        this.editor.clipEnd = e;
      }
      this.updateScrubberHighlight();
      this.renderTimelineRuler();
    };
    startIn.addEventListener('input', updateTrim);
    endIn.addEventListener('input', updateTrim);

    document.getElementById('btnNudgeStartMinus1').addEventListener('click', () => { startIn.value = Math.max(0, (parseFloat(startIn.value) - 1.0)).toFixed(1); updateTrim(); });
    document.getElementById('btnNudgeStartPlus1').addEventListener('click', () => { startIn.value = (parseFloat(startIn.value) + 1.0).toFixed(1); updateTrim(); });
    document.getElementById('btnNudgeEndMinus1').addEventListener('click', () => { endIn.value = Math.max(0, (parseFloat(endIn.value) - 1.0)).toFixed(1); updateTrim(); });
    document.getElementById('btnNudgeEndPlus1').addEventListener('click', () => { endIn.value = (parseFloat(endIn.value) + 1.0).toFixed(1); updateTrim(); });

    // Properties Panel Tabs
    document.getElementById('tabPropGameplay').addEventListener('click', () => this.switchPropTab('gameplay'));
    document.getElementById('tabPropStreamer').addEventListener('click', () => this.switchPropTab('streamer'));
    document.getElementById('tabPropLayout').addEventListener('click', () => this.switchPropTab('layout'));

    // Gameplay Element Controls
    const gpZoom = document.getElementById('gameplayZoomInput');
    const gpPanX = document.getElementById('gameplayPanXInput');
    const gpPosY = document.getElementById('gameplayPosYInput');

    gpZoom.addEventListener('input', () => {
      document.getElementById('txtGameplayZoom').textContent = `${parseFloat(gpZoom.value).toFixed(2)}x`;
      if (this.editor) {
        const sec = this.editor.getActiveSection();
        sec.gameplay.zoom = parseFloat(gpZoom.value);
        this.editor.drawFrame();
      }
    });
    gpPanX.addEventListener('input', () => {
      if (this.editor) {
        const sec = this.editor.getActiveSection();
        sec.gameplay.pan_x = parseFloat(gpPanX.value);
        this.editor.drawFrame();
      }
    });
    gpPosY.addEventListener('input', () => {
      if (this.editor) {
        const sec = this.editor.getActiveSection();
        sec.gameplay.y = parseFloat(gpPosY.value);
        this.editor.updateOverlayBoxPosition();
        this.editor.drawFrame();
      }
    });
    document.getElementById('btnResetGameplay').addEventListener('click', () => {
      gpZoom.value = 1.0;
      gpPanX.value = 0.5;
      document.getElementById('txtGameplayZoom').textContent = '1.0x';
      if (this.editor) {
        const sec = this.editor.getActiveSection();
        sec.gameplay.zoom = 1.0;
        sec.gameplay.pan_x = 0.5;
        this.editor.drawFrame();
      }
    });

    // Streamer Element Controls
    document.getElementById('chkStreamerEnabled').addEventListener('change', (e) => {
      if (this.editor) {
        const sec = this.editor.getActiveSection();
        sec.streamer.enabled = e.target.checked;
        this.editor.updateOverlayBoxPosition();
        this.editor.drawFrame();
      }
    });
    const stZoom = document.getElementById('streamerZoomInput');
    stZoom.addEventListener('input', () => {
      document.getElementById('txtStreamerZoom').textContent = `${parseFloat(stZoom.value).toFixed(2)}x`;
      if (this.editor) {
        const sec = this.editor.getActiveSection();
        sec.streamer.zoom = parseFloat(stZoom.value);
        this.editor.drawFrame();
      }
    });
    const stBorder = document.getElementById('streamerBorderInput');
    stBorder.addEventListener('input', () => {
      document.getElementById('txtStreamerBorder').textContent = `${stBorder.value}px`;
      if (this.editor) {
        const sec = this.editor.getActiveSection();
        sec.streamer.border_w = parseInt(stBorder.value, 10);
        this.editor.drawFrame();
      }
    });
    const stRadius = document.getElementById('streamerRadiusInput');
    stRadius.addEventListener('input', () => {
      document.getElementById('txtStreamerRadius').textContent = `${stRadius.value}px`;
      if (this.editor) {
        const sec = this.editor.getActiveSection();
        sec.streamer.corner_radius = parseInt(stRadius.value, 10);
        this.editor.drawFrame();
      }
    });
    document.querySelectorAll('.swatch-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.swatch-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        if (this.editor) {
          const sec = this.editor.getActiveSection();
          sec.streamer.border_color = btn.dataset.color;
          this.editor.updateOverlayBoxPosition();
          this.editor.drawFrame();
        }
      });
    });
    document.getElementById('btnResetStreamer').addEventListener('click', () => {
      if (this.editor) {
        const sec = this.editor.getActiveSection();
        sec.streamer.x = 0.65;
        sec.streamer.y = 0.05;
        sec.streamer.w = 0.30;
        sec.streamer.h = 0.25;
        sec.streamer.zoom = 1.0;
        sec.streamer.corner_radius = 8;
        sec.streamer.border_w = 2;
        this.editor.updateOverlayBoxPosition();
        this.editor.drawFrame();
        this.syncPropertiesPanel();
      }
    });

    // Auto-detect Facecam
    document.getElementById('btnAutoDetectFacecam').addEventListener('click', () => {
      if (this.currentProjectMeta && this.currentProjectMeta.facecam_region) {
        const fc = this.currentProjectMeta.facecam_region;
        if (this.editor) {
          const sec = this.editor.getActiveSection();
          sec.streamer.crop_x = fc.x;
          sec.streamer.crop_y = fc.y;
          sec.streamer.crop_w = fc.w;
          sec.streamer.crop_h = fc.h;
          this.editor.drawFrame();
        }
        alert('Webcam coordinates mapped to streamer facecam box!');
      } else {
        alert('Default gaming webcam coordinates applied (Top-Right facecam).');
      }
    });

    // Layout Buttons for Active Section
    document.querySelectorAll('.layout-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.layout-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        if (this.editor) {
          this.editor.setActiveSectionLayout(btn.dataset.layout);
          this.renderTimelineSections();
        }
      });
    });

    // Background & Subtitles
    document.getElementById('selBackgroundStyle').addEventListener('change', (e) => {
      if (this.editor) {
        const sec = this.editor.getActiveSection();
        sec.background.type = e.target.value === 'blur' ? 'blur' : 'color';
        sec.background.color = e.target.value === 'darkblue' ? '#0a0e17' : '#000000';
        this.editor.drawFrame();
      }
    });

    document.getElementById('selCaptionStyle').addEventListener('change', (e) => {
      if (this.editor) this.editor.config.subtitle_style = e.target.value;
    });
    document.getElementById('chkEnableCaptions').addEventListener('change', (e) => {
      if (this.editor) this.editor.config.enable_subtitles = e.target.checked;
    });

    // Transcription
    document.getElementById('btnTranscribeClip').addEventListener('click', () => this.transcribeCurrentClip());

    // Storage Actions
    document.getElementById('btnCleanCache').addEventListener('click', () => this.runCleanup(false, true));
    document.getElementById('btnDeleteSource').addEventListener('click', () => {
      if (confirm('Are you sure you want to delete the source video? Finished exports will be preserved.')) {
        this.runCleanup(true, true);
      }
    });

    // AI Settings Modal (Header)
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
      // Ignore background probe error
    }
  }

  // =========================================================================
  // Ingest & Highlight Detection
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

    const payload = {
      target_count: parseInt(document.getElementById('selTargetCount').value, 10) || 6,
      sensitivity: document.getElementById('selSensitivity').value || 'medium',
      focus_mode: document.getElementById('selFocusMode').value || 'all',
      min_duration: parseFloat(document.getElementById('inpMinDur').value) || 15.0,
      max_duration: parseFloat(document.getElementById('inpMaxDur').value) || 45.0,
    };

    try {
      await fetch(`/api/projects/${this.currentProjectId}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
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
  // Load Project & Candidates Screen
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
      card.className = `candidate-card ${c.accepted === false ? 'deselected' : ''}`;
      card.id = `card_${c.id}`;

      const tagsHtml = (c.reasons || []).map(r => {
        let cls = 'tag';
        if (r.code.includes('chat')) cls += ' chat';
        else if (r.code.includes('laughter')) cls += ' laughter';
        else cls += ' audio';
        return `<span class="${cls}">${r.code}: ${r.value}</span>`;
      }).join('');

      const segCount = (c.edit_suggestions && c.edit_suggestions.length) || 3;

      card.innerHTML = `
        <div class="card-top">
          <div style="display: flex; align-items: center; gap: 8px;">
            <input type="checkbox" class="chk-select-cand" data-id="${c.id}" ${c.accepted !== false ? 'checked' : ''} title="Include in review">
            <span class="card-rank">#${c.rank} (${c.id})</span>
          </div>
          <span class="card-score-badge">HYPE ${c.hype_score}/100</span>
        </div>
        <div class="card-body">
          <div class="card-title">${c.suggested_title || 'Gaming Highlight'}</div>
          <div class="card-explanation">${c.explanation || 'Interesting gaming moment.'}</div>
          <div class="reasons-tags">${tagsHtml}</div>
          <div class="ai-edit-badge">⚡ ${segCount} AI Timeline Transitions Prepared</div>
        </div>
        <div class="card-footer">
          <span class="card-timing">⏱️ ${c.start.toFixed(1)}s - ${c.end.toFixed(1)}s (${c.duration.toFixed(1)}s)</span>
          <div style="display: flex; gap: 6px;">
            <button class="btn btn-sm btn-edit-clip" data-id="${c.id}">Edit Clip ✂️</button>
            <button class="btn btn-sm btn-danger btn-remove-cand" data-id="${c.id}">✕</button>
          </div>
        </div>
      `;

      card.querySelector('.chk-select-cand').addEventListener('change', (e) => {
        c.accepted = e.target.checked;
        card.classList.toggle('deselected', !c.accepted);
      });

      card.querySelector('.btn-edit-clip').addEventListener('click', (e) => {
        e.stopPropagation();
        this.openClipEditor(c.id);
      });

      card.querySelector('.btn-remove-cand').addEventListener('click', (e) => {
        e.stopPropagation();
        if (confirm(`Remove highlight #${c.rank}?`)) {
          this.currentHighlights.candidates = this.currentHighlights.candidates.filter(item => item.id !== c.id);
          this.renderCandidates(this.currentHighlights.candidates);
        }
      });

      grid.appendChild(card);
    });
  }

  // =========================================================================
  // Clip Editor & Multi-Section Timeline
  // =========================================================================

  async openClipEditor(clipId) {
    if (!this.currentHighlights) return;
    const cand = this.currentHighlights.candidates.find(c => c.id === clipId);
    if (!cand) return;
    this.activeClip = cand;

    document.getElementById('editorClipTitleInput').value = cand.suggested_title || `Highlight ${cand.id}`;
    document.getElementById('trimStartInput').value = cand.start.toFixed(1);
    document.getElementById('trimEndInput').value = cand.end.toFixed(1);
    document.getElementById('editorDurationText').textContent = `${cand.duration.toFixed(1)}s`;
    document.getElementById('exportSuccessBar').style.display = 'none';

    const video = document.getElementById('sourceVideo');
    video.src = `/api/projects/${this.currentProjectId}/video`;
    video.currentTime = cand.start;

    if (!this.editor) {
      this.editor = new CanvasEditor('editorCanvas', 'sourceVideo', 'facecamOverlayBox');
      this.editor.onSectionChanged = (idx, sec) => {
        this.renderTimelineSections();
        this.syncPropertiesPanel();
      };
      this.editor.onPropertiesChanged = (sec) => {
        this.syncPropertiesPanel();
      };
    }

    this.editor.clipStart = cand.start;
    this.editor.clipEnd = cand.end;

    try {
      const res = await fetch(`/api/projects/${this.currentProjectId}/clips/${clipId}/settings`);
      if (res.ok) {
        const s = await res.json();
        this.editor.setConfig({
          layout: s.layout || 'split',
          aspect_ratio: s.aspect_ratio || '9:16',
          facecam_x: s.facecam_x,
          facecam_y: s.facecam_y,
          facecam_w: s.facecam_w,
          facecam_h: s.facecam_h,
          gameplay_pan_x: s.gameplay_pan_x,
          zoom_factor: s.zoom_factor,
          sections: s.sections || cand.edit_suggestions || [],
          enable_subtitles: s.enable_subtitles,
          subtitle_style: s.subtitle_style,
          segments: s.segments || []
        });

        this.setEditorAspect(s.aspect_ratio || '9:16', false);
        document.getElementById('editorTranscriptText').value = s.full_text || '';
        if (s.start_s) document.getElementById('trimStartInput').value = s.start_s;
        if (s.end_s) document.getElementById('trimEndInput').value = s.end_s;
      }
    } catch (e) {
      console.warn('Clip settings error:', e);
    }

    this.switchView('editorView');
    this.updateScrubberHighlight();
    this.renderTimelineRuler();
    this.renderTimelineSections();
    this.syncPropertiesPanel();
  }

  setEditorAspect(aspect, redraw = true) {
    document.getElementById('btnAspect916').classList.toggle('active', aspect === '9:16');
    document.getElementById('btnAspect169').classList.toggle('active', aspect === '16:9');
    document.getElementById('canvasTitleText').textContent = `CANVAS PREVIEW (${aspect})`;

    const wrapper = document.getElementById('canvasWrapper');
    if (aspect === '16:9') {
      wrapper.style.width = '640px';
      wrapper.style.height = '360px';
    } else {
      wrapper.style.width = '360px';
      wrapper.style.height = '640px';
    }

    if (this.editor && redraw) {
      this.editor.setAspectRatio(aspect);
    }
  }

  renderTimelineRuler() {
    const ruler = document.getElementById('timelineRuler');
    ruler.innerHTML = '';
    const dur = Math.max(5.0, (this.editor ? this.editor.clipEnd - this.editor.clipStart : 30.0));

    const step = dur > 40 ? 10 : 5;
    for (let t = 0; t <= dur; t += step) {
      const pct = (t / dur) * 100;
      const tick = document.createElement('div');
      tick.className = 'ruler-tick';
      tick.style.left = `${pct}%`;
      tick.innerHTML = `<span>${t}s</span><div class="ruler-tick-mark"></div>`;
      ruler.appendChild(tick);
    }
  }

  renderTimelineSections() {
    const track = document.getElementById('timelineSectionsTrack');
    if (!track || !this.editor || !this.editor.sections) return;

    track.innerHTML = '';
    const dur = Math.max(1.0, this.editor.clipEnd - this.editor.clipStart);

    this.editor.sections.forEach((sec, idx) => {
      const block = document.createElement('div');
      block.className = `timeline-section-block ${idx === this.editor.activeSectionIndex ? 'active' : ''}`;

      const secDur = Math.max(0.5, sec.end - sec.start);
      const widthPct = (secDur / dur) * 100;
      block.style.flex = `${widthPct}`;

      block.innerHTML = `
        <div class="sec-badge-row">
          <span style="font-weight: 700; font-size: 11px;">#${idx + 1}</span>
          <span class="sec-layout-tag">${(sec.layout || 'split').toUpperCase()}</span>
        </div>
        <div class="sec-time-label">${sec.start.toFixed(1)}s - ${sec.end.toFixed(1)}s</div>
      `;

      block.addEventListener('click', () => {
        this.editor.activeSectionIndex = idx;
        const video = document.getElementById('sourceVideo');
        video.currentTime = this.editor.clipStart + sec.start;
        this.renderTimelineSections();
        this.syncPropertiesPanel();
      });

      track.appendChild(block);
    });

    const activeSec = this.editor.getActiveSection();
    if (activeSec) {
      document.getElementById('secStartInput').value = activeSec.start.toFixed(1);
      document.getElementById('secEndInput').value = activeSec.end.toFixed(1);
    }
  }

  switchPropTab(tabId) {
    document.querySelectorAll('.prop-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.prop-content').forEach(c => c.style.display = 'none');

    if (tabId === 'gameplay') {
      document.getElementById('tabPropGameplay').classList.add('active');
      document.getElementById('contentPropGameplay').style.display = 'block';
      if (this.editor) this.editor.selectedElement = 'gameplay';
    } else if (tabId === 'streamer') {
      document.getElementById('tabPropStreamer').classList.add('active');
      document.getElementById('contentPropStreamer').style.display = 'block';
      if (this.editor) this.editor.selectedElement = 'streamer';
    } else {
      document.getElementById('tabPropLayout').classList.add('active');
      document.getElementById('contentPropLayout').style.display = 'block';
    }
    if (this.editor) this.editor.updateOverlayBoxPosition();
  }

  syncPropertiesPanel() {
    if (!this.editor) return;
    const sec = this.editor.getActiveSection();
    if (!sec) return;

    // Gameplay
    document.getElementById('gameplayZoomInput').value = sec.gameplay.zoom || 1.0;
    document.getElementById('txtGameplayZoom').textContent = `${(sec.gameplay.zoom || 1.0).toFixed(2)}x`;
    document.getElementById('gameplayPanXInput').value = sec.gameplay.pan_x !== undefined ? sec.gameplay.pan_x : 0.5;
    document.getElementById('gameplayPosYInput').value = sec.gameplay.y !== undefined ? sec.gameplay.y : 0.4;

    // Streamer
    document.getElementById('chkStreamerEnabled').checked = sec.streamer.enabled !== false;
    document.getElementById('streamerZoomInput').value = sec.streamer.zoom || 1.0;
    document.getElementById('txtStreamerZoom').textContent = `${(sec.streamer.zoom || 1.0).toFixed(2)}x`;
    document.getElementById('streamerBorderInput').value = sec.streamer.border_w !== undefined ? sec.streamer.border_w : 2;
    document.getElementById('txtStreamerBorder').textContent = `${sec.streamer.border_w || 2}px`;
    document.getElementById('streamerRadiusInput').value = sec.streamer.corner_radius || 0;
    document.getElementById('txtStreamerRadius').textContent = `${sec.streamer.corner_radius || 0}px`;

    // Layout
    document.querySelectorAll('.layout-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.layout === sec.layout);
    });
    document.getElementById('selBackgroundStyle').value = sec.background.type === 'blur' ? 'blur' : 'black';
  }

  async generateAiSuggestionsForClip() {
    if (!this.activeClip) return;
    try {
      const res = await fetch(`/api/projects/${this.currentProjectId}/clips/${this.activeClip.id}/ai-edit-suggestions`, {
        method: 'POST'
      });
      const data = await res.json();
      if (data.sections && data.sections.length > 0) {
        this.editor.applyAiEditSuggestions(data.sections);
        this.renderTimelineSections();
        this.syncPropertiesPanel();
        alert(`AI Edit Suggestions applied! Generated ${data.sections.length} layout transitions across timeline.`);
      }
    } catch (e) {
      alert(`AI Suggestions error: ${e.message}`);
    }
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
        this.editor.config.segments = data.segments || [];
      }
      alert('Transcription complete! Captions are now active on your canvas preview.');
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
      aspect_ratio: this.editor.aspectRatio,
      facecam_x: this.editor.config.facecam_x,
      facecam_y: this.editor.config.facecam_y,
      facecam_w: this.editor.config.facecam_w,
      facecam_h: this.editor.config.facecam_h,
      gameplay_pan_x: this.editor.config.gameplay_pan_x,
      zoom_factor: this.editor.config.zoom_factor,
      sections: this.editor.sections,
      start_s: parseFloat(document.getElementById('trimStartInput').value),
      end_s: parseFloat(document.getElementById('trimEndInput').value),
      enable_subtitles: document.getElementById('chkEnableCaptions').checked,
      subtitle_style: document.getElementById('selCaptionStyle').value,
      clip_title: document.getElementById('editorClipTitleInput').value.trim() || this.activeClip.suggested_title
    };

    try {
      await fetch(`/api/projects/${this.currentProjectId}/clips/${this.activeClip.id}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      });
      alert('Clip progress saved successfully!');
    } catch (e) {
      alert(`Save error: ${e.message}`);
    }
  }

  // =========================================================================
  // Export Video Modal & Destination Selection
  // =========================================================================

  openExportModal() {
    const modal = document.getElementById('exportModal');
    modal.classList.add('active');
    const title = (document.getElementById('editorClipTitleInput').value || 'clip').replace(/[^a-zA-Z0-9_-]/g, '_');
    document.getElementById('exportDestPathInput').placeholder = `Default: exports/${this.currentProjectId}/${this.activeClip.id}_${title}.mp4`;
  }

  async browseExportDestination() {
    const title = (document.getElementById('editorClipTitleInput').value || 'clip').replace(/[^a-zA-Z0-9_-]/g, '_');
    const defaultName = `${title}_${this.activeClip.id}.mp4`;

    try {
      const res = await fetch(`/api/system/browse-save-path?default_filename=${encodeURIComponent(defaultName)}`, {
        method: 'POST'
      });
      const data = await res.json();
      if (!data.cancelled && data.path) {
        document.getElementById('exportDestPathInput').value = data.path;
      }
    } catch (e) {
      alert(`Browse dialog error: ${e.message}`);
    }
  }

  async startRenderExport() {
    if (!this.activeClip || !this.editor) return;
    await this.saveClipSettings();

    const destPath = document.getElementById('exportDestPathInput').value.trim();
    const progressEl = document.getElementById('exportRenderProgress');
    progressEl.style.display = 'block';

    const btn = document.getElementById('btnStartRenderExport');
    btn.disabled = true;

    try {
      const res = await fetch(`/api/projects/${this.currentProjectId}/clips/${this.activeClip.id}/render`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          destination_path: destPath || null,
        })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Rendering failed');
      }
      const data = await res.json();
      this.lastRenderedPath = data.output_path;
      this.lastRenderedFilename = data.filename;

      document.getElementById('exportModal').classList.remove('active');
      progressEl.style.display = 'none';

      // Show Export Success Bar
      const bar = document.getElementById('exportSuccessBar');
      document.getElementById('exportedFilename').textContent = data.filename;
      document.getElementById('exportedSize').textContent = `${data.size_mb} MB`;
      document.getElementById('exportSavedPathText').textContent = `Saved at: ${data.output_path}`;

      const dlBtn = document.getElementById('btnDownloadExport');
      dlBtn.href = `/api/exports/${this.currentProjectId}/${data.filename}?download=true`;

      bar.style.display = 'flex';
      alert(`Export Complete!\nVideo saved to: ${data.output_path}`);
    } catch (e) {
      alert(`Render error: ${e.message}`);
    } finally {
      btn.disabled = false;
      progressEl.style.display = 'none';
    }
  }

  async openExportFolder() {
    if (!this.lastRenderedPath) return;
    try {
      const res = await fetch('/api/system/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: this.lastRenderedPath })
      });
      if (!res.ok) {
        const err = await res.json();
        alert(`Could not open folder: ${err.detail}`);
      }
    } catch (e) {
      alert(`Open folder error: ${e.message}`);
    }
  }

  async saveAsNativeDialog() {
    if (!this.activeClip) return;
    try {
      const res = await fetch(`/api/exports/${this.currentProjectId}/${this.activeClip.id}/save-dialog`, {
        method: 'POST'
      });
      const data = await res.json();
      if (data.status === 'saved') {
        this.lastRenderedPath = data.path;
        document.getElementById('exportSavedPathText').textContent = `Saved to: ${data.path}`;
        alert(`Saved successfully to:\n${data.path}`);
      }
    } catch (e) {
      alert(`Save As error: ${e.message}`);
    }
  }

  // =========================================================================
  // AI Settings Modal (Header)
  // =========================================================================

  openAiModal() {
    const modal = document.getElementById('aiSettingsModal');
    modal.classList.add('active');
    this.refreshOllamaModels();
  }

  switchAiTab(tab) {
    const btnLocal = document.getElementById('tabBtnLocalAi');
    const btnApi = document.getElementById('tabBtnApiAi');
    const contentLocal = document.getElementById('tabContentLocalAi');
    const contentApi = document.getElementById('tabContentApiAi');

    if (tab === 'local') {
      btnLocal.classList.add('active');
      btnApi.classList.remove('active');
      contentLocal.style.display = 'block';
      contentApi.style.display = 'none';
    } else {
      btnApi.classList.add('active');
      btnLocal.classList.remove('active');
      contentApi.style.display = 'block';
      contentLocal.style.display = 'none';
    }
  }

  handleApiProviderChange() {
    const prov = document.getElementById('selApiProvider').value;
    const urlInput = document.getElementById('aiApiUrlInput');
    const modelInput = document.getElementById('aiApiModelInput');
    const hint = document.getElementById('apiModelHint');

    if (prov === 'deepseek') {
      urlInput.value = 'https://api.deepseek.com/v1';
      modelInput.value = 'deepseek-chat';
      hint.innerHTML = 'Default: <code>deepseek-chat</code>';
    } else {
      urlInput.value = 'https://openrouter.ai/api/v1';
      modelInput.value = 'deepseek/deepseek-chat';
      hint.innerHTML = 'Default: <code>deepseek/deepseek-chat</code>';
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

        if (data.model_details && data.model_details.length > 0) {
          sel.innerHTML = data.model_details.map(m => `<option value="${m.name}">${m.name} — ${m.size} (${m.ram}) ${m.recommended ? '★ RECOMMENDED' : ''}</option>`).join('');
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
      provider: prov,
      configured: true
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
  // Storage & Projects Modal
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
