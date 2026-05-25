/**
 * ============================================================================
 * ComfyUI-Feixue-UniversalMonitor - Main Application
 * ============================================================================
 * 
 * 主应用程序文件 - 整合所有组件和逻辑
 * 
 * 功能:
 * 1. 初始化和管理监控器 UI
 * 2. 数据获取和更新
 * 3. 组件状态管理
 * 4. 用户交互处理 (拖拽、折叠、关闭等)
 * 5. 响应式布局适配
 * 
 * @author Feixue
 * @version 1.0.0
 * @license MIT
 * ============================================================================
 */

'use strict';

// ============================================================================
// UNIVERSAL MONITOR CLASS (通用监控器类)
// ============================================================================

class UniversalMonitorUI {
  constructor(options = {}) {
    // Configuration
    this.config = {
      container: options.container || document.body,
      theme: options.theme || 'cyberpunk-blue',
      position: options.position || 'top-right',
      updateInterval: options.updateInterval || 1000,  // 1 second
      showOnStart: options.showOnStart !== false,
      draggable: options.draggable !== false,
      collapsible: options.collapsible !== false,
      
      // API endpoints
      apiBase: options.apiBase || '/universal_monitor',
      ...options
    };
    
    // State
    this.state = {
      isInitialized: false,
      isVisible: false,
      isCollapsed: false,
      isDragging: false,
      isLoading: true,
      hasError: false,
      currentData: null,
      historyData: {
        cpu: [],
        gpu: [],
        memory: [],
        power: [],
        temperature: []
      },
      maxHistoryPoints: 60  // Keep last 60 data points (60 seconds at 1s interval)
    };
    
    // DOM References
    this.elements = {};
    
    // Animation controllers
    this.animators = {};
    
    // Timers
    this.updateTimer = null;
    
    // Bind methods
    this.init = this.init.bind(this);
    this.destroy = this.destroy.bind(this);
    this.update = this.update.bind(this);
    this.show = this.show.bind(this);
    this.hide = this.hide.bind(this);
    this.toggle = this.toggle.bind(this);
    this.collapse = this.collapse.bind(this);
    this.expand = this.expand.bind(this);
  }
  
  // ==========================================================================
  // INITIALIZATION (初始化)
  // ==========================================================================
  
  /**
   * Initialize the monitor UI
   */
  async init() {
    if (this.state.isInitialized) return this;
    
    try {
      // Create DOM structure
      this.createDOM();
      
      // Apply initial state
      this.applyTheme(this.config.theme);
      this.applyPosition(this.config.position);
      
      // Setup event listeners
      this.setupEventListeners();
      
      // Initialize animations
      this.initAnimations();
      
      // Show if configured
      if (this.config.showOnStart) {
        await this.show();
      }
      
      // Start data updates
      this.startUpdates();
      
      this.state.isInitialized = true;
      console.log('[UniversalMonitor] Initialized successfully');
      
      return this;
      
    } catch (error) {
      console.error('[UniversalMonitor] Initialization failed:', error);
      this.showError(error.message);
      return this;
    }
  }
  
  /**
   * Create the complete DOM structure
   */
  createDOM() {
    const container = typeof this.config.container === 'string' 
      ? document.querySelector(this.config.container)
      : this.config.container;
    
    if (!container) {
      throw new Error('Container element not found');
    }
    
    // Root element
    this.elements.root = document.createElement('div');
    this.elements.root.className = 'um-root';
    this.elements.root.setAttribute('data-theme', this.config.theme);
    this.elements.root.innerHTML = `
      <!-- Screen reader announcer -->
      <div class="um-sr-announcer" role="status" aria-live="polite" aria-atomic="true"></div>
      
      <!-- Top Menu Bar with Capsules -->
      <nav class="top-menu-bar" role="toolbar" aria-label="Hardware Monitor Quick Stats">
        <div class="capsule capsule--pred" data-metric="pred" tabindex="0" role="button" aria-label="Prediction Success Rate">
          <span class="capsule__indicator capsule__indicator--normal"></span>
          <div class="capsule__pred-ring">
            <svg viewBox="0 0 18 18">
              <defs>
                <linearGradient id="pred-ring-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" style="stop-color:#00ff88"/>
                  <stop offset="100%" style="stop-color:#00d4ff"/>
                </linearGradient>
              </defs>
              <circle class="capsule__pred-ring-bg" cx="9" cy="9" r="7"/>
              <circle class="capsule__pred-ring-progress" cx="9" cy="9" r="7"
                stroke-dasharray="43.98" stroke-dashoffset="43.98"/>
            </svg>
          </div>
          <div class="capsule__content">
            <span class="capsule__value">--</span>
            <span class="capsule__unit">PRED</span>
          </div>
          <div class="capsule__sparkline">
            <canvas class="capsule__sparkline-canvas"></canvas>
          </div>
        </div>
        
        <div class="capsule capsule--normal" data-metric="cpu" tabindex="0" role="button" aria-label="CPU Usage">
          <span class="capsule__indicator capsule__indicator--normal"></span>
          <div class="capsule__icon">
            <svg viewBox="0 0 14 14"><path d="M3 2h8v10H3z M5 4v6M7 4v6M9 4v6"/></svg>
          </div>
          <div class="capsule__content">
            <span class="capsule__value">--</span>
            <span class="capsule__unit">%</span>
          </div>
          <div class="capsule__sparkline">
            <canvas class="capsule__sparkline-canvas"></canvas>
          </div>
        </div>
        
        <div class="capsule capsule--normal" data-metric="ram" tabindex="0" role="button" aria-label="RAM Usage">
          <span class="capsule__indicator capsule__indicator--normal"></span>
          <div class="capsule__icon">
            <svg viewBox="0 0 14 14"><path d="M2 4h10v8H2zM4 2v2M6 2v2M8 2v2M10 2v2"/></svg>
          </div>
          <div class="capsule__content">
            <span class="capsule__value">--</span>
            <span class="capsule__unit">GB</span>
          </div>
          <div class="capsule__sparkline">
            <canvas class="capsule__sparkline-canvas"></canvas>
          </div>
        </div>
        
        <div class="capsule capsule--normal" data-metric="gpu" tabindex="0" role="button" aria-label="GPU Usage">
          <span class="capsule__indicator capsule__indicator--normal"></span>
          <div class="capsule__icon">
            <svg viewBox="0 0 14 14"><path d="M12 8H8l-2 4H2l2-6L2 2h8l2 6z"/></svg>
          </div>
          <div class="capsule__content">
            <span class="capsule__value">--</span>
            <span class="capsule__unit">%</span>
          </div>
          <div class="capsule__sparkline">
            <canvas class="capsule__sparkline-canvas"></canvas>
          </div>
        </div>
        
        <div class="capsule capsule--normal" data-metric="vram" tabindex="0" role="button" aria-label="VRAM Usage">
          <span class="capsule__indicator capsule__indicator--normal"></span>
          <div class="capsule__icon">
            <svg viewBox="0 0 14 14"><path d="M3 2h8v10H3z M5 5h4M5 7h4M5 9h2"/></svg>
          </div>
          <div class="capsule__content">
            <span class="capsule__value">--</span>
            <span class="capsule__unit">G</span>
          </div>
          <div class="capsule__sparkline">
            <canvas class="capsule__sparkline-canvas"></canvas>
          </div>
        </div>
        
        <div class="capsule capsule--normal" data-metric="reserved" tabindex="0" role="button" aria-label="Reserved VRAM">
          <span class="capsule__indicator capsule__indicator--inactive"></span>
          <div class="capsule__icon">
            <svg viewBox="0 0 14 14"><path d="M7 1l1.5 4.5H13L9.5 8l1.5 4.5L7 10l-4 2.5L4.5 8 1 5.5h4.5z"/></svg>
          </div>
          <div class="capsule__content">
            <span class="capsule__value">--</span>
            <span class="capsule__unit">RSV</span>
          </div>
        </div>
        
        <div class="capsule capsule--normal" data-metric="power" tabindex="0" role="button" aria-label="Power Draw">
          <span class="capsule__indicator capsule__indicator--normal"></span>
          <div class="capsule__icon">
            <svg viewBox="0 0 14 14"><path d="M8 1v4l4 4v4H2v-4l4-4V1h2z"/></svg>
          </div>
          <div class="capsule__content">
            <span class="capsule__value">--</span>
            <span class="capsule__unit">W</span>
          </div>
          <div class="capsule__waveform">
            <svg width="40" height="3" viewBox="0 0 40 3">
              <path class="capsule__waveform-path" d="M0,1.5 Q10,0 20,1.5 T40,1.5"/>
            </svg>
          </div>
        </div>
      </nav>
      
      <!-- Hover Panel -->
      <aside class="hover-panel" role="widget" aria-label="Hardware Monitor Details" aria-expanded="true">
        <!-- Header -->
        <header class="panel-header">
          <div class="panel-header__drag-handle"></div>
          
          <div class="panel-header__left">
            <div class="panel-header__logo">
              <svg viewBox="0 0 20 20">
                <path d="M13 2L3 14h9l-1 6 10-12h-9l1-6z"/>
              </svg>
            </div>
            <h1 class="panel-header__title">Universal Monitor</h1>
          </div>
          
          <div class="panel-header__controls">
            ${this.config.collapsible ? `
            <button class="panel-header__btn panel-header__btn--collapse" 
                    aria-label="Collapse panel" 
                    title="Collapse">
              <svg viewBox="0 0 14 14"><path d="M4 6l3 3 3-3"/></svg>
            </button>
            ` : ''}
            <button class="panel-header__btn panel-header__btn--close" 
                    aria-label="Close monitor" 
                    title="Close">
              <svg viewBox="0 0 14 14"><path d="M3 3l8 8M11 3l-8 8"/></svg>
            </button>
          </div>
        </header>
        
        <!-- Body -->
        <div class="panel-body">
          <!-- Metrics Grid -->
          <div class="metrics-grid">
            <!-- CPU Card -->
            <article class="metric-card metric-card--normal" data-metric="cpu" aria-label="CPU Usage">
              <div class="metric-card__header">
                <div class="metric-card__label-group">
                  <div class="metric-card__icon">
                    <svg viewBox="0 0 16 16"><path d="M4 2h8v11H4z M6 4v7M8 4v7M10 4v7"/></svg>
                  </div>
                  <span class="metric-card__label">CPU</span>
                </div>
              </div>
              <div class="metric-card__body">
                <span class="metric-card__value mono-text">--</span>
                <span class="metric-card__unit">%</span>
              </div>
              <div class="metric-card__progress">
                <div class="metric-card__progress-bar" style="width: 0%"></div>
              </div>
            </article>
            
            <!-- RAM Card -->
            <article class="metric-card metric-card--normal" data-metric="ram" aria-label="Memory Usage">
              <div class="metric-card__header">
                <div class="metric-card__label-group">
                  <div class="metric-card__icon">
                    <svg viewBox="0 0 16 16"><path d="M2 5h12v9H2zM4 3v2M7 3v2M10 3v2M13 3v2"/></svg>
                  </div>
                  <span class="metric-card__label">RAM</span>
                </div>
              </div>
              <div class="metric-card__body">
                <span class="metric-card__value mono-text">--</span>
                <span class="metric-card__unit">GB</span>
              </div>
              <div class="metric-card__secondary mono-text">-- / -- GB</div>
              <div class="metric-card__progress">
                <div class="metric-card__progress-bar" style="width: 0%"></div>
              </div>
            </article>
            
            <!-- GPU Card -->
            <article class="metric-card metric-card--normal metric-card--gpu-ring" data-metric="gpu" aria-label="GPU Usage">
              <div class="metric-card__ring-container">
                <svg viewBox="0 0 100 100">
                  <defs>
                    <linearGradient id="ring-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" style="stop-color:#00d4ff"/>
                      <stop offset="50%" style="stop-color:#a855f7"/>
                      <stop offset="100%" style="stop-color:#ff3366"/>
                    </linearGradient>
                  </defs>
                  <circle class="ring-progress__track" cx="50" cy="50" r="44"/>
                  <circle class="ring-progress__fill ring-progress__fill--normal" cx="50" cy="50" r="44"
                    stroke-dasharray="276.46" stroke-dashoffset="276.46"/>
                </svg>
                <div class="ring-progress__content">
                  <span class="ring-progress__value mono-text">--</span>
                  <span class="ring-progress__label">GPU</span>
                </div>
              </div>
            </article>
            
            <!-- VRAM Card -->
            <article class="metric-card metric-card--normal" data-metric="vram" aria-label="Video Memory Usage">
              <div class="metric-card__header">
                <div class="metric-card__label-group">
                  <div class="metric-card__icon">
                    <svg viewBox="0 0 16 16"><path d="M3 2h10v11H3z M5 5h6M5 7h6M5 9h4"/></svg>
                  </div>
                  <span class="metric-card__label">VRAM</span>
                </div>
              </div>
              <div class="metric-card__body">
                <div class="metric-card__vram-values">
                  <span class="metric-card__vram-main mono-text">--</span>
                  <span class="metric-card__vram-sub mono-text">/ -- G</span>
                </div>
              </div>
              <div class="metric-card__progress">
                <div class="metric-card__progress-bar" style="width: 0%"></div>
              </div>
            </article>
            
            <!-- Prediction Card -->
            <article class="metric-card metric-card--prediction metric-card--normal" data-metric="prediction" aria-label="VRAM Prediction">
              <div class="metric-card__prediction-header">
                <div class="metric-card__label-group">
                  <div class="metric-card__icon">
                    <svg viewBox="0 0 16 16"><path d="M8 1l2 5h5l-4 3 1.5 5L8 11l-4.5 3L5 9 1 6h5z"/></svg>
                  </div>
                  <span class="metric-card__label">PRED Prediction</span>
                </div>
                <span class="metric-card__risk-indicator metric-card__risk-indicator--low">
                  <span>Low Risk</span>
                </span>
              </div>
              
              <div class="metric-card__body">
                <span class="metric-card__value mono-text">--</span>
                <span class="metric-card__unit">% success rate</span>
              </div>
              
              <div class="metric-card__progress">
                <div class="metric-card__progress-bar" style="width: 0%"></div>
              </div>
              
              <div class="metric-card__recommendations">
                <div class="metric-card__recommendation-item">
                  <svg class="metric-card__recommendation-icon" viewBox="0 0 12 12">
                    <path d="M6 1l1.5 4h4l-3 2.5 1 4L6 9.5 2.5 11l1-4-3-2.5h4z" fill="currentColor"/>
                  </svg>
                  <span>Awaiting prediction data...</span>
                </div>
              </div>
            </article>
          </div>
          
          <!-- Detail Section -->
          <div class="detail-section">
            <!-- Thermometer -->
            <div class="thermometer thermometer--normal" data-metric="temperature">
              <svg width="24" height="120" viewBox="0 0 24 120">
                <defs>
                  <linearGradient id="thermo-glass-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" style="stop-color:rgba(255,255,255,0.15)"/>
                    <stop offset="50%" style="stop-color:rgba(255,255,255,0.05)"/>
                    <stop offset="100%" style="stop-color:rgba(255,255,255,0.15)"/>
                  </linearGradient>
                </defs>
                
                <!-- Tube outline -->
                <rect class="thermometer__tube" x="6" y="4" width="12" height="90" rx="6"/>
                
                <!-- Liquid fill (positioned from bottom) -->
                <rect class="thermometer__liquid thermometer__liquid--cool" x="8" y="80" width="8" height="14" rx="4"/>
                
                <!-- Bulb at bottom -->
                <circle class="thermometer__bulb" cx="12" cy="108" r="10"/>
                
                <!-- Scale markings -->
                <g class="thermometer__scale">
                  <line x1="19" y1="10" x2="23" y2="10"/>
                  <text x="22" y="13" class="thermometer__scale-text">90°</text>
                  
                  <line x1="19" y1="32" x2="21" y2="32"/>
                  <text x="22" y="35" class="thermometer__scale-text">60°</text>
                  
                  <line x1="19" y1="55" x2="23" y2="55"/>
                  <text x="22" y="58" class="thermometer__scale-text">30°</text>
                  
                  <line x1="19" y1="85" x2="21" y2="85"/>
                  <text x="22" y="88" class="thermometer__scale-text">0°</text>
                </g>
              </svg>
              
              <span class="thermometer__temp-label mono-text">--°C</span>
              
              <!-- Fire particles (hidden by default) -->
              <div class="thermometer__fire-particles">
                <span class="thermometer__particle"></span>
                <span class="thermometer__particle"></span>
                <span class="thermometer__particle"></span>
                <span class="thermometer__particle"></span>
                <span class="thermometer__particle"></span>
              </div>
            </div>
            
            <!-- Power Chart -->
            <div class="chart-container">
              <div class="line-chart" data-chart="power">
                <canvas></canvas>
                <div class="line-chart__tooltip"></div>
                <div class="line-chart__crosshair"></div>
              </div>
              <div class="line-chart__legend">
                <div class="line-chart__legend-item">
                  <span class="line-chart__legend-color" style="background: #00d4ff;"></span>
                  <span>Power (W)</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <!-- Footer -->
        <footer class="panel-footer">
          <div class="panel-footer__info">
            <span class="panel-footer__source">
              <span class="panel-footer__source-dot"></span>
              <span class="panel-footer__source-name">Detecting...</span>
            </span>
            <span class="panel-footer__version">v1.0.0</span>
          </div>
          
          <div class="panel-footer__status">
            <span class="panel-footer__live-indicator">
              <span class="panel-footer__live-dot"></span>
              <span>LIVE</span>
            </span>
          </div>
        </footer>
      </aside>
    `;
    
    container.appendChild(this.elements.root);
    
    // Cache DOM references
    this.cacheElementReferences();
  }
  
  /**
   * Cache frequently used DOM elements
   */
  cacheElementReferences() {
    const root = this.elements.root;
    
    // Panel elements
    this.elements.panel = root.querySelector('.hover-panel');
    this.elements.panelHeader = root.querySelector('.panel-header');
    this.elements.panelBody = root.querySelector('.panel-body');
    this.elements.panelFooter = root.querySelector('.panel-footer');
    
    // Control buttons
    this.elements.closeBtn = root.querySelector('.panel-header__btn--close');
    this.elements.collapseBtn = root.querySelector('.panel-header__btn--collapse');
    this.elements.dragHandle = root.querySelector('.panel-header__drag-handle');
    
    // Capsules
    this.elements.capsules = root.querySelectorAll('.capsule');
    
    // Metric cards
    this.elements.cards = root.querySelectorAll('.metric-card');
    
    // Charts
    this.elements.charts = root.querySelectorAll('.line-chart canvas');
    
    // Announcer for screen readers
    this.elements.announcer = root.querySelector('.um-sr-announcer');
  }
  
  // ==========================================================================
  // EVENT LISTENERS (事件监听器)
  // ==========================================================================
  
  setupEventListeners() {
    // Close button
    if (this.elements.closeBtn) {
      this.elements.closeBtn.addEventListener('click', () => this.hide());
    }
    
    // Collapse button
    if (this.elements.collapseBtn) {
      this.elements.collapseBtn.addEventListener('click', () => this.toggleCollapse());
    }
    
    // Drag functionality
    if (this.config.draggable && this.elements.dragHandle) {
      this.setupDragFunctionality();
    }
    
    // Keyboard navigation
    this.elements.root.addEventListener('keydown', (e) => this.handleKeyboard(e));
    
    // Window events
    window.addEventListener('resize', debounce(() => this.handleResize(), 150));
    
    // Visibility change (pause updates when tab hidden)
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        this.pauseUpdates();
      } else {
        this.resumeUpdates();
      }
    });
    
    // Theme change listener
    if (window.matchMedia) {
      window.matchMedia('(prefers-reduced-motion: reduce)')
        .addEventListener('change', () => this.handleReducedMotionChange());
    }
  }
  
  /**
   * Setup drag and drop functionality for the panel
   */
  setupDragFunctionality() {
    let isDragging = false;
    let startX, startY, startLeft, startTop;
    
    const onDragStart = (e) => {
      // Only left click or touch
      if (e.type === 'mousedown' && e.button !== 0) return;
      
      e.preventDefault();
      isDragging = true;
      
      const rect = this.elements.panel.getBoundingClientRect();
      
      startX = e.type === 'mousedown' ? e.clientX : e.touches[0].clientX;
      startY = e.type === 'mousedown' ? e.clientY : e.touches[0].clientY;
      startLeft = rect.left;
      startTop = rect.top;
      
      this.elements.panel.classList.add('hover-panel--dragging');
      this.state.isDragging = true;
      
      document.body.style.userSelect = 'none';
    };
    
    const onDragMove = (e) => {
      if (!isDragging) return;
      
      const clientX = e.type === 'mousemove' ? e.clientX : e.touches[0].clientX;
      const clientY = e.type === 'mousemove' ? e.clientY : e.touches[0].clientY;
      
      const deltaX = clientX - startX;
      const deltaY = clientY - startY;
      
      let newLeft = startLeft + deltaX;
      let newTop = startTop + deltaY;
      
      // Constrain to viewport
      const rect = this.elements.panel.getBoundingClientRect();
      const maxLeft = window.innerWidth - rect.width;
      const maxTop = window.innerHeight - rect.height;
      
      newLeft = Math.max(0, Math.min(newLeft, maxLeft));
      newTop = Math.max(0, Math.min(newTop, maxTop));
      
      // Optional snap to grid (10px)
      newLeft = Math.round(newLeft / 10) * 10;
      newTop = Math.round(newTop / 10) * 10;
      
      this.elements.panel.style.left = `${newLeft}px`;
      this.elements.panel.style.top = `${newTop}px`;
      this.elements.panel.style.right = 'auto';
    };
    
    const onDragEnd = () => {
      if (!isDragging) return;
      
      isDragging = false;
      this.state.isDragging = false;
      
      this.elements.panel.classList.remove('hover-panel--dragging');
      document.body.style.userSelect = '';
      
      // Save position to localStorage
      const rect = this.elements.panel.getBoundingClientRect();
      localStorage.setItem('um-panel-position', JSON.stringify({
        left: rect.left,
        top: rect.top
      }));
    };
    
    // Mouse events (desktop-only: removed touch events for performance optimization)
    this.elements.dragHandle.addEventListener('mousedown', onDragStart);
    document.addEventListener('mousemove', onDragMove);
    document.addEventListener('mouseup', onDragEnd);
  }
  
  /**
   * Handle keyboard navigation
   */
  handleKeyboard(e) {
    switch (e.key) {
      case 'Escape':
        if (this.state.isVisible) {
          this.hide();
        }
        break;
        
      case 'Enter':
      case ' ':
        if (e.target.closest('.capsule')) {
          e.preventDefault();
          // Could expand/capsule or focus panel
          this.show();
        }
        break;
        
      case 'Tab':
        // Ensure focus trap when panel is modal
        break;
    }
  }
  
  // ==========================================================================
  // DATA MANAGEMENT (数据管理)
  // ==========================================================================
  
  /**
   * Start periodic data updates
   */
  startUpdates() {
    if (this.updateTimer) return;
    
    // Initial fetch
    this.fetchData();
    
    // Set up interval
    this.updateTimer = setInterval(() => {
      this.fetchData();
    }, this.config.updateInterval);
  }
  
  /**
   * Pause updates (when tab is hidden)
   */
  pauseUpdates() {
    if (this.updateTimer) {
      clearInterval(this.updateTimer);
      this.updateTimer = null;
    }
  }
  
  /**
   * Resume updates (when tab becomes visible)
   */
  resumeUpdates() {
    if (!this.updateTimer) {
      this.startUpdates();
    }
  }
  
  /**
   * Fetch data from backend API
   */
  async fetchData() {
    try {
      // Try to get data from ComfyUI extension API
      let data = null;
      
      if (window.api?.get_snapshot) {
        data = await window.api.get_snapshot();
      } else {
        // Fallback: fetch from endpoint
        const response = await fetch(`${this.config.apiBase}/snapshot`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        data = await response.json();
      }
      
      if (data.error) {
        throw new Error(data.error);
      }
      
      this.state.currentData = data;
      this.state.hasError = false;
      this.state.isLoading = false;
      
      // Update history for charts
      this.updateHistory(data);
      
      // Update UI
      this.updateUI(data);
      
    } catch (error) {
      console.warn('[UniversalMonitor] Data fetch error:', error);
      this.state.hasError = true;
      
      // Don't show error immediately, might be transient
      // Could implement retry logic here
    }
  }
  
  /**
   * Update history data arrays for charts
   */
  updateHistory(data) {
    const now = Date.now();
    
    // Add current values to history
    if (data.cpu) {
      this.state.historyData.cpu.push({ time: now, value: data.cpu.usage_percent });
    }
    if (data.gpus && data.gpus[0]) {
      const gpu = data.gpus[0];
      this.state.historyData.gpu.push({ time: now, value: gpu.gpu_utilization });
      this.state.historyData.power.push({ time: now, value: gpu.power_draw_watts });
      if (gpu.temperature) {
        this.state.historyData.temperature.push({ time: now, value: gpu.temperature });
      }
      this.state.historyData.memory.push({ time: now, value: gpu.vram_used_mb });
    }
    
    // Trim history to max points
    Object.keys(this.state.historyData).forEach(key => {
      if (this.state.historyData[key].length > this.state.maxHistoryPoints) {
        this.state.historyData[key] = this.state.historyData[key].slice(-this.state.maxHistoryPoints);
      }
    });
  }
  
  /**
   * Update all UI components with new data
   */
  updateUI(data) {
    // Update capsules
    this.updateCapsules(data);
    
    // Update metric cards
    this.updateCards(data);
    
    // Update charts
    this.updateCharts(data);
    
    // Update footer info
    this.updateFooter(data);
    
    // Announce critical changes to screen readers
    this.announceCriticalChanges(data);
  }
  
  /**
   * Update top menu bar capsules
   */
  updateCapsules(data) {
    // PRED capsule
    if (data.prediction) {
      const predCapsule = this.elements.root.querySelector('[data-metric="pred"]');
      if (predCapsule) {
        const rate = data.prediction.success_rate * 100;
        this.updateCapsuleValue(predCapsule, `${rate.toFixed(0)}`);
        this.updatePredRing(predCapsule, rate);
        this.setCapsuleStatus(predCapsule, this.getStatusFromPercent(rate));
      }
    }
    
    // CPU capsule
    if (data.cpu) {
      const cpuCapsule = this.elements.root.querySelector('[data-metric="cpu"]');
      if (cpuCapsule) {
        this.updateCapsuleValue(cpuCapsule, data.cpu.usage_percent.toFixed(0));
        this.setCapsuleStatus(cpuCapsule, this.getStatusFromPercent(data.cpu.usage_percent));
      }
    }
    
    // RAM capsule
    if (data.ram) {
      const ramCapsule = this.elements.root.querySelector('[data-metric="ram"]');
      if (ramCapsule) {
        this.updateCapsuleValue(ramCapsule, data.ram.used_gb.toFixed(1));
        this.setCapsuleStatus(ramCapsule, this.getStatusFromPercent(data.ram.usage_percent));
      }
    }
    
    // GPU capsule
    if (data.gpus && data.gpus[0]) {
      const gpu = data.gpus[0];
      
      const gpuCapsule = this.elements.root.querySelector('[data-metric="gpu"]');
      if (gpuCapsule) {
        this.updateCapsuleValue(gpuCapsule, gpu.gpu_utilization.toFixed(0));
        this.setCapsuleStatus(gpuCapsule, this.getStatusFromPercent(gpu.gpu_utilization));
      }
      
      const vramCapsule = this.elements.root.querySelector('[data-metric="vram"]');
      if (vramCapsule) {
        const vramGb = (gpu.vram_used_mb / 1024).toFixed(1);
        this.updateCapsuleValue(vramCapsule, vramGb);
        this.setCapsuleStatus(vramCapsule, this.getStatusFromPercent(gpu.memory_utilization));
      }
      
      const powerCapsule = this.elements.root.querySelector('[data-metric="power"]');
      if (powerCapsule) {
        this.updateCapsuleValue(powerCapsule, gpu.power_draw_watts.toFixed(0));
        this.setCapsuleStatus(powerCapsule, this.getStatusFromPower(gpu.power_draw_watts, gpu.power_limit_watts));
      }
    }
  }
  
  /**
   * Update metric cards in the panel
   */
  updateCards(data) {
    // CPU Card
    if (data.cpu) {
      const cpuCard = this.elements.root.querySelector('.metric-card[data-metric="cpu"]');
      if (cpuCard) {
        const valueEl = cpuCard.querySelector('.metric-card__value');
        const progressEl = cpuCard.querySelector('.metric-card__progress-bar');
        
        animatePercentage(valueEl, data.cpu.usage_percent);
        progressEl.style.width = `${data.cpu.usage_percent}%`;
        
        this.setCardStatus(cpuCard, this.getStatusFromPercent(data.cpu.usage_percent));
      }
    }
    
    // RAM Card
    if (data.ram) {
      const ramCard = this.elements.root.querySelector('.metric-card[data-metric="ram"]');
      if (ramCard) {
        const valueEl = ramCard.querySelector('.metric-card__value');
        const secondaryEl = ramCard.querySelector('.metric-card__secondary');
        const progressEl = ramCard.querySelector('.metric-card__progress-bar');
        
        valueEl.textContent = data.ram.used_gb.toFixed(1);
        secondaryEl.textContent = `${data.ram.used_gb.toFixed(1)} / ${data.ram.total_gb.toFixed(1)} GB`;
        progressEl.style.width = `${data.ram.usage_percent}%`;
        
        this.setCardStatus(ramCard, this.getStatusFromPercent(data.ram.usage_percent));
      }
    }
    
    // GPU Card (with ring)
    if (data.gpus && data.gpus[0]) {
      const gpu = data.gpus[0];
      const gpuCard = this.elements.root.querySelector('.metric-card[data-metric="gpu"]');
      if (gpuCard) {
        const ringValueEl = gpuCard.querySelector('.ring-progress__value');
        const ringFillEl = gpuCard.querySelector('.ring-progress__fill');
        
        animatePercentage(ringValueEl, gpu.gpu_utilization);
        this.updateRingProgress(ringFillEl, gpu.gpu_utilization);
        
        this.setCardStatus(gpuCard, this.getStatusFromPercent(gpu.gpu_utilization));
      }
      
      // VRAM Card
      const vramCard = this.elements.root.querySelector('.metric-card[data-metric="vram"]');
      if (vramCard) {
        const mainEl = vramCard.querySelector('.metric-card__vram-main');
        const subEl = vramCard.querySelector('.metric-card__vram-sub');
        const progressEl = vramCard.querySelector('.metric-card__progress-bar');
        
        const usedGb = (gpu.vram_used_mb / 1024).toFixed(1);
        const totalGb = (gpu.vram_total_mb / 1024).toFixed(0);
        
        mainEl.textContent = `${usedGb}`;
        subEl.textContent = `/ ${totalGb} G`;
        progressEl.style.width = `${gpu.memory_utilization}%`;
        
        this.setCardStatus(vramCard, this.getStatusFromPercent(gpu.memory_utilization));
      }
      
      // Prediction Card
      if (data.prediction) {
        const predCard = this.elements.root.querySelector('.metric-card[data-metric="prediction"]');
        if (predCard) {
          const valueEl = predCard.querySelector('.metric-card__value');
          const progressEl = predCard.querySelector('.metric-card__progress-bar');
          const riskIndicator = predCard.querySelector('.metric-card__risk-indicator');
          const recommendations = predCard.querySelector('.metric-card__recommendations');
          
          const rate = data.prediction.success_rate * 100;
          valueEl.textContent = `${rate.toFixed(0)}`;
          progressEl.style.width = `${rate}%`;
          
          // Update risk indicator
          const riskLevel = data.prediction.risk_level;
          riskIndicator.className = `metric-card__risk-indicator metric-card__risk-indicator--${riskLevel}`;
          riskIndicator.innerHTML = `<span>${riskLevel.charAt(0).toUpperCase() + riskLevel.slice(1)} Risk</span>`;
          
          // Update recommendations
          if (data.prediction.recommendations && data.prediction.recommendations.length > 0) {
            recommendations.innerHTML = data.prediction.recommendations.map(rec => `
              <div class="metric-card__recommendation-item">
                <svg class="metric-card__recommendation-icon" viewBox="0 0 12 12">
                  <path d="M6 1l1.5 4h4l-3 2.5 1 4L6 9.5 2.5 11l1-4-3-2.5h4z" fill="currentColor"/>
                </svg>
                <span>${rec}</span>
              </div>
            `).join('');
          }
          
          this.setCardStatus(predCard, this.getStatusFromRisk(riskLevel));
        }
      }
      
      // Temperature
      if (gpu.temperature) {
        const thermo = this.elements.root.querySelector('.thermometer');
        if (thermo) {
          this.updateThermometer(thermo, gpu.temperature);
        }
      }
    }
  }
  
  /**
   * Update chart canvases
   */
  updateCharts(data) {
    // Implementation would use ChartAnimator class
    // This is a placeholder for chart rendering logic
    
    const powerChartCanvas = this.elements.root.querySelector('.line-chart[data-chart="power"] canvas');
    if (powerChartCanvas && this.state.historyData.power.length > 1) {
      this.renderLineChart(
        powerChartCanvas, 
        this.state.historyData.power,
        { color: '#00d4ff', label: 'Power (W)' }
      );
    }
  }
  
  /**
   * Update footer information
   */
  updateFooter(data) {
    const sourceName = this.elements.root.querySelector('.panel-footer__source-name');
    const sourceDot = this.elements.root.querySelector('.panel-footer__source-dot');
    
    if (sourceName && data.provider_name) {
      sourceName.textContent = data.provider_name;
      
      // Set dot status based on provider quality
      if (data.provider_name.includes('amdsmi') || data.provider_name.includes('nvidia')) {
        sourceDot.className = 'panel-footer__source-dot';
      } else if (data.provider_name.includes('generic') || data.provider_name.includes('psutil')) {
        sourceDot.className = 'panel-footer__source-dot panel-footer__source-dot--warning';
      } else {
        sourceDot.className = 'panel-footer__source-dot';
      }
    }
  }
  
  // ==========================================================================
  // HELPER METHODS (辅助方法)
  // ==========================================================================
  
  getStatusFromPercent(percent) {
    if (percent >= 80) return 'danger';
    if (percent >= 60) return 'warning';
    return 'normal';
  }
  
  getStatusFromPower(current, limit) {
    if (!limit) return 'normal';
    const ratio = current / limit;
    if (ratio >= 0.9) return 'danger';
    if (ratio >= 0.7) return 'warning';
    return 'normal';
  }
  
  getStatusFromRisk(riskLevel) {
    switch (riskLevel) {
      case 'critical': return 'danger';
      case 'high': return 'danger';
      case 'medium': return 'warning';
      default: return 'normal';
    }
  }
  
  updateCapsuleValue(capsule, value) {
    const valueEl = capsule.querySelector('.capsule__value');
    if (valueEl) valueEl.textContent = value;
  }
  
  setCapsuleStatus(capsule, status) {
    // Remove old status classes
    capsule.classList.remove('capsule--normal', 'capsule--warning', 'capsule--danger');
    
    // Add new status class
    capsule.classList.add(`capsule--${status}`);
    
    // Update indicator
    const indicator = capsule.querySelector('.capsule__indicator');
    if (indicator) {
      indicator.className = `capsule__indicator capsule__indicator--${status === 'normal' ? 'normal' : status}`;
    }
  }
  
  setCardStatus(card, status) {
    card.classList.remove('metric-card--normal', 'metric-card--warning', 'metric-card--danger');
    card.classList.add(`metric-card--${status}`);
  }
  
  updatePredRing(capsule, percent) {
    const progress = capsule.querySelector('.capsule__pred-ring-progress');
    if (progress) {
      const circumference = 43.98; // 2 * PI * 7
      const offset = circumference - (percent / 100) * circumference;
      progress.style.strokeDashoffset = offset;
    }
  }
  
  updateRingProgress(element, percent) {
    if (!element) return;
    
    const circumference = 276.46; // 2 * PI * 44
    const offset = circumference - (percent / 100) * circumference;
    
    element.style.strokeDashoffset = offset;
    
    // Update color class based on status
    element.classList.remove('ring-progress__fill--normal', 'ring-progress__fill--warning', 'ring-progress__fill--danger');
    
    if (percent >= 80) {
      element.classList.add('ring-progress__fill--danger');
    } else if (percent >= 60) {
      element.classList.add('ring-progress__fill--warning');
    } else {
      element.classList.add('ring-progress__fill--normal');
    }
  }
  
  updateThermometer(thermo, tempC) {
    const liquid = thermo.querySelector('.thermometer__liquid');
    const label = thermo.querySelector('.thermometer__temp-label');
    
    if (liquid && label) {
      label.textContent = `${tempC.toFixed(0)}°C`;
      
      // Calculate liquid height (0-100°C range)
      const maxHeight = 70; // Max height of liquid area
      const height = Math.min((tempC / 100) * maxHeight, maxHeight);
      
      liquid.style.height = `${Math.max(height, 4)}px`;
      liquid.setAttribute('y', (94 - height).toString());
      
      // Update color class
      liquid.classList.remove(
        'thermometer__liquid--cool',
        'thermometer__liquid--normal',
        'thermometer__liquid--warm',
        'thermometer__liquid--hot'
      );
      
      thermo.classList.remove('thermometer--cool', 'thermometer--normal', 'thermometer--warm', 'thermometer--hot');
      
      if (tempC > 85) {
        liquid.classList.add('thermometer__liquid--hot');
        thermo.classList.add('thermometer--hot');
      } else if (tempC > 70) {
        liquid.classList.add('thermometer__liquid--warm');
        thermo.classList.add('thermometer--warm');
      } else if (tempC > 50) {
        liquid.classList.add('thermometer__liquid--normal');
        thermo.classList.add('thermometer--normal');
      } else {
        liquid.classList.add('thermometer__liquid--cool');
        thermo.classList.add('thermometer--cool');
      }
    }
  }
  
  renderLineChart(canvas, dataPoints, options = {}) {
    if (!canvas || !dataPoints || dataPoints.length < 2) return;
    
    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    
    // Set actual canvas size for sharp rendering
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    
    const width = rect.width;
    const height = rect.height;
    const padding = { top: 10, right: 10, bottom: 20, left: 30 };
    
    const drawWidth = width - padding.left - padding.right;
    const drawHeight = height - padding.top - padding.bottom;
    
    // Clear
    ctx.clearRect(0, 0, width, height);
    
    // Find min/max
    const values = dataPoints.map(d => d.value);
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const range = maxVal - minVal || 1;
    
    // Draw grid lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    
    for (let i = 0; i <= 4; i++) {
      const y = padding.top + (drawHeight / 4) * i;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
    }
    
    ctx.setLineDash([]);
    
    // Draw Y-axis labels
    ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
    ctx.font = '9px JetBrains Mono, monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    
    for (let i = 0; i <= 4; i++) {
      const value = maxVal - (range / 4) * i;
      const y = padding.top + (drawHeight / 4) * i;
      ctx.fillText(value.toFixed(0), padding.left - 5, y);
    }
    
    // Calculate points
    const points = dataPoints.map((d, i) => ({
      x: padding.left + (i / (dataPoints.length - 1)) * drawWidth,
      y: padding.top + drawHeight - ((d.value - minVal) / range) * drawHeight
    }));
    
    // Draw gradient fill
    ctx.beginPath();
    ctx.moveTo(points[0].x, height - padding.bottom);
    points.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.lineTo(points[points.length - 1].x, height - padding.bottom);
    ctx.closePath();
    
    const gradient = ctx.createLinearGradient(0, padding.top, 0, height - padding.bottom);
    gradient.addColorStop(0, 'rgba(0, 212, 255, 0.2)');
    gradient.addColorStop(1, 'transparent');
    ctx.fillStyle = gradient;
    ctx.fill();
    
    // Draw line with gradient stroke
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    
    // Catmull-Rom spline interpolation
    for (let i = 0; i < points.length - 1; i++) {
      const p0 = points[Math.max(i - 1, 0)];
      const p1 = points[i];
      const p2 = points[Math.min(i + 1, points.length - 1)];
      const p3 = points[Math.min(i + 2, points.length - 1)];
      
      for (let t = 0; t <= 1; t += 0.1) {
        const x = catmullRom(p0.x, p1.x, p2.x, p3.x, t);
        const y = catmullRom(p0.y, p1.y, p2.y, p3.y, t);
        ctx.lineTo(x, y);
      }
    }
    
    const strokeGradient = ctx.createLinearGradient(padding.left, 0, width - padding.right, 0);
    strokeGradient.addColorStop(0, '#00d4ff');
    strokeGradient.addColorStop(1, '#a855f7');
    
    ctx.strokeStyle = strokeGradient;
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.stroke();
  }
  
  announceCriticalChanges(data) {
    // Announce important changes to screen reader users
    if (!this.elements.announcer) return;
    
    const messages = [];
    
    if (data.gpus && data.gpus[0]) {
      const gpu = data.gpus[0];
      
      if (gpu.gpu_utilization > 90) {
        messages.push(`GPU usage critically high at ${gpu.gpu_utilization.toFixed(0)}%`);
      }
      
      if (gpu.temperature && gpu.temperature > 85) {
        messages.push(`GPU temperature warning: ${gpu.temperature.toFixed(0)} degrees Celsius`);
      }
    }
    
    if (data.prediction && data.prediction.risk_level === 'critical') {
      messages.push('Prediction indicates critical VRAM shortage risk');
    }
    
    if (messages.length > 0) {
      this.elements.announcer.textContent = messages.join('. ');
    }
  }
  
  // ==========================================================================
  // PUBLIC API (公共接口)
  // ==========================================================================
  
  async show() {
    if (this.state.isVisible) return;
    
    this.elements.root.classList.remove('um-root--hidden');
    this.elements.root.classList.remove('um-root--closing');
    this.elements.panel.setAttribute('aria-expanded', 'true');
    
    this.state.isVisible = true;
    
    // Trigger entrance animation
    requestAnimationFrame(() => {
      this.elements.panel.style.animation = 'none';  // Reset
      void this.elements.panel.offsetWidth;  // Force reflow
      this.elements.panel.style.animation = '';
    });
  }
  
  hide() {
    if (!this.state.isVisible) return;
    
    this.elements.panel.classList.add('hover-panel--closing');
    
    setTimeout(() => {
      this.elements.root.classList.add('um-root--hidden');
      this.elements.panel.classList.remove('hover-panel--closing');
      this.elements.panel.setAttribute('aria-expanded', 'false');
    }, 200);
    
    this.state.isVisible = false;
  }
  
  toggle() {
    if (this.state.isVisible) {
      this.hide();
    } else {
      this.show();
    }
  }
  
  collapse() {
    if (this.state.isCollapsed) return;
    
    this.elements.root.classList.add('um-root--collapsed');
    this.elements.panel.classList.add('hover-panel--collapsed');
    this.elements.panel.setAttribute('aria-expanded', 'false');
    
    if (this.elements.collapseBtn) {
      this.elements.collapseBtn.classList.add('is-active');
    }
    
    this.state.isCollapsed = true;
  }
  
  expand() {
    if (!this.state.isCollapsed) return;
    
    this.elements.root.classList.remove('um-root--collapsed');
    this.elements.panel.classList.remove('hover-panel--collapsed');
    this.elements.panel.setAttribute('aria-expanded', 'true');
    
    if (this.elements.collapseBtn) {
      this.elements.collapseBtn.classList.remove('is-active');
    }
    
    this.state.isCollapsed = false;
  }
  
  toggleCollapse() {
    if (this.state.isCollapsed) {
      this.expand();
    } else {
      this.collapse();
    }
  }
  
  setTheme(themeName) {
    this.config.theme = themeName;
    this.applyTheme(themeName);
  }
  
  applyTheme(themeName) {
    this.elements.root.setAttribute('data-theme', themeName);
  }
  
  setPosition(position) {
    this.config.position = position;
    this.applyPosition(position);
  }
  
  applyPosition(position) {
    this.elements.root.className = `um-root um-root--position-${position}`;
  }
  
  initAnimations() {
    // Initialize ripple effects
    if (typeof initRippleEffects === 'function') {
      initRippleEffects();
    }
    
    // Initialize lazy animations
    if (typeof initLazyAnimations === 'function') {
      initLazyAnimations();
    }
  }
  
  showError(message) {
    this.state.hasError = true;
    this.state.isLoading = false;
    
    // You could show an error state in the panel here
    console.error('[UniversalMonitor] Error:', message);
  }
  
  handleResize() {
    // Redraw charts on resize
    if (this.state.currentData) {
      this.updateCharts(this.state.currentData);
    }
  }
  
  handleReducedMotionChange() {
    // Re-initialize animations with reduced motion settings
    this.initAnimations();
  }
  
  /**
   * Destroy the instance and cleanup
   */
  destroy() {
    // Stop updates
    this.pauseUpdates();
    
    // Remove event listeners
    // (In a real implementation, you'd store references and remove them)
    
    // Destroy animation controllers
    Object.values(this.animators).forEach(animator => {
      if (animator.destroy) animator.destroy();
    });
    
    // Remove DOM
    if (this.elements.root && this.elements.root.parentNode) {
      this.elements.root.parentNode.removeChild(this.elements.root);
    }
    
    // Clear state
    this.state.isInitialized = false;
    
    console.log('[UniversalMonitor] Destroyed');
  }
}

// ============================================================================
// CATMULL-ROM SPLINE HELPER (Catmull-Rom 样条插值辅助函数)
// ============================================================================

function catmullRom(p0, p1, p2, p3, t) {
  const t2 = t * t;
  const t3 = t2 * t;
  return 0.5 * (
    (2 * p1) +
    (-p0 + p2) * t +
    (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
    (-p0 + 3 * p1 - 3 * p2 + p3) * t3
  );
}

// ============================================================================
// DEBOUNCE UTILITY (防抖工具函数)
// ============================================================================

function debounce(func, wait = 16) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// ============================================================================
// EXPORTS (导出)
// ============================================================================

// Export for ES modules and CommonJS
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { UniversalMonitorUI };
} else if (typeof window !== 'undefined') {
  window.UniversalMonitorUI = UniversalMonitorUI;
}
