/**
 * SEMReactiveCard — Reactive base class for interactive SEM cards
 *
 * Provides Lit-like behavior without the Lit dependency:
 * - Declarative watched entities with automatic shouldUpdate
 * - Template-based rendering with DOM diffing (no innerHTML rebuild)
 * - Built-in freeze/thaw for optimistic service call handling
 * - Automatic event handler cleanup
 *
 * Subclasses define:
 *   static get watchedEntities() — array of entity IDs to watch
 *   _buildTemplate() — returns HTML string for initial render
 *   _applyState(root) — updates DOM elements with current values
 */

class SEMReactiveCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._hass = null;
        this._config = null;
        this._rendered = false;
        this._lang = null;
        this._localizeReady = false;
        this._prevEntityStates = {};
        this._frozenEntities = {};
        this._holdTimers = {};
        this._holdIntervals = {};
    }

    // ── Translation ──
    _t(key) {
        const lang = this._hass?.language;
        return (typeof semLocalize === 'function') ? semLocalize(key, lang) : key;
    }

    // ── Entity state readers ──
    _state(entityId, fallback = 0) {
        const frozen = this._frozenEntities[entityId];
        if (frozen) return frozen.value;
        const e = this._hass?.states[entityId];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) || fallback;
    }

    _stateStr(entityId) {
        const e = this._hass?.states[entityId];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }

    _stateAttrs(entityId) {
        return this._hass?.states[entityId]?.attributes || {};
    }

    // ── Freeze/thaw for optimistic updates ──
    _freezeEntity(entityId, value) {
        const existing = this._frozenEntities[entityId];
        if (existing?.timer) clearTimeout(existing.timer);
        this._frozenEntities[entityId] = {
            value,
            timer: setTimeout(() => {
                delete this._frozenEntities[entityId];
                this._applyIfMounted();
            }, 1000),
        };
    }

    _isFrozen() {
        return Object.keys(this._frozenEntities).length > 0;
    }

    // ── Service calls ──
    async _callService(domain, service, data) {
        if (!this._hass) return;
        try {
            await this._hass.callService(domain, service, data);
        } catch (e) {
            console.error(`[SEM ${this.tagName}]`, e);
        }
    }

    _setNumber(entityId, value) {
        const entity = this._hass?.states[entityId];
        if (!entity) return;
        const min = parseFloat(entity.attributes.min) || 0;
        const max = parseFloat(entity.attributes.max) || 100;
        const clamped = Math.max(min, Math.min(max, value));
        this._freezeEntity(entityId, clamped);
        this._applyIfMounted();
        this._callService('number', 'set_value', { entity_id: entityId, value: clamped });
    }

    _stepNumber(entityId, delta) {
        const entity = this._hass?.states[entityId];
        if (!entity) return;
        const frozen = this._frozenEntities[entityId];
        const current = frozen ? frozen.value : (parseFloat(entity.state) || 0);
        const step = parseFloat(entity.attributes.step) || 1;
        this._setNumber(entityId, current + delta * step);
    }

    _toggleSwitch(entityId) {
        const state = this._hass?.states[entityId];
        if (!state) return;
        const newState = state.state === 'on' ? 'off' : 'on';
        this._freezeEntity(entityId, newState);
        this._applyIfMounted();
        const svc = state.state === 'on' ? 'turn_off' : 'turn_on';
        this._callService('switch', svc, { entity_id: entityId });
    }

    _selectOption(entityId, option) {
        this._freezeEntity(entityId, option);
        this._applyIfMounted();
        this._callService('select', 'select_option', { entity_id: entityId, option });
    }

    // ── Hold-to-repeat for steppers ──
    _startHold(entityId, delta) {
        this._stopHold(entityId);
        this._holdTimers[entityId] = setTimeout(() => {
            this._holdIntervals[entityId] = setInterval(() => {
                this._stepNumber(entityId, delta);
            }, 150);
        }, 400);
    }

    _stopHold(entityId) {
        clearTimeout(this._holdTimers[entityId]);
        clearInterval(this._holdIntervals[entityId]);
        delete this._holdTimers[entityId];
        delete this._holdIntervals[entityId];
    }

    // ── Core: shouldUpdate via entity reference comparison ──
    set hass(hass) {
        const prevHass = this._hass;
        this._hass = hass;

        // Check locale change
        const lang = hass?.language;
        const hasLocalize = typeof semLocalize === 'function';
        let localeChanged = false;
        if (lang !== this._lang || (hasLocalize && !this._localizeReady)) {
            this._lang = lang;
            this._localizeReady = hasLocalize;
            localeChanged = true;
        }

        // While frozen, skip updates entirely
        if (this._isFrozen() && !localeChanged) return;

        // Check if any watched entity's STATE OBJECT reference changed
        // This is the key optimization — HA reuses the same object if the entity didn't change
        const watched = this.constructor.watchedEntities || [];
        let entityChanged = false;
        for (const id of watched) {
            const newState = hass.states[id];
            if (this._prevEntityStates[id] !== newState) {
                entityChanged = true;
                break;
            }
        }

        if (!entityChanged && !localeChanged && this._rendered) return;

        // Update reference cache
        for (const id of watched) {
            this._prevEntityStates[id] = hass.states[id];
        }

        // First render or locale change → full template build
        if (!this._rendered || localeChanged) {
            this._mountTemplate();
            return;
        }

        // Subsequent updates → patch values only (no innerHTML)
        this._applyIfMounted();
    }

    // ── Mount: build template once, then apply values ──
    _mountTemplate() {
        const html = this._buildTemplate();
        this.shadowRoot.innerHTML = html;
        this._rendered = true;
        this._bindEvents();
        this._applyState(this.shadowRoot);
    }

    _applyIfMounted() {
        if (!this._rendered || !this.shadowRoot) return;
        this._applyState(this.shadowRoot);
    }

    // ── Override in subclass ──
    _buildTemplate() { return '<div>Override _buildTemplate()</div>'; }
    _applyState(root) { /* Override: update DOM values */ }
    _bindEvents() { /* Override: bind click/input handlers */ }

    // ── Config ──
    setConfig(config) {
        this._config = config;
    }

    // ── Helpers for subclasses ──
    $(sel) { return this.shadowRoot?.querySelector(sel); }

    _setText(sel, text) {
        const el = this.$(sel);
        if (el && el.textContent !== text) el.textContent = text;
    }

    _setStyle(el, prop, value) {
        if (el && el.style[prop] !== value) el.style[prop] = value;
    }

    _setAttr(el, attr, value) {
        if (el && el.getAttribute(attr) !== value) el.setAttribute(attr, value);
    }

    // ── Lifecycle ──
    connectedCallback() {
        // Poll for semLocalize availability
        if (!this._localizeReady) {
            let attempts = 0;
            this._localizeCheckTimer = setInterval(() => {
                attempts++;
                if (typeof semLocalize === 'function' && this._hass) {
                    clearInterval(this._localizeCheckTimer);
                    this._localizeCheckTimer = null;
                    this.hass = this._hass; // re-trigger with translations
                } else if (attempts >= 50) {
                    clearInterval(this._localizeCheckTimer);
                    this._localizeCheckTimer = null;
                }
            }, 200);
        }
    }

    disconnectedCallback() {
        if (this._localizeCheckTimer) {
            clearInterval(this._localizeCheckTimer);
            this._localizeCheckTimer = null;
        }
        // Clean up hold timers
        for (const id of Object.keys(this._holdTimers)) this._stopHold(id);
        // Clean up freeze timers
        for (const id of Object.keys(this._frozenEntities)) {
            clearTimeout(this._frozenEntities[id]?.timer);
        }
        this._frozenEntities = {};
    }

    getCardSize() { return 4; }
}

// Export
if (typeof window !== 'undefined') {
    window.SEMReactiveCard = SEMReactiveCard;
}
