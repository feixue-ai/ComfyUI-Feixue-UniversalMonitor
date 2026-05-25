/**
 * ============================================================================
 * ComfyUI-Feixue-UniversalMonitor - WebSocket Service (POLLING REMOVED)
 * ============================================================================
 *
 * Real-time data communication layer for the UniversalMonitor dashboard.
 * Provides WebSocket client with automatic reconnection, heartbeat detection.
 *
 * ⚠️ **P0 CRITICAL FIX**: HTTP polling has been completely removed!
 *
 * **Why Polling Was Removed**:
 * - Caused DOM forced async repaint every 1 second (setInterval + fetch)
 * - Interrupted mouse drag and hover event streams
 * - Triggered "click/drag not responding" frozen UI feeling
 * - Generated Layout/Recalculate Style events during user interactions
 *
 * **Current Architecture** (WebSocket-Only):
 * - Connection state machine (CONNECTING → CONNECTED → DISCONNECTED → RECONNECTING)
 * - Exponential backoff reconnection (1s → 2s → 4s → 8s → 16s → 30s max)
 * - Heartbeat detection (30s interval, 3 missed = disconnect)
 * - Offline message queue (max 10 latest messages)
 * - User-visible error overlay on failure (NO silent fallback!)
 *
 * Features:
 * - Connection state machine with robust lifecycle management
 * - Exponential backoff reconnection strategy
 * - Heartbeat ping/pong mechanism for connection health
 * - Offline message queue for reliable delivery
 * - Fatal error display instead of silent degradation
 *
 * @author Feixue
 * @version 2.0.0 (P0 FIX - Polling Removed)
 * @license MIT
 * ============================================================================
 */

'use strict';

import { globalEventBus } from '../core/event-emitter.js';

// =============================================================================
// WebSocket Service
// =============================================================================

/**
 * WebSocket client manager with robust connection management.
 *
 * Implements a state machine for connection lifecycle management:
 * - DISCONNECTED → connect() → CONNECTING
 * - CONNECTING → onopen → CONNECTED
 * - CONNECTED → onclose → RECONNECTING (if auto-reconnect) / DISCONNECTED
 * - CONNECTED → onerror → RECONNECTING
 * - RECONNECTING → setTimeout → CONNECTING
 * - RECONNECTING → disconnect(true) → DISCONNECTED → DISCONNECTED
 *
 * @class WebSocketService
 * @example
 * import { WebSocketService } from './services/websocket-service.js';
 *
 * const wsService = new WebSocketService({ url: 'ws://localhost:8765/ws' });
 * wsService.init(globalEventBus);
 * wsService.connect();
 *
 * wsService.on('data', (message) => {
 *   console.log('Received:', message);
 * });
 */
class WebSocketService {
  /**
   * Creates a WebSocket service instance.
   * @param {Object} [options={}] - Configuration options.
   * @param {string} [options.url] - WebSocket server URL. Defaults to `ws://${host}/ws/feixue_monitor`.
   * @param {boolean} [options.reconnect=true] - Enable automatic reconnection.
   * @param {number} [options.maxReconnectDelay=30000] - Maximum reconnection delay in ms (30s).
   * @param {number} [options.heartbeatInterval=30000] - Heartbeat ping interval in ms (30s).
   * @param {number} [options.maxMissedHeartbeats=3] - Max missed heartbeats before disconnect.
   * @param {number} [options.offlineQueueSize=10] - Maximum offline queue size.
   */
  constructor(options = {}) {
    /**
     * WebSocket server URL.
     * @type {string}
     */
    this.url = options.url || `ws://${window.location.host}/ws/feixue_monitor`;

    /**
     * Whether automatic reconnection is enabled.
     * @type {boolean}
     */
    this.reconnectEnabled = options.reconnect !== false;

    /**
     * Maximum reconnection delay in milliseconds.
     * @type {number}
     */
    this.maxReconnectDelay = options.maxReconnectDelay || 30000; // 30s

    /**
     * Heartbeat ping interval in milliseconds.
     * @type {number}
     */
    this.heartbeatInterval = options.heartbeatInterval || 30000; // 30s

    /**
     * Maximum number of missed heartbeats before forcing disconnect.
     * @type {number}
     */
    this.maxMissedHeartbeats = options.maxMissedHeartbeats || 3;

    /**
     * Maximum number of messages cached in offline queue.
     * @type {number}
     */
    this.offlineQueueSize = options.offlineQueueSize || 10;

    // -------------------------------------------------------------------------
    // State Machine
    // -------------------------------------------------------------------------

    /**
     * Current connection state.
     * Possible values: 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED' | 'DISCONNECTING' | 'RECONNECTING'
     * @type {string}
     * @private
     */
    this._state = 'DISCONNECTED';

    /**
     * Raw WebSocket instance.
     * @type {WebSocket|null}
     * @private
     */
    this._ws = null;

    /**
     * Reconnection timer ID.
     * @type {number|null}
     * @private
     */
    this._reconnectTimer = null;

    /**
     * Heartbeat interval timer ID.
     * @type {number|null}
     * @private
     */
    this._heartbeatTimer = null;

    /**
     * Count of consecutive missed heartbeats.
     * @type {number}
     * @private
     */
    this._heartbeatMissed = 0;

    /**
     * Current reconnection delay (starts at 1000ms, doubles each attempt).
     * @type {number}
     * @private
     */
    this._reconnectDelay = 1000;

    /**
     * Queue for messages sent while disconnected.
     * @type {Array<Object>}
     * @private
     */
    this._offlineQueue = [];

    /**
     * Global event emitter instance (injected via init()).
     * @type {EventEmitter|null}
     * @private
     */
    this._eventEmitter = null;

    // -------------------------------------------------------------------------
    // Statistics
    // -------------------------------------------------------------------------

    /**
     * Connection and message statistics.
     * @type {Object}
     * @property {number} connections - Total successful connections.
     * @property {number} messagesReceived - Total messages received.
     * @property {number} messagesSent - Total messages sent.
     * @property {number} reconnectCount - Total reconnection attempts.
     * @property {number|null} lastMessageTime - Timestamp of last received message.
     * @property {number} averageLatency - Rolling average network latency in ms.
     */
    this._stats = {
      connections: 0,
      messagesReceived: 0,
      messagesSent: 0,
      reconnectCount: 0,
      lastMessageTime: null,
      averageLatency: 0
    };

    /**
     * Latency samples for rolling average calculation.
     * @type {Array<number>}
     * @private
     */
    this._latencySamples = [];

    /**
     * Maximum number of latency samples to keep for average calculation.
     * @type {number}
     * @private
     */
    this._maxLatencySamples = 10;
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Initialize the service with the global event emitter.
   * Must be called before connect().
   *
   * @param {EventEmitter} eventEmitter - The global event bus instance.
   * @throws {TypeError} If eventEmitter is not provided or invalid.
   *
   * @example
   * wsService.init(globalEventBus);
   */
  init(eventEmitter) {
    if (!eventEmitter || typeof eventEmitter.emit !== 'function') {
      throw new TypeError('WebSocketService.init(): eventEmitter must be an EventEmitter instance');
    }
    this._eventEmitter = eventEmitter;
  }

  /**
   * Establish WebSocket connection to the server.
   * No-op if already connected or connecting.
   */
  connect() {
    this._connect();
  }

  /**
   * Disconnect from the WebSocket server.
   *
   * @param {boolean} [reconnect=false] - If true, will schedule reconnection after disconnect.
   *                                      If false, disables future reconnections.
   */
  disconnect(reconnect = false) {
    // Clear reconnection timer
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }

    // Stop heartbeat
    this._stopHeartbeat();

    // Close WebSocket if open
    if (this._ws) {
      try {
        // Remove event handlers to prevent _handleClose from triggering reconnect
        this._ws.onopen = null;
        this._ws.onmessage = null;
        this._ws.onerror = null;
        this._ws.onclose = null;

        if (this._ws.readyState === WebSocket.OPEN ||
            this._ws.readyState === WebSocket.CONNECTING) {
          this._ws.close(1000, 'Client disconnect');
        }
      } catch (error) {
        console.warn('[WS] Error during disconnect:', error);
      }

      this._ws = null;
    }

    const wasConnected = this._state === 'CONNECTED';
    this._setState('DISCONNECTED');

    // Disable reconnection unless explicitly requested
    if (!reconnect) {
      this.reconnectEnabled = false;
    }

    if (wasConnected) {
      this._emit('disconnected', {
        code: 1000,
        reason: 'Client disconnect',
        clean: true
      });
    }

    console.log('[WS] Disconnected');
  }

  /**
   * Send a message to the WebSocket server.
   * If disconnected, queues the message for later delivery (up to offlineQueueSize).
   *
   * @param {Object|string|number|boolean} data - Data to send. Objects are JSON-stringified.
   * @returns {boolean} True if message was sent immediately, false if queued.
   *
   * @example
   * wsService.send({ type: 'subscribe', channels: ['gpu', 'cpu'] });
   */
  send(data) {
    const message = typeof data === 'string' ? data : JSON.stringify(data);

    if (this._state === 'CONNECTED' && this._ws && this._ws.readyState === WebSocket.OPEN) {
      try {
        this._ws.send(message);
        this._stats.messagesSent++;
        return true;
      } catch (error) {
        console.error('[WS] Send failed:', error);
        return this._queueOfflineMessage(data);
      }
    } else {
      return this._queueOfflineMessage(data);
    }
  }

  /**
   * Register an event listener on this service.
   * Delegates to the internal event emitter.
   *
   * @param {string} event - Event name ('data', 'connected', 'disconnected', 'error', etc.)
   * @param {Function} callback - Listener function.
   * @returns {WebSocketService} This instance (chainable).
   */
  on(event, callback) {
    if (this._eventEmitter) {
      this._eventEmitter.on(event, callback);
    }
    return this;
  }

  /**
   * Remove an event listener from this service.
   *
   * @param {string} event - Event name.
   * @param {Function} callback - Listener function to remove.
   * @returns {WebSocketService} This instance (chainable).
   */
  off(event, callback) {
    if (this._eventEmitter) {
      this._eventEmitter.off(event, callback);
    }
    return this;
  }

  // ---------------------------------------------------------------------------
  // Getters
  // ---------------------------------------------------------------------------

  /**
   * Current connection state.
   * @type {string}
   * @readonly
   */
  get state() {
    return this._state;
  }

  /**
   * Whether the WebSocket is currently connected and ready.
   * @type {boolean}
   * @readonly
   */
  get isConnected() {
    return this._state === 'CONNECTED';
  }

  /**
   * Copy of current statistics (immutable snapshot).
   * @type {Object}
   * @readonly
   */
  get stats() {
    return { ...this._stats };
  }

  /**
   * Number of messages currently in the offline queue.
   * @type {number}
   * @readonly
   */
  get offlineQueueLength() {
    return this._offlineQueue.length;
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Connection Management
  // ---------------------------------------------------------------------------

  /**
   * Internal connection implementation.
   * Enforces state machine rules and creates WebSocket instance.
   * @private
   */
  _connect() {
    // State guard: prevent duplicate connections
    if (this._state === 'CONNECTED' || this._state === 'CONNECTING') {
      console.warn('[WS] Already connecting or connected, ignoring connect() call');
      return;
    }

    this._setState('CONNECTING');

    try {
      console.log(`[WS] Connecting to ${this.url}...`);

      this._ws = new WebSocket(this.url);

      this._ws.onopen = () => this._handleOpen();
      this._ws.onmessage = (event) => this._handleMessage(event);
      this._ws.onclose = (event) => this._handleClose(event);
      this._ws.onerror = (error) => this._handleError(error);

    } catch (error) {
      console.error('[WS] Connection failed:', error);
      this._setState('DISCONNECTED');
      this._scheduleReconnect();
    }
  }

  /**
   * Handle WebSocket open event.
   * Transitions to CONNECTED state and starts heartbeat.
   * @private
   */
  _handleOpen() {
    this._setState('CONNECTED');
    this._stats.connections++;
    this._reconnectDelay = 1000; // Reset exponential backoff
    this._heartbeatMissed = 0;

    // Start heartbeat mechanism
    this._startHeartbeat();

    // Flush any queued offline messages
    this._flushOfflineQueue();

    // Emit connected event
    this._emit('connected', {
      connections: this._stats.connections,
      url: this.url
    });

    console.log(`[WS] Connected (${this.url}) - Connection #${this._stats.connections}`);
  }

  /**
   * Handle WebSocket message event.
   * Parses JSON, handles pong responses, and dispatches data events.
   * @param {MessageEvent} event - WebSocket message event.
   * @private
   */
  _handleMessage(event) {
    const startTime = performance.now();

    this._stats.messagesReceived++;
    this._stats.lastMessageTime = Date.now();

    try {
      const message = JSON.parse(event.data);

      // Handle pong response (heartbeat acknowledgment)
      if (message.type === 'pong') {
        this._heartbeatMissed = 0; // Reset missed counter

        // Calculate network round-trip latency
        if (message.timestamp) {
          const latency = Date.now() - message.timestamp;
          this._updateAverageLatency(latency);
        }
        return;
      }

      // Dispatch data message to listeners
      this._emit('data', message);

      // Type-specific event for targeted listening
      const dataType = message.type || 'snapshot';
      this._emit(`data:${dataType}`, message);

    } catch (error) {
      console.error('[WS] Message parse error:', error, '\nRaw data:', event.data);
      this._emit('error', {
        type: 'parse_error',
        message: error.message,
        raw: event.data
      });
    }

    // Performance logging (message processing should be < 1ms)
    const processingTime = performance.now() - startTime;
    if (processingTime > 1) {
      console.warn(`[WS] Slow message processing: ${processingTime.toFixed(2)}ms`);
    }
  }

  /**
   * Handle WebSocket close event.
   * Manages state transition and schedules reconnection if appropriate.
   * @param {CloseEvent} event - WebSocket close event.
   * @private
   */
  _handleClose(event) {
    this._stopHeartbeat();

    const wasConnected = this._state === 'CONNECTED';
    this._setState('DISCONNECTED');

    if (wasConnected) {
      this._emit('disconnected', {
        code: event.code,
        reason: event.reason || 'Unknown reason',
        clean: event.wasClean || false
      });

      console.log(
        `[WS] Disconnected (code=${event.code}, reason="${event.reason}", clean=${event.wasClean})`
      );
    }

    // Schedule reconnection unless:
    // 1. Reconnection is disabled
    // 2. It was a normal closure (code 1000)
    if (this.reconnectEnabled && event.code !== 1000) {
      this._scheduleReconnect();
    }
  }

  /**
   * Handle WebSocket error event.
   * Logs error and triggers reconnection flow.
   * @param {Event} error - WebSocket error event.
   * @private
   */
  _handleError(error) {
    console.error('[WS] Connection error:', error);
    this._emit('error', {
      type: 'connection_error',
      message: 'WebSocket connection error'
    });

    // Error is usually followed by close event, but handle it here too
    if (this._state === 'CONNECTED' || this._state === 'CONNECTING') {
      this._scheduleReconnect();
    }
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Reconnection Logic
  // ---------------------------------------------------------------------------

  /**
   * Schedule a reconnection attempt using exponential backoff.
   * @private
   */
  _scheduleReconnect() {
    // Guard: don't schedule if already reconnecting or disabled
    if (!this.reconnectEnabled || this._state === 'RECONNECTING') {
      return;
    }

    this._setState('RECONNECTING');
    this._stats.reconnectCount++;

    const delaySeconds = (this._reconnectDelay / 1000).toFixed(1);

    console.log(
      `[WS] Reconnecting in ${delaySeconds}s... ` +
      `(attempt #${this._stats.reconnectCount}, max delay: ${this.maxReconnectDelay / 1000}s)`
    );

    this._emit('reconnecting', {
      delay: this._reconnectDelay,
      attempt: this._stats.reconnectCount,
      maxDelay: this.maxReconnectDelay
    });

    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this._connect();
    }, this._reconnectDelay);

    // Exponential backoff: double the delay, cap at maxReconnectDelay
    this._reconnectDelay = Math.min(
      this._reconnectDelay * 2,
      this.maxReconnectDelay
    );
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Heartbeat Mechanism
  // ---------------------------------------------------------------------------

  /**
   * Start sending heartbeat pings at regular intervals.
   * Clears any existing heartbeat timer first.
   * @private
   */
  _startHeartbeat() {
    this._stopHeartbeat(); // Ensure no duplicate timers

    this._heartbeatTimer = setInterval(() => {
      if (this._state !== 'CONNECTED') return;
      if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;

      try {
        // Send ping with timestamp for latency calculation
        this._ws.send(JSON.stringify({
          type: 'ping',
          timestamp: Date.now()
        }));

        this._stats.messagesSent++;
        this._heartbeatMissed++;

        // Check if we've exceeded max missed heartbeats
        if (this._heartbeatMissed >= this.maxMissedHeartbeats) {
          console.warn(
            `[WS] Missed ${this._heartbeatMissed} heartbeats, ` +
            `forcing disconnect (threshold: ${this.maxMissedHeartbeats})`
          );

          // Force close due to heartbeat timeout
          if (this._ws) {
            try {
              this._ws.close(4001, 'Heartbeat timeout');
            } catch (e) {
              console.warn('[WS] Error closing after heartbeat timeout:', e);
            }
          }
        }
      } catch (error) {
        console.error('[WS] Heartbeat send failed:', error);
        this._heartbeatMissed++;
      }
    }, this.heartbeatInterval);
  }

  /**
   * Stop heartbeat mechanism and reset counters.
   * @private
   */
  _stopHeartbeat() {
    if (this._heartbeatTimer) {
      clearInterval(this._heartbeatTimer);
      this._heartbeatTimer = null;
    }
    this._heartbeatMissed = 0;
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Offline Queue
  // ---------------------------------------------------------------------------

  /**
   * Queue a message for delivery when connection is restored.
   * Evicts oldest messages when queue exceeds maxSize.
   *
   * @param {*} data - Message data to queue.
   * @returns {boolean} Always returns false (indicating not sent immediately).
   * @private
   */
  _queueOfflineMessage(data) {
    // Evict oldest message if at capacity
    while (this._offlineQueue.length >= this.offlineQueueSize) {
      const evicted = this._offlineQueue.shift();
      console.warn('[WS] Offline queue full, evicted oldest message:', evicted);
    }

    this._offlineQueue.push({
      data,
      timestamp: Date.now()
    });

    console.debug(`[WS] Queued offline message (${this._offlineQueue.length}/${this.offlineQueueSize})`);
    return false;
  }

  /**
   * Send all queued offline messages in order.
   * Called automatically after successful reconnection.
   * @private
   */
  _flushOfflineQueue() {
    if (this._offlineQueue.length === 0) return;

    console.log(`[WS] Flushing ${this._offlineQueue.length} queued messages`);

    const queueCopy = [...this._offlineQueue];
    this._offlineQueue = [];

    for (const item of queueCopy) {
      try {
        this.send(item.data);
      } catch (error) {
        console.error('[WS] Failed to flush queued message:', error);
      }
    }

    this._emit('queue_flushed', { count: queueCopy.length });
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Statistics & Utilities
  // ---------------------------------------------------------------------------

  /**
   * Update rolling average latency with new sample.
   * Keeps only the last `_maxLatencySamples` samples.
   *
   * @param {number} latency - New latency measurement in milliseconds.
   * @private
   */
  _updateAverageLatency(latency) {
    this._latencySamples.push(latency);

    // Keep only recent samples
    if (this._latencySamples.length > this._maxLatencySamples) {
      this._latencySamples.shift();
    }

    // Calculate average
    const sum = this._latencySamples.reduce((a, b) => a + b, 0);
    this._stats.averageLatency = Math.round(sum / this._latencySamples.length);
  }

  /**
   * Update internal state and emit state change event.
   *
   * @param {string} newState - New state value.
   * @private
   */
  _setState(newState) {
    const oldState = this._state;
    this._state = newState;

    if (oldState !== newState) {
      this._emit('state_changed', {
        from: oldState,
        to: newState
      });

      console.debug(`[WS] State: ${oldState} -> ${newState}`);
    }
  }

  /**
   * Safely emit an event through the event emitter.
   * Silently fails if emitter not initialized.
   *
   * @param {string} event - Event name.
   * @param {*} [data] - Event payload.
   * @private
   */
  _emit(event, data) {
    if (this._eventEmitter) {
      try {
        this._eventEmitter.emit(event, data);
      } catch (error) {
        console.error(`[WS] Error emitting event "${event}":`, error);
      }
    }
  }

  /**
   * Complete cleanup of all resources (timers, references, etc.).
   * Call this when the service instance is no longer needed to prevent memory leaks.
   */
  destroy() {
    this.disconnect(false); // Disconnect without reconnect

    // Clear all internal state
    this._offlineQueue = [];
    this._latencySamples = [];
    this._eventEmitter = null;

    console.log('[WS] Service destroyed, all resources cleaned up');
  }
}


// =============================================================================
// ❌ POLLING SERVICE REMOVED - P0 CRITICAL FIX
// =============================================================================
// HTTP polling has been completely removed due to critical UI performance issues:
//
// PROBLEMS CAUSED BY POLLING:
// - DOM forced async repaint every 1 second
// - Interrupts mouse drag and hover event streams
// - Causes "click/drag not responding" frozen UI feeling
// - Triggers Layout/Recalculate Style events during user interactions
//
// REPLACEMENT STRATEGY:
// - WebSocket connection is now MANDATORY (no fallback)
// - If WebSocket fails: show clear error message to user
// - User must refresh page (F5) to retry connection
// - Zero tolerance for silent degradation to polling
//
// SEE ALSO: DataService class below (refactored to enforce WebSocket-only)
// =============================================================================


// =============================================================================
// DataService (WebSocket-Only Mode - P0 CRITICAL FIX)
// =============================================================================

/**
 * WebSocket-only data communication service.
 *
 * ⚠️ **CRITICAL**: HTTP polling has been completely removed!
 * This service now enforces WebSocket-exclusive communication.
 *
 * **Design Decision Rationale**:
 * - Polling caused severe UI performance issues (DOM repaints every 1s)
 * - Interrupted mouse drag/hover events, causing "frozen UI" feeling
 * - Triggered Layout/Recalculate Style during user interactions
 *
 * **Behavior on WebSocket Failure**:
 * - ❌ NO silent fallback to polling (FORBIDDEN)
 * - ✅ Show clear error message to user
 * - ✅ Suggest page refresh (F5) to retry
 * - ✅ Emit 'critical-error' event for UI to display
 *
 * @class DataService
 * @example
 * import { DataService } from './services/websocket-service.js';
 *
 * const dataService = new DataService({
 *   ws: { url: 'ws://localhost:8765/ws/monitor' }
 * });
 *
 * dataService.init(globalEventBus);
 *
 * // Listen for data (WebSocket only)
 * dataService.on('data', (data) => updateUI(data));
 *
 * // Handle connection failure (NO polling fallback!)
 * dataService.on('critical-error', (error) => {
 *   showErrorToUser("WebSocket连接失败，请刷新页面");
 * });
 */
class DataService {
  /**
   * Creates a DataService instance (WebSocket-only mode).
   * @param {Object} [options={}] - Configuration options.
   * @param {Object} [options.ws={}] - WebSocket configuration passed to WebSocketService.
   * @param {string} [options.mode='websocket'] - Only 'websocket' is supported (polling removed).
   */
  constructor(options = {}) {
    /**
     * Configuration options.
     * @type {Object}
     * @private
     */
    this._options = options;

    /**
     * Current operating mode (always 'websocket' - polling removed).
     * @type {'websocket'}
     * @private
     */
    this._mode = 'websocket'; // Forced to websocket-only

    /**
     * Currently active transport service instance (WebSocket only).
     * @type {WebSocketService|null}
     * @private
     */
    this._activeService = null;

    /**
     * Global event emitter instance.
     * @type {EventEmitter|null}
     * @private
     */
    this._eventEmitter = null;
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Initialize the data service with the global event emitter.
   * Attempts to establish WebSocket connection immediately.
   *
   * @param {EventEmitter} eventEmitter - The global event bus instance.
   * @throws {TypeError} If eventEmitter is invalid.
   */
  init(eventEmitter) {
    if (!eventEmitter || typeof eventEmitter.emit !== 'function') {
      throw new TypeError('DataService.init(): eventEmitter must be an EventEmitter instance');
    }

    this._eventEmitter = eventEmitter;

    // Force WebSocket-only mode (no polling fallback!)
    this._establishWebSocket();
  }

  /**
   * Register an event listener (delegates to WebSocket service).
   *
   * @param {string} event - Event name.
   * @param {Function} callback - Listener function.
   * @returns {DataService} This instance (chainable).
   */
  on(event, callback) {
    if (this._activeService && typeof this._activeService.on === 'function') {
      this._activeService.on(event, callback);
    }
    return this;
  }

  /**
   * Remove an event listener (delegates to WebSocket service).
   *
   * @param {string} event - Event name.
   * @param {Function} callback - Listener to remove.
   * @returns {DataService} This instance (chainable).
   */
  off(event, callback) {
    if (this._activeService && typeof this._activeService.off === 'function') {
      this._activeService.off(event, callback);
    }
    return this;
  }

  /**
   * Send data through WebSocket.
   *
   * @param {*} data - Data to send.
   * @returns {boolean} True if sent successfully, false otherwise.
   */
  send(data) {
    if (this._activeService && typeof this._activeService.send === 'function') {
      return this._activeService.send(data);
    }
    console.warn('[DataService] Cannot send: WebSocket not connected');
    return false;
  }

  /**
   * Attempt to re-establish WebSocket connection after failure.
   * Useful for manual recovery or retry logic.
   */
  forceReconnect() {
    console.log('[DataService] User requested WebSocket reconnection');

    // Cleanup existing service
    if (this._activeService) {
      try {
        if (typeof this._activeService.destroy === 'function') {
          this._activeService.destroy();
        } else if (typeof this._activeService.disconnect === 'function') {
          this._activeService.disconnect(false);
        }
      } catch (error) {
        console.warn('[DataService] Error during cleanup:', error);
      }

      this._activeService = null;
    }

    // Re-establish WebSocket connection
    this._establishWebSocket();
  }

  // ---------------------------------------------------------------------------
  // Getters
  // ---------------------------------------------------------------------------

  /**
   * Current transport mode (always 'websocket').
   * @type {'websocket'}
   * @readonly
   */
  get mode() {
    return this._mode; // Always returns 'websocket'
  }

  /**
   * Whether WebSocket service is active and connected.
   * @type {boolean}
   * @readonly
   */
  get isActive() {
    return this._activeService !== null && this._activeService.isConnected;
  }

  /**
   * Statistics from the WebSocket service.
   * @type {Object|null}
   * @readonly
   */
  get stats() {
    return this._activeService ? this._activeService.stats : null;
  }

  /**
   * Name of the active transport (always 'websocket').
   * @type {'websocket'|null}
   * @readonly
   */
  get activeTransport() {
    return this._activeService instanceof WebSocketService ? 'websocket' : null;
  }

  // ---------------------------------------------------------------------------
  // Private Methods - WebSocket Management
  // ---------------------------------------------------------------------------

  /**
   * Establish WebSocket connection with error handling.
   * On failure: shows error message instead of falling back to polling.
   * @private
   */
  _establishWebSocket() {
    // Check browser support
    if (typeof WebSocket === 'undefined' || WebSocket === null) {
      const errorMsg = '您的浏览器不支持WebSocket，无法使用监控功能';

      console.error(`[DataService] 🔴 ${errorMsg}`);

      // Emit critical error for UI to display
      this._emit('critical-error', {
        type: 'browser_unsupported',
        message: errorMsg,
        suggestion: '请使用现代浏览器（Chrome/Firefox/Edge）并刷新页面',
        fatal: true
      });

      // Show user-visible error (NOT silent degradation!)
      this._showFatalError(errorMsg, '请使用Chrome、Firefox或Edge等现代浏览器');
      return;
    }

    // Create and initialize WebSocket service
    try {
      this._activeService = new WebSocketService(this._options.ws || {});
      this._activeService.init(this._eventEmitter);

      // Monitor for connection errors (but DO NOT fall back to polling!)
      this._activeService.on('error', ({ type, message }) => {
        console.error(`[DataService] WebSocket error: ${type} - ${message}`);

        if (type === 'connection_error') {
          this._emit('warning', {
            message: 'WebSocket连接出现问题',
            willRetry: true,
            willNotFallback: true // Explicitly state no polling fallback
          });
        }
      });

      // Monitor for repeated reconnection failures
      this._activeService.on('reconnecting', ({ attempt }) => {
        console.warn(`[DataService] WebSocket重连第 ${attempt} 次...`);

        // After multiple failures, show persistent error (still no polling!)
        if (attempt >= 3) {
          const errorMsg = `WebSocket连接已失败${attempt}次，请检查网络后刷新页面`;

          console.error(`[DataService] 🔴 ${errorMsg}`);

          this._emit('persistent-failure', {
            attempt: attempt,
            message: errorMsg,
            suggestion: '按F5刷新页面重试'
          });
        }
      });

      // Start connection
      this._activeService.connect();

      console.log('[DataService] ✅ WebSocket传输层已初始化（纯WebSocket模式，无轮询降级）');

    } catch (error) {
      const errorMsg = `WebSocket服务初始化失败: ${error.message}`;

      console.error(`[DataService] 🔴 ${errorMsg}`);

      // Emit critical error (DO NOT fall back to polling!)
      this._emit('critical-error', {
        type: 'initialization_failed',
        message: errorMsg,
        suggestion: '请按F5刷新页面重试',
        error: error.toString(),
        fatal: true
      });

      // Show user-visible error
      this._showFatalError(
        '监控服务连接初始化失败',
        '请按F5刷新页面重试连接'
      );
    }
  }

  /**
   * Display a user-visible fatal error message.
   * Creates an overlay that cannot be ignored (unlike silent polling fallback).
   *
   * @param {string} title - Error title.
   * @param {string} suggestion - User action suggestion.
   * @private
   */
  _showFatalError(title, suggestion) {
    // Ensure DOM is ready
    if (!document.body) {
      document.addEventListener('DOMContentLoaded', () => this._showFatalError(title, suggestion));
      return;
    }

    // Remove existing error overlay if present
    const existingOverlay = document.getElementById('feixue-critical-error-overlay');
    if (existingOverlay) {
      existingOverlay.remove();
    }

    // Create error overlay
    const overlay = document.createElement('div');
    overlay.id = 'feixue-critical-error-overlay';
    overlay.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: rgba(0, 0, 0, 0.85);
      color: #ff4444;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      z-index: 999999;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      text-align: center;
      padding: 20px;
    `;

    overlay.innerHTML = `
      <div style="
        max-width: 600px;
        background: rgba(20, 20, 20, 0.95);
        border: 2px solid #ff4444;
        border-radius: 12px;
        padding: 40px;
        box-shadow: 0 10px 40px rgba(255, 68, 68, 0.3);
      ">
        <h1 style="color: #ff4444; margin: 0 0 20px 0; font-size: 28px;">
          ❌ 飞雪监测器连接失败
        </h1>
        <p style="color: #ffffff; font-size: 18px; margin: 15px 0; line-height: 1.6;">
          ${title}
        </p>
        <p style="color: #ffaa00; font-size: 16px; margin: 20px 0; line-height: 1.5;">
          💡 ${suggestion}
        </p>
        <button onclick="location.reload()" style="
          background: linear-gradient(135deg, #0066ff, #0044cc);
          color: white;
          border: none;
          padding: 15px 40px;
          font-size: 18px;
          border-radius: 8px;
          cursor: pointer;
          margin-top: 20px;
          transition: transform 0.2s, box-shadow 0.2s;
        " onmouseover="this.style.transform='scale(1.05)'; this.style.boxShadow='0 6px 20px rgba(0,102,255,0.4)'"
           onmouseout="this.style.transform='scale(1)'; this.style.boxShadow='none'">
          🔄 立即刷新页面 (F5)
        </button>
        <p style="color: #888888; font-size: 12px; margin-top: 25px; line-height: 1.4;">
          注意：本监控器已禁用HTTP轮询模式以避免UI卡顿<br>
          必须建立WebSocket连接才能正常工作
        </p>
      </div>
    `;

    document.body.appendChild(overlay);

    console.error('[DataService] 🔴 已显示致命错误提示（用户可见），拒绝静默降级到轮询');
  }

  /**
   * Safely emit an event through the event emitter.
   * @param {string} event - Event name.
   * @param {*} [data] - Payload.
   * @private
   */
  _emit(event, data) {
    if (this._eventEmitter) {
      try {
        this._eventEmitter.emit(event, data);
      } catch (error) {
        console.error(`[DataService] Error emitting event "${event}":`, error);
      }
    }
  }

  /**
   * Complete cleanup of all resources.
   * Must be called when the DataService instance is no longer needed.
   */
  destroy() {
    if (this._activeService) {
      try {
        if (typeof this._activeService.destroy === 'function') {
          this._activeService.destroy();
        } else if (typeof this._activeService.disconnect === 'function') {
          this._activeService.disconnect(false);
        }
      } catch (error) {
        console.warn('[DataService] Error during cleanup:', error);
      }

      this._activeService = null;
    }

    this._eventEmitter = null;

    console.log('[DataService] ✅ 已销毁（纯WebSocket模式，零轮询代码）');
  }
}


// =============================================================================
// Exports (WebSocket-Only - PollingService REMOVED)
// =============================================================================

export {
  WebSocketService,
  DataService
  // ❌ PollingService has been removed due to P0 critical UI performance issues
  // See: https://example.com/polling-removal-rationale (internal doc)
};

export default DataService;
