/**
 * Enigma - Client library for enigma display pages
 *
 * Provides:
 * - WebSocket connection management with auto-reconnect
 * - Cached state with delta updates
 * - Declarative HTML bindings for text, visibility, color, sprites
 * - Unit formatting (N -> KN -> MN -> GN etc)
 * - Watch/subscribe API for custom JS/WebGL
 *
 * See enigma/docs/DISPLAY_CONFIG.md for the tutorial.
 */

const Enigma = {
    _values: {},
    _listeners: new Map(),      // key -> Set of callbacks
    _globalListeners: [],       // called on any change
    _connected: false,
    _socket: null,
    _statusCallbacks: [],

    /**
     * Get current value for a key
     */
    get(key) {
        return this._values[key];
    },

    /**
     * Get all current values (returns copy)
     */
    getAll() {
        return { ...this._values };
    },

    /**
     * Check if a key exists
     */
    has(key) {
        return key in this._values;
    },

    /**
     * Watch specific key(s) for changes
     * @param {string|string[]} keys - Key or array of keys to watch
     * @param {function} fn - Callback(newValue, key, allValues)
     */
    watch(keys, fn) {
        const keyArray = Array.isArray(keys) ? keys : [keys];
        for (const key of keyArray) {
            if (!this._listeners.has(key)) {
                this._listeners.set(key, new Set());
            }
            this._listeners.get(key).add(fn);
        }
        return () => this.unwatch(keys, fn);
    },

    /**
     * Remove a watch
     */
    unwatch(keys, fn) {
        const keyArray = Array.isArray(keys) ? keys : [keys];
        for (const key of keyArray) {
            this._listeners.get(key)?.delete(fn);
        }
    },

    /**
     * Subscribe to all changes (for WebGL render loops etc)
     * @param {function} fn - Callback(deltaObject, allValues)
     */
    subscribe(fn) {
        this._globalListeners.push(fn);
        return () => {
            const idx = this._globalListeners.indexOf(fn);
            if (idx >= 0) this._globalListeners.splice(idx, 1);
        };
    },

    /**
     * Subscribe to connection status changes
     * @param {function} fn - Callback(isConnected)
     */
    onStatus(fn) {
        this._statusCallbacks.push(fn);
        fn(this._connected);  // Immediate callback with current state
        return () => {
            const idx = this._statusCallbacks.indexOf(fn);
            if (idx >= 0) this._statusCallbacks.splice(idx, 1);
        };
    },

    /**
     * Check connection status
     */
    isConnected() {
        return this._connected;
    },

    /**
     * Internal: Process incoming delta update
     */
    _update(deltas) {
        Object.assign(this._values, deltas);

        // Fire key-specific listeners
        for (const key of Object.keys(deltas)) {
            const listeners = this._listeners.get(key);
            if (listeners) {
                for (const fn of listeners) {
                    try {
                        fn(deltas[key], key, this._values);
                    } catch (e) {
                        console.error(`Enigma listener error for ${key}:`, e);
                    }
                }
            }
        }

        // Fire global listeners
        for (const fn of this._globalListeners) {
            try {
                fn(deltas, this._values);
            } catch (e) {
                console.error('Enigma global listener error:', e);
            }
        }

        // Update declarative bindings
        Bindings._processUpdate(deltas);
    },

    /**
     * Internal: Update connection status
     */
    _setConnected(connected) {
        this._connected = connected;
        for (const fn of this._statusCallbacks) {
            try {
                fn(connected);
            } catch (e) {
                console.error('Enigma status callback error:', e);
            }
        }
    },

    /**
     * Initialize WebSocket connection
     * Call this after DOM is ready, or it will auto-init on DOMContentLoaded
     */
    init() {
        if (this._socket) return;  // Already initialized

        if (typeof io === 'undefined') {
            console.error('Enigma: socket.io not loaded');
            return;
        }

        this._socket = io();

        this._socket.on('connect', () => {
            console.log('Enigma: Connected');
            this._setConnected(true);
            this._socket.emit('get_data');  // Request initial state
        });

        this._socket.on('disconnect', () => {
            console.log('Enigma: Disconnected');
            this._setConnected(false);
        });

        this._socket.on('update', (data) => {
            this._update(data);
        });

        this._socket.on('reload', () => {
            console.log('Enigma: Reload requested by host');
            window.location.reload();
        });

        // Initialize declarative bindings
        Bindings._init();
    }
};


/**
 * Units - Formatting utilities for physical units
 */
const Units = {
    _siPrefixes: [
        { threshold: 1e12, prefix: 'T', divisor: 1e12 },
        { threshold: 1e9,  prefix: 'G', divisor: 1e9 },
        { threshold: 1e6,  prefix: 'M', divisor: 1e6 },
        { threshold: 1e3,  prefix: 'K', divisor: 1e3 },
        { threshold: 0,    prefix: '',  divisor: 1 }
    ],

    /**
     * Format a number with SI prefix and unit
     * @param {number} value - The value to format
     * @param {string} unit - Unit suffix (e.g., 'N', 'W', 'm')
     * @param {number} decimals - Decimal places (default 1)
     * @returns {string} Formatted string like "167.0KN"
     */
    format(value, unit = '', decimals = 1) {
        if (value === null || value === undefined || isNaN(value)) {
            return '---' + unit;
        }
        const abs = Math.abs(value);
        const p = this._siPrefixes.find(p => abs >= p.threshold) || this._siPrefixes[this._siPrefixes.length - 1];
        return (value / p.divisor).toFixed(decimals) + p.prefix + unit;
    },

    /**
     * Format with fixed decimal places, no SI prefix
     */
    fixed(value, decimals = 2) {
        if (value === null || value === undefined || isNaN(value)) {
            return '---';
        }
        return value.toFixed(decimals);
    },

    /**
     * Format as percentage
     */
    percent(value, decimals = 0) {
        if (value === null || value === undefined || isNaN(value)) {
            return '---%';
        }
        return (value * 100).toFixed(decimals) + '%';
    },

    /**
     * Format as percentage where input is already 0-100
     */
    percent100(value, decimals = 0) {
        if (value === null || value === undefined || isNaN(value)) {
            return '---%';
        }
        return value.toFixed(decimals) + '%';
    }
};


/**
 * Bindings - Declarative HTML binding system
 *
 * Supported attributes:
 *
 * data-bind="Key"              - Bind text content to value
 * data-unit="N"                - Format with SI prefix + unit
 * data-decimals="2"            - Decimal places for numbers
 * data-format="percent"        - Special format: percent, percent100, fixed
 *
 * data-show="Key"              - Show element based on value
 * data-eq="VALUE"              - Show when value === VALUE
 * data-neq="VALUE"             - Show when value !== VALUE
 * data-gt="NUMBER"             - Show when value > NUMBER
 * data-gte="NUMBER"            - Show when value >= NUMBER
 * data-lt="NUMBER"             - Show when value < NUMBER
 * data-lte="NUMBER"            - Show when value <= NUMBER
 * data-in="A,B,C"              - Show when value is in list
 * data-notin="A,B,C"           - Show when value is not in list
 *
 * data-color="red:>800, yellow:>500, green:*"
 *                              - Set color based on thresholds (first match wins)
 *                              - Requires data-bind for the key
 *
 * data-sprite-switch="Key"     - Container for sprite switching
 *   (children have data-case="VALUE" to match)
 *
 * data-class-prefix="state-"   - Add class with prefix + value
 * data-class-bind="Key"        - Key to bind for class
 */
const Bindings = {
    _textBindings: [],      // {el, key, unit, decimals, format, colorRules}
    _showBindings: [],      // {el, key, condition, conditionValue}
    _spriteBindings: [],    // {container, key, cases: Map<value, element>}
    _classBindings: [],     // {el, key, prefix, currentClass}

    _init() {
        this._scanDOM();
    },

    _scanDOM() {
        // Text bindings
        document.querySelectorAll('[data-bind]').forEach(el => {
            const key = el.dataset.bind;
            const unit = el.dataset.unit || '';
            const decimals = el.dataset.decimals !== undefined ? parseInt(el.dataset.decimals) : 1;
            const format = el.dataset.format || null;
            const colorRules = el.dataset.color ? this._parseColorRules(el.dataset.color) : null;

            this._textBindings.push({ el, key, unit, decimals, format, colorRules });
        });

        // Show/hide bindings
        document.querySelectorAll('[data-show]').forEach(el => {
            const key = el.dataset.show;
            const binding = { el, key, condition: null, conditionValue: null };

            if (el.dataset.eq !== undefined) {
                binding.condition = 'eq';
                binding.conditionValue = el.dataset.eq;
            } else if (el.dataset.neq !== undefined) {
                binding.condition = 'neq';
                binding.conditionValue = el.dataset.neq;
            } else if (el.dataset.gt !== undefined) {
                binding.condition = 'gt';
                binding.conditionValue = parseFloat(el.dataset.gt);
            } else if (el.dataset.gte !== undefined) {
                binding.condition = 'gte';
                binding.conditionValue = parseFloat(el.dataset.gte);
            } else if (el.dataset.lt !== undefined) {
                binding.condition = 'lt';
                binding.conditionValue = parseFloat(el.dataset.lt);
            } else if (el.dataset.lte !== undefined) {
                binding.condition = 'lte';
                binding.conditionValue = parseFloat(el.dataset.lte);
            } else if (el.dataset.in !== undefined) {
                binding.condition = 'in';
                binding.conditionValue = el.dataset.in.split(',').map(s => s.trim());
            } else if (el.dataset.notin !== undefined) {
                binding.condition = 'notin';
                binding.conditionValue = el.dataset.notin.split(',').map(s => s.trim());
            } else {
                // Default: show if truthy
                binding.condition = 'truthy';
            }

            // Start hidden
            el.style.display = 'none';
            this._showBindings.push(binding);
        });

        // Sprite switch bindings
        document.querySelectorAll('[data-sprite-switch]').forEach(container => {
            const key = container.dataset.spriteSwitch;
            const cases = new Map();

            container.querySelectorAll('[data-case]').forEach(child => {
                const caseValue = child.dataset.case;
                cases.set(caseValue, child);
                child.style.display = 'none';  // Start all hidden
            });

            this._spriteBindings.push({ container, key, cases, currentCase: null });
        });

        // Class bindings
        document.querySelectorAll('[data-class-bind]').forEach(el => {
            const key = el.dataset.classBind;
            const prefix = el.dataset.classPrefix || '';
            this._classBindings.push({ el, key, prefix, currentClass: null });
        });
    },

    _parseColorRules(spec) {
        // Parse "red:>800, yellow:>500, green:*"
        const rules = [];
        for (const part of spec.split(',')) {
            const [color, condition] = part.trim().split(':');
            if (!condition || condition === '*') {
                rules.push({ color: color.trim(), condition: 'always' });
            } else if (condition.startsWith('>=')) {
                rules.push({ color: color.trim(), condition: 'gte', value: parseFloat(condition.slice(2)) });
            } else if (condition.startsWith('>')) {
                rules.push({ color: color.trim(), condition: 'gt', value: parseFloat(condition.slice(1)) });
            } else if (condition.startsWith('<=')) {
                rules.push({ color: color.trim(), condition: 'lte', value: parseFloat(condition.slice(2)) });
            } else if (condition.startsWith('<')) {
                rules.push({ color: color.trim(), condition: 'lt', value: parseFloat(condition.slice(1)) });
            } else if (condition.startsWith('=')) {
                rules.push({ color: color.trim(), condition: 'eq', value: condition.slice(1) });
            } else {
                // Treat as equality
                rules.push({ color: color.trim(), condition: 'eq', value: condition });
            }
        }
        return rules;
    },

    _evaluateCondition(condition, conditionValue, actualValue) {
        switch (condition) {
            case 'eq':
                return String(actualValue) === String(conditionValue);
            case 'neq':
                return String(actualValue) !== String(conditionValue);
            case 'gt':
                return actualValue > conditionValue;
            case 'gte':
                return actualValue >= conditionValue;
            case 'lt':
                return actualValue < conditionValue;
            case 'lte':
                return actualValue <= conditionValue;
            case 'in':
                return conditionValue.includes(String(actualValue));
            case 'notin':
                return !conditionValue.includes(String(actualValue));
            case 'truthy':
                return !!actualValue;
            case 'always':
                return true;
            default:
                return false;
        }
    },

    _getColor(rules, value) {
        for (const rule of rules) {
            if (this._evaluateCondition(rule.condition, rule.value, value)) {
                return rule.color;
            }
        }
        return null;
    },

    _formatValue(value, binding) {
        if (binding.format === 'percent') {
            return Units.percent(value, binding.decimals);
        } else if (binding.format === 'percent100') {
            return Units.percent100(value, binding.decimals);
        } else if (binding.format === 'fixed') {
            return Units.fixed(value, binding.decimals);
        } else if (binding.unit) {
            return Units.format(value, binding.unit, binding.decimals);
        } else if (typeof value === 'number') {
            return Units.fixed(value, binding.decimals);
        } else {
            return String(value ?? '---');
        }
    },

    _processUpdate(deltas) {
        const changedKeys = new Set(Object.keys(deltas));

        // Text bindings
        for (const binding of this._textBindings) {
            if (changedKeys.has(binding.key)) {
                const value = deltas[binding.key];
                binding.el.textContent = this._formatValue(value, binding);

                if (binding.colorRules) {
                    const color = this._getColor(binding.colorRules, value);
                    if (color) {
                        binding.el.style.color = color;
                    }
                }
            }
        }

        // Show/hide bindings
        for (const binding of this._showBindings) {
            if (changedKeys.has(binding.key)) {
                const value = deltas[binding.key];
                const show = this._evaluateCondition(binding.condition, binding.conditionValue, value);
                binding.el.style.display = show ? '' : 'none';
            }
        }

        // Sprite switch bindings
        for (const binding of this._spriteBindings) {
            if (changedKeys.has(binding.key)) {
                const value = String(deltas[binding.key]);

                // Hide current case
                if (binding.currentCase !== null) {
                    const oldEl = binding.cases.get(binding.currentCase);
                    if (oldEl) oldEl.style.display = 'none';
                }

                // Show new case
                const newEl = binding.cases.get(value);
                if (newEl) {
                    newEl.style.display = '';
                    binding.currentCase = value;
                } else {
                    binding.currentCase = null;
                }
            }
        }

        // Class bindings
        for (const binding of this._classBindings) {
            if (changedKeys.has(binding.key)) {
                const value = deltas[binding.key];
                const newClass = binding.prefix + value;

                if (binding.currentClass) {
                    binding.el.classList.remove(binding.currentClass);
                }
                binding.el.classList.add(newClass);
                binding.currentClass = newClass;
            }
        }
    }
};


// Auto-initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => Enigma.init());
} else {
    // DOM already ready (script loaded at end of body)
    setTimeout(() => Enigma.init(), 0);
}
