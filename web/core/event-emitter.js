/**
 * ============================================================================
 * ComfyUI-Feixue-UniversalMonitor - Event Emitter (Event Bus)
 * ============================================================================
 *
 * Lightweight publish-subscribe event bus for decoupled component communication.
 * Avoids global variable pollution and provides a clean API for inter-component
 * messaging within the UniversalMonitor UI.
 *
 * Features:
 * - O(1) on/off operations via Map-based storage
 * - Wildcard listener support ('*' matches all events)
 * - Namespace grouping ('gpu:*' matches all GPU-related events)
 * - Built-in debounce/throttle decorators
 * - Memory leak protection with maxListeners threshold
 * - Chainable API (returns `this` from mutation methods)
 *
 * @author Feixue
 * @version 1.0.0
 * @license MIT
 * ============================================================================
 */

'use strict';

/**
 * Lightweight publish-subscribe event bus.
 * Provides decoupled communication between UI components without global state.
 *
 * @class EventEmitter
 * @example
 * import { globalEventBus } from './event-emitter.js';
 *
 * // Basic usage
 * globalEventBus.on('data:update', (payload) => console.log(payload));
 * globalEventBus.emit('data:update', { cpu: 45 });
 *
 * // Namespace pattern
 * globalEventBus.on('gpu:*', (event, data) => console.log(event, data));
 * globalEventBus.emit('gpu:temperature', 72);
 *
 * // Debounced listener
 * globalEventBus.onDebounced('resize', handleResize, 200);
 */
class EventEmitter {
  /**
   * Creates an EventEmitter instance.
   * @param {Object} [options={}] - Configuration options.
   * @param {number} [options.maxListeners=20] - Maximum listeners per event before warning.
   */
  constructor(options = {}) {
    /**
     * Internal event storage. Keyed by event name, values are arrays of listener objects.
     * Each listener object: { callback, once, priority, context }
     * @type {Map<string, Array<Object>>}
     * @private
     */
    this._events = new Map();

    /**
     * Maximum number of listeners per event before emitting a memory leak warning.
     * @type {number}
     * @private
     */
    this._maxListeners = options.maxListeners || 20;

    /**
     * Tracks debounce/throttle timer IDs for cleanup.
     * @type {Map<string, number>}
     * @private
     */
    this._timers = new Map();
  }

  // ---------------------------------------------------------------------------
  // Core API
  // ---------------------------------------------------------------------------

  /**
   * Register an event listener.
   * Supports namespaced events (e.g., 'data:update') and priority ordering.
   *
   * @param {string} event - Event name. Supports namespace syntax ('category:action').
   *                         Use '*' as wildcard to listen to all events.
   * @param {Function} callback - Listener function to invoke when event fires.
   * @param {Object} [options={}] - Listener options.
   * @param {boolean} [options.once=false] - If true, listener is removed after first invocation.
   * @param {number} [options.priority=0] - Higher priority listeners are called first.
   * @param {*} [options.context=null] - `this` binding for the callback.
   * @returns {EventEmitter} This instance (enables chaining).
   *
   * @example
   * bus.on('data:update', handler, { once: true, priority: 10 });
   */
  on(event, callback, options = {}) {
    if (typeof callback !== 'function') {
      throw new TypeError(`EventEmitter.on(): callback must be a function, got ${typeof callback}`);
    }
    if (typeof event !== 'string' || event.length === 0) {
      throw new TypeError('EventEmitter.on(): event must be a non-empty string');
    }

    if (!this._events.has(event)) {
      this._events.set(event, []);
    }

    const listeners = this._events.get(event);

    // Memory leak protection
    if (listeners.length >= this._maxListeners) {
      console.warn(
        `[EventEmitter] Possible memory leak detected. ` +
        `${listeners.length} listeners registered for event "${event}". ` +
        `Max is ${this._maxListeners}.`
      );
    }

    const listener = {
      callback,
      once: !!options.once,
      priority: typeof options.priority === 'number' ? options.priority : 0,
      context: options.context || null,
    };

    // Insert in priority order (higher priority = called first)
    const insertIndex = listeners.findIndex(
      (existing) => existing.priority < listener.priority
    );
    if (insertIndex === -1) {
      listeners.push(listener);
    } else {
      listeners.splice(insertIndex, 0, listener);
    }

    return this;
  }

  /**
   * Register a one-time event listener.
   * Automatically removed after its first invocation.
   *
   * @param {string} event - Event name.
   * @param {Function} callback - Listener function.
   * @param {Object} [options={}] - Same options as `.on()`, `once` is implicitly true.
   * @returns {EventEmitter} This instance.
   */
  once(event, callback, options = {}) {
    return this.on(event, callback, { ...options, once: true });
  }

  /**
   * Remove event listener(s).
   *
   * - `off()` - Remove ALL listeners from ALL events (full reset).
   * - `off('event')` - Remove all listeners for a specific event.
   * - `off('event', callback)` - Remove a specific listener from an event.
   *
   * @param {string} [event] - Event name. Omit to clear all events.
   * @param {Function} [callback] - Specific listener to remove. Omit to clear all for this event.
   * @returns {EventEmitter} This instance.
   */
  off(event, callback) {
    // Clear everything
    if (arguments.length === 0) {
      this._events.clear();
      this._clearAllTimers();
      return this;
    }

    // Clear specific event
    if (arguments.length === 1 || callback === undefined) {
      this._events.delete(event);
      return this;
    }

    // Remove specific listener
    if (this._events.has(event)) {
      const listeners = this._events.get(event);
      const filtered = listeners.filter((l) => l.callback !== callback);
      if (filtered.length === 0) {
        this._events.delete(event);
      } else {
        this._events.set(event, filtered);
      }
    }

    return this;
  }

  /**
   * Emit an event, invoking all registered listeners with the provided arguments.
   * Also triggers wildcard ('*') and namespace-matched listeners.
   *
   * @param {string} event - Event name to emit.
   * @param {...*} args - Arguments forwarded to each listener.
   * @returns {boolean} True if at least one listener was invoked, false otherwise.
   *
   * @example
   * bus.emit('data:update', { cpu: 45 }, 'extra-arg');
   */
  emit(event, ...args) {
    let invoked = false;

    // 1. Invoke exact-match listeners
    if (this._events.has(event)) {
      const listeners = [...this._events.get(event)]; // snapshot to allow mutations during iteration
      invoked = this._invokeListeners(listeners, event, args) || invoked;
    }

    // 2. Invoke wildcard listeners ('*')
    if (this._events.has('*')) {
      const wildcards = [...this._events.get('*')];
      invoked = this._invokeListeners(wildcards, event, args) || invoked;
    }

    // 3. Invoke namespace-matched listeners (e.g., 'gpu:*' matches 'gpu:temperature')
    for (const [pattern, listeners] of this._events) {
      if (pattern !== '*' && pattern.endsWith(':*') && this._matchNamespace(pattern, event)) {
        const nsListeners = [...listeners];
        invoked = this._invokeListeners(nsListeners, event, args) || invoked;
      }
    }

    return invoked;
  }

  // ---------------------------------------------------------------------------
  // Decorator Methods
  // ---------------------------------------------------------------------------

  /**
   * Register a debounced event listener.
   * The callback will fire only after `delay` ms of silence since the last emit.
   *
   * @param {string} event - Event name.
   * @param {Function} callback - Debounced listener function.
   * @param {number} [delay=300] - Debounce delay in milliseconds.
   * @param {Object} [options={}] - Additional listener options (passed to .on()).
   * @returns {EventEmitter} This instance.
   *
   * @example
   * bus.onDebounced('resize', handleResize, 200);
   */
  onDebounced(event, callback, delay = 300, options = {}) {
    if (typeof callback !== 'function') {
      throw new TypeError('EventEmitter.onDebounced(): callback must be a function');
    }

    const timerKey = `${event}:debounced:${callback.name || 'anonymous'}`;
    const debouncedFn = (...args) => {
      const existingTimer = this._timers.get(timerKey);
      if (existingTimer) {
        clearTimeout(existingTimer);
      }
      const timerId = setTimeout(() => {
        callback.apply(null, args);
        this._timers.delete(timerKey);
      }, delay);
      this._timers.set(timerKey, timerId);
    };

    // Store reference so we can clean up later
    debouncedFn._originalCallback = callback;
    debouncedFn._timerKey = timerKey;

    return this.on(event, debouncedFn, options);
  }

  /**
   * Register a throttled event listener.
   * The callback will fire at most once every `interval` ms.
   *
   * @param {string} event - Event name.
   * @param {Function} callback - Throttled listener function.
   * @param {number} [interval=300] - Throttle interval in milliseconds.
   * @param {Object} [options={}] - Additional listener options (passed to .on()).
   * @returns {EventEmitter} This instance.
   *
   * @example
   * bus.onThrottled('scroll', handleScroll, 100);
   */
  onThrottled(event, callback, interval = 300, options = {}) {
    if (typeof callback !== 'function') {
      throw new TypeError('EventEmitter.onThrottled(): callback must be a function');
    }

    const timerKey = `${event}:throttled:${callback.name || 'anonymous'}`;
    let lastCallTime = 0;
    let timerId = null;

    const throttledFn = (...args) => {
      const now = Date.now();
      const elapsed = now - lastCallTime;

      if (elapsed >= interval) {
        // Enough time has passed - execute immediately
        lastCallTime = now;
        callback.apply(null, args);
      } else if (!timerId) {
        // Schedule execution for the remaining time
        timerId = setTimeout(() => {
          lastCallTime = Date.now();
          callback.apply(null, args);
          timerId = null;
        }, interval - elapsed);
        this._timers.set(timerKey, timerId);
      }
    };

    throttledFn._originalCallback = callback;
    throttledFn._timerKey = timerKey;

    return this.on(event, throttledFn, options);
  }

  // ---------------------------------------------------------------------------
  // Query & Utility Methods
  // ---------------------------------------------------------------------------

  /**
   * Remove all listeners and clear all timers.
   * @returns {EventEmitter} This instance.
   */
  clear() {
    this._events.clear();
    this._clearAllTimers();
    return this;
  }

  /**
   * Get the number of listeners registered for a given event.
   * @param {string} event - Event name.
   * @returns {number} Listener count. Returns 0 if event has no listeners.
   */
  listenerCount(event) {
    if (!this._events.has(event)) return 0;
    return this._events.get(event).length;
  }

  /**
   * Get the total count of all registered listeners across all events.
   * @returns {number} Total listener count.
   */
  totalCount() {
    let total = 0;
    for (const listeners of this._events.values()) {
      total += listeners.length;
    }
    return total;
  }

  /**
   * Get an array of all event names that currently have registered listeners.
   * @returns {string[]} Array of event names.
   */
  eventNames() {
    return Array.from(this._events.keys());
  }

  /**
   * Check if any listeners are registered for a given event.
   * @param {string} event - Event name.
   * @returns {boolean} True if the event has at least one listener.
   */
  hasListeners(event) {
    return this._events.has(event) && this._events.get(event).length > 0;
  }

  // ---------------------------------------------------------------------------
  // Private Helpers
  // ---------------------------------------------------------------------------

  /**
   * Invoke a list of listeners, handling `once` removal and `context` binding.
   * @param {Array<Object>} listeners - Array of listener objects.
   * @param {string} event - The event name being emitted.
   * @param {Array} args - Arguments to forward to callbacks.
   * @returns {boolean} Whether any listeners were actually invoked.
   * @private
   */
  _invokeListeners(listeners, event, args) {
    if (listeners.length === 0) return false;

    let invoked = false;
    const toRemove = [];

    for (let i = 0; i < listeners.length; i++) {
      const listener = listeners[i];
      try {
        const ctx = listener.context || null;
        listener.callback.apply(ctx, args);
        invoked = true;
      } catch (error) {
        console.error(`[EventEmitter] Error in listener for "${event}":`, error);
      }

      if (listener.once) {
        toRemove.push(listener.callback);
      }
    }

    // Remove `once` listeners after the full iteration
    if (toRemove.length > 0) {
      const current = this._events.get(event) || [];
      const filtered = current.filter((l) => !toRemove.includes(l.callback));
      if (filtered.length === 0) {
        this._events.delete(event);
      } else {
        this._events.set(event, filtered);
      }
    }

    return invoked;
  }

  /**
   * Check if an event name matches a namespace pattern (e.g., 'gpu:*' matches 'gpu:temp').
   * @param {string} pattern - Namespace pattern ending with ':*'.
   * @param {string} event - Actual event name.
   * @returns {boolean} True if the event matches the namespace.
   * @private
   */
  _matchNamespace(pattern, event) {
    const prefix = pattern.slice(0, -1); // remove trailing '*'
    return event.startsWith(prefix) && event.length > prefix.length;
  }

  /**
   * Clear all active debounce/throttle timers.
   * @private
   */
  _clearAllTimers() {
    for (const [key, timerId] of this._timers) {
      clearTimeout(timerId);
    }
    this._timers.clear();
  }
}

// ---------------------------------------------------------------------------
// Singleton Export
// ---------------------------------------------------------------------------

/**
 * Global singleton instance of EventEmitter.
 * Use this shared instance for application-wide event communication.
 *
 * @type {EventEmitter}
 * @example
 * import { globalEventBus } from './core/event-emitter.js';
 * globalEventBus.on('app:ready', initApp);
 */
export const globalEventBus = new EventEmitter();

export default EventEmitter;
