/**
 * ============================================================================
 * ComfyUI-Feixue-UniversalMonitor - Configuration Manager
 * ============================================================================
 *
 * Centralized UI configuration manager with localStorage persistence.
 * Provides deep merge strategy (user config overrides defaults), dot-path
 * access for nested values, type validation, and config version migration.
 *
 * Design decisions:
 * - Singleton pattern: one ConfigManager instance per application lifecycle.
 * - Lazy caching: reads from localStorage only once, then operates on in-memory cache.
 * - Event-driven: emits change events when any config value is modified,
 *   enabling reactive UI updates without polling.
 *
 * @author Feixue
 * @version 1.0.0
 * @license MIT
 * ============================================================================
 */

'use strict';

import { globalEventBus } from './event-emitter.js';

/**
 * Current configuration schema version. Increment this when the shape of
 * `_defaults` changes to trigger automatic migration of stale user data.
 * @type {number}
 * @private
 */
const CONFIG_VERSION = 1;

/**
 * The localStorage key prefix used for namespacing.
 * @type {string}
 * @private
 */
const STORAGE_KEY_PREFIX = 'fxm_';

/**
 * UI Configuration Manager.
 * Manages all user-configurable settings with persistence and reactivity.
 *
 * @class ConfigManager
 * @example
 * import config from './core/config-manager.js';
 *
 * // Initialize with event bus
 * config.init(globalEventBus);
 *
 * // Read config with dot-path
 * const theme = config.get('theme');              // 'cyberpunk-dark'
 * const cpuVisible = config.get('metrics.cpu.visible'); // true
 *
 * // Write config (auto-persists + emits events)
 * config.set('theme', 'neon-purple');
 *
 * // Listen for changes
 * config.onChange((value, path) => {
 *   console.log(`Config changed at ${path}:`, value);
 * }, 'theme');
 */
class ConfigManager {
  /**
   * Creates a ConfigManager instance.
   * @param {string} [namespace='fxm_config'] - Namespace for localStorage isolation.
   */
  constructor(namespace = 'fxm_config') {
    /**
     * Storage namespace (used as part of the localStorage key).
     * @type {string}
     */
    this.namespace = namespace;

    /**
     * Full localStorage key: `fxm_{namespace}`.
     * @type {string}
     * @private
     */
    this._storageKey = STORAGE_KEY_PREFIX + namespace;

    /**
     * Default configuration values. These are used as fallbacks when no
     * user-defined value exists, and as the baseline after a reset().
     * @type {Object}
     * @private
     */
    this._defaults = {
      _v: CONFIG_VERSION,
      theme: 'cyberpunk-dark',
      refreshRate: 1000,
      showOnStartup: true,
      position: { x: 20, y: 20 },
      panelState: 'expanded',
      metrics: {
        pred: { visible: true, order: 0 },
        cpu:  { visible: true, order: 1 },
        ram:  { visible: true, order: 2 },
        gpu:  { visible: true, order: 3 },
        vram: { visible: true, order: 4 },
        rsv:  { visible: true, order: 5 },
        pwr:  { visible: false, order: 6 },
      },
      animations: {
        enabled: true,
        duration: 300,
      },
      performance: {
        enableCountUp: false,
        maxDataPoints: 120,
        renderFPS: 30,
      },
    };

    /**
     * In-memory cache of the merged configuration (defaults + user overrides).
     * Null until `init()` is called.
     * @type {Object|null}
     * @private
     */
    this._cache = null;

    /**
     * Reference to the EventEmitter instance used for broadcasting changes.
     * Set via `init()`.
     * @type {EventEmitter|null}
     * @private
     */
    this._eventEmitter = null;
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  /**
   * Initialize the configuration manager.
   * Loads persisted user config from localStorage, deep-merges with defaults,
   * runs migration if needed, and caches the result in memory.
   *
   * @param {EventEmitter} eventEmitter - Global event bus for emitting change notifications.
   * @returns {ConfigManager} This instance (enables chaining).
   *
   * @example
   * config.init(globalEventBus);
   */
  init(eventEmitter) {
    if (!(eventEmitter && typeof eventEmitter.on === 'function')) {
      throw new TypeError('ConfigManager.init(): eventEmitter must be an EventEmitter instance');
    }
    this._eventEmitter = eventEmitter;

    try {
      const raw = localStorage.getItem(this._storageKey);
      let userConfig = null;

      if (raw) {
        userConfig = JSON.parse(raw);

        // Version migration
        if (userConfig && typeof userConfig._v === 'number' && userConfig._v < CONFIG_VERSION) {
          console.warn(
            `[ConfigManager] Migrating config from v${userConfig._v} to v${CONFIG_VERSION}`
          );
          userConfig = this._migrate(userConfig);
        }
      }

      // Deep merge: defaults <- userConfig
      this._cache = this._deepMerge(this._clone(this._defaults), userConfig || {});
    } catch (error) {
      console.error('[ConfigManager] Failed to load config from localStorage:', error);
      // Fall back to pure defaults
      this._cache = this._clone(this._defaults);
    }

    return this;
  }

  // ---------------------------------------------------------------------------
  // Read / Write API
  // ---------------------------------------------------------------------------

  /**
   * Get a configuration value by dot-notation path.
   * Returns the default value if the path does not exist or cache is not initialized.
   *
   * @param {string} path - Dot-separated path (e.g., 'metrics.cpu.visible').
   *                         Omit path to retrieve the entire config object (copy).
   * @param {*} [defaultValue=undefined] - Fallback value if path resolves to undefined.
   * @returns {*} The resolved value, or defaultValue.
   *
   * @example
   * config.get('theme');                    // 'cyberpunk-dark'
   * config.get('metrics.gpu.visible');       // true
   * config.get('nonexistent', 42);           // 42
   * config.get();                            // { theme: ..., metrics: ... } (full copy)
   */
  get(path, defaultValue = undefined) {
    if (!this._cache) {
      console.warn('[ConfigManager] get() called before init(). Returning default.');
      return defaultValue;
    }

    // Return full config clone if no path specified
    if (path === undefined || path === null) {
      return this._clone(this._cache);
    }

    if (typeof path !== 'string') {
      console.warn(`[ConfigManager] get(): expected string path, got ${typeof path}`);
      return defaultValue;
    }

    const value = this._resolvePath(this._cache, path);
    return value !== undefined ? value : defaultValue;
  }

  /**
   * Set a configuration value by dot-notation path.
   * Automatically persists to localStorage and emits a 'config:change' event.
   *
   * @param {string} path - Dot-separated path (e.g., 'theme', 'metrics.cpu.visible').
   * @param {*} value - Value to set.
   * @returns {ConfigManager} This instance.
   *
   * @example
   * config.set('theme', 'neon-purple');
   * config.set('metrics.pwr.visible', true);
   */
  set(path, value) {
    if (!this._cache) {
      throw new Error('[ConfigManager] set() called before init(). Call init() first.');
    }

    if (typeof path !== 'string' || path.length === 0) {
      throw new TypeError('[ConfigManager] set(): path must be a non-empty string');
    }

    // Type validation against defaults
    const defaultVal = this._resolvePath(this._defaults, path);
    if (defaultVal !== undefined && value !== null && typeof value !== typeof defaultVal && typeof defaultVal !== 'undefined') {
      console.warn(
        `[ConfigManager] Type mismatch at "${path}": expected ${typeof defaultVal}, got ${typeof value}. ` +
        `Setting anyway, but this may cause issues.`
      );
    }

    const oldValue = this._resolvePath(this._cache, path);
    this._setAtPath(this._cache, path, value);

    // Persist to localStorage
    this._persist();

    // Emit change event
    if (this._eventEmitter) {
      this._eventEmitter.emit('config:change', {
        path,
        value,
        oldValue,
        config: this._clone(this._cache),
      });
    }

    return this;
  }

  /**
   * Reset all configuration back to defaults.
   * Clears localStorage and resets the in-memory cache.
   * Emits a 'config:reset' event.
   *
   * @returns {ConfigManager} This instance.
   */
  reset() {
    this._cache = this._clone(this._defaults);
    this._persist();

    if (this._eventEmitter) {
      this._eventEmitter.emit('config:reset', { config: this._clone(this._cache) });
    }

    return this;
  }

  // ---------------------------------------------------------------------------
  // Change Observation
  // ---------------------------------------------------------------------------

  /**
   * Register a callback to invoke when configuration changes.
   *
   * @param {Function} callback - Called with `(newValue, fullPath, eventData)`.
   * @param {string|null} [path=null] - If provided, only fire when this specific path changes.
   *                                     If null/omitted, fires for any config change.
   * @returns {Function} Unsubscribe function. Call it to stop listening.
   *
   * @example
   * // Listen to all changes
   * const unsub = config.onChange((val, path) => console.log(path, val));
   *
   * // Listen to a specific path only
   * config.onChange((val) => console.log('Theme changed:', val), 'theme');
   *
   * // Later: unsubscribe
   * unsub();
   */
  onChange(callback, path = null) {
    if (typeof callback !== 'function') {
      throw new TypeError('ConfigManager.onChange(): callback must be a function');
    }

    const wrapper = (eventData) => {
      // If path filter is set, only respond to matching paths
      if (path !== null && eventData.path !== path) return;
      callback(eventData.value, eventData.path, eventData);
    };

    if (this._eventEmitter) {
      this._eventEmitter.on('config:change', wrapper);
    }

    // Return unsubscribe function
    return () => {
      if (this._eventEmitter) {
        this._eventEmitter.off('config:change', wrapper);
      }
    };
  }

  // ---------------------------------------------------------------------------
  // Debug & Export
  // ---------------------------------------------------------------------------

  /**
   * Export the current full configuration as a plain object (deep clone).
   * Useful for debugging or serialization.
   *
   * @returns {Object} Complete configuration snapshot.
   */
  exportConfig() {
    if (!this._cache) {
      console.warn('[ConfigManager] exportConfig() called before init(). Returning empty object.');
      return {};
    }
    return this._clone(this._cache);
  }

  /**
   * Get the current configuration schema version.
   * @returns {number}
   */
  get version() {
    return CONFIG_VERSION;
  }

  /**
   * Check whether the manager has been initialized (cache populated).
   * @returns {boolean}
   */
  get isReady() {
    return this._cache !== null;
  }

  // ---------------------------------------------------------------------------
  // Private Helpers
  // ---------------------------------------------------------------------------

  /**
   * Resolve a dot-notation path within an object.
   * @param {Object} obj - Target object.
   * @param {string} path - Dot-separated path.
   * @returns {*} Resolved value, or undefined if any segment is missing.
   * @private
   */
  _resolvePath(obj, path) {
    const keys = path.split('.');
    let current = obj;

    for (const key of keys) {
      if (current === null || current === undefined || typeof current !== 'object') {
        return undefined;
      }
      current = current[key];
    }

    return current;
  }

  /**
   * Set a value at a dot-notation path within an object, creating intermediate
   * objects as needed.
   * @param {Object} obj - Target object (mutated in place).
   * @param {string} path - Dot-separated path.
   * @param {*} value - Value to assign.
   * @private
   */
  _setAtPath(obj, path, value) {
    const keys = path.split('.');
    let current = obj;

    for (let i = 0; i < keys.length - 1; i++) {
      const key = keys[i];
      if (
        current[key] === null ||
        current[key] === undefined ||
        typeof current[key] !== 'object'
      ) {
        current[key] = {};
      }
      current = current[key];
    }

    current[keys[keys.length - 1]] = value;
  }

  /**
   * Deep merge source into target. Source values override target values.
   * Arrays are replaced (not concatenated). Plain objects are merged recursively.
   * @param {Object} target - Base object (defaults).
   * @param {Object} source - Override object (user config).
   * @returns {Object} New merged object (neither argument is mutated).
   * @private
   */
  _deepMerge(target, source) {
    const result = this._clone(target);

    for (const key of Object.keys(source)) {
      if (
        source[key] &&
        typeof source[key] === 'object' &&
        !Array.isArray(source[key]) &&
        result[key] &&
        typeof result[key] === 'object' &&
        !Array.isArray(result[key])
      ) {
        // Both are plain objects -- recurse
        result[key] = this._deepMerge(result[key], source[key]);
      } else {
        // Primitives, arrays, or type mismatch -- source wins
        result[key] = this._clone(source[key]);
      }
    }

    return result;
  }

  /**
   * Deep clone a plain object or array. Handles primitives, dates, and regex.
   * Uses structuredClone where available, falls back to JSON round-trip.
   * @param {*} value - Value to clone.
   * @returns {*} Cloned value.
   * @private
   */
  _clone(value) {
    if (value === null || value === undefined) return value;
    if (typeof value !== 'object') return value; // primitive

    try {
      // structuredClone handles Date, RegExp, Map, Set, etc.
      if (typeof structuredClone === 'function') {
        return structuredClone(value);
      }
    } catch (_) {
      // structuredClone may fail on non-transferable objects
    }

    // Fallback: JSON round-trip (loses Date, RegExp, etc.)
    return JSON.parse(JSON.stringify(value));
  }

  /**
   * Persist the current in-memory cache to localStorage.
   * @private
   */
  _persist() {
    try {
      localStorage.setItem(this._storageKey, JSON.stringify(this._cache));
    } catch (error) {
      console.error('[ConfigManager] Failed to persist config to localStorage:', error);
      // Possible causes: storage quota exceeded, private browsing, etc.
    }
  }

  /**
   * Migrate an older config schema to the current version.
   * Add migration steps here as CONFIG_VERSION increments.
   * @param {Object} oldConfig - Parsed old config from localStorage.
   * @returns {Object} Migrated config ready for merging.
   * @private
   */
  _migrate(oldConfig) {
    const migrated = this._clone(oldConfig);

    // Example future migrations:
    //
    // if (migrated._v < 2) {
    //   // Rename 'panelVisible' -> 'showOnStartup'
    //   if ('panelVisible' in migrated) {
    //     migrated.showOnStartup = migrated.panelVisible;
    //     delete migrated.panelVisible;
    //   }
    // }

    migrated._v = CONFIG_VERSION;
    return migrated;
  }
}

// ---------------------------------------------------------------------------
// Singleton Export
// ---------------------------------------------------------------------------

/**
 * Global singleton instance of ConfigManager.
 * Call `.init(globalEventBus)` before using other methods.
 *
 * @type {ConfigManager}
 * @example
 * import config from './core/config-manager.js';
 * config.init(globalEventBus);
 * console.log(config.get('theme'));
 */
export default new ConfigManager();
