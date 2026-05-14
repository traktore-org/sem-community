/**
 * SEMLitBase — LitElement base class for all SEM dashboard cards
 *
 * Provides:
 * - Entity-reference shouldUpdate (only re-render when watched entities change)
 * - Freeze/thaw for optimistic service call handling
 * - Translation via semLocalize()
 * - Service call helpers (number, switch, select)
 * - Hold-to-repeat for stepper buttons
 */

import { LitElement, html, css, nothing } from 'lit';
import { semTheme } from './sem-shared.js';

export { html, css, nothing };

export class SEMLitBase extends LitElement {
    constructor() {
        super();
        this._hass = null;
        this._config = null;
        this._lang = null;
        this._localizeReady = false;
        this._prevVals = {};
        this._frozenEntities = {};
        this._holdTimers = {};
        this._holdIntervals = {};
        this._cachedTheme = null;
        this._updateTimer = null;
    }

    // ── hass setter with entity-reference shouldUpdate ──
    set hass(hass) {
        const old = this._hass;
        this._hass = hass;

        // Locale change detection
        const lang = hass?.language;
        const hasLocalize = typeof semLocalize === 'function';
        let localeChanged = false;
        if (lang !== this._lang || (hasLocalize && !this._localizeReady)) {
            this._lang = lang;
            this._localizeReady = hasLocalize;
            localeChanged = true;
        }

        // Skip while frozen (optimistic update in progress)
        if (this._isFrozen() && !localeChanged) return;

        // Value comparison — SEM coordinator recreates ALL state objects on every cycle,
        // so reference comparison (===) always triggers. Compare actual .state values instead.
        const watched = this.constructor.watchedEntities || [];
        let changed = false;
        for (const id of watched) {
            const newState = hass.states[id]?.state;
            if (this._prevVals[id] !== newState) {
                changed = true;
                break;
            }
        }
        if (!changed && !localeChanged) return;

        // Update value cache
        for (const id of watched) {
            this._prevVals[id] = hass.states[id]?.state;
        }

        this._scheduleUpdate();
    }

    get hass() {
        return this._hass;
    }

    // ── Debounced update — batches rapid state changes into single render ──
    _scheduleUpdate() {
        if (this._updateTimer) return; // already scheduled
        this._updateTimer = setTimeout(() => {
            this._updateTimer = null;
            this.requestUpdate();
        }, 16); // ~1 frame at 60fps
    }

    // ── Theme (cached — only recomputed once, then reused across renders) ──
    _theme() {
        if (!this._cachedTheme) {
            this._cachedTheme = semTheme();
        }
        return this._cachedTheme;
    }

    // ── Translation ──
    _t(key) {
        if (!key) return '';
        return (typeof semLocalize === 'function')
            ? semLocalize(key, this._hass?.language)
            : key;
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
        const frozen = this._frozenEntities[entityId];
        if (frozen) return String(frozen.value);
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
                this.requestUpdate();
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
        this.requestUpdate();
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
        this.requestUpdate();
        const svc = state.state === 'on' ? 'turn_off' : 'turn_on';
        this._callService('switch', svc, { entity_id: entityId });
    }

    _selectOption(entityId, option) {
        this._freezeEntity(entityId, option);
        this.requestUpdate();
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

    // ── Debug: flash border on render to visualize update frequency ──
    updated() {
        if (window._semDebug) {
            this.style.outline = '2px solid red';
            this.style.outlineOffset = '-2px';
            clearTimeout(this._debugFlashTimer);
            this._debugFlashTimer = setTimeout(() => {
                this.style.outline = '';
                this.style.outlineOffset = '';
            }, 200);
            const tag = this.tagName.toLowerCase();
            if (!window._semRenderLog) window._semRenderLog = {};
            window._semRenderLog[tag] = (window._semRenderLog[tag] || 0) + 1;
        }
    }

    // ── Lifecycle ──
    connectedCallback() {
        super.connectedCallback();
        if (window._semDebug) {
            console.log(`[SEM DEBUG] ${this.tagName} connectedCallback`);
        }
        // Poll for semLocalize availability
        if (!this._localizeReady) {
            let attempts = 0;
            this._localizeCheckTimer = setInterval(() => {
                attempts++;
                if (typeof semLocalize === 'function' && this._hass) {
                    clearInterval(this._localizeCheckTimer);
                    this._localizeCheckTimer = null;
                    this._localizeReady = true;
                    this.requestUpdate();
                } else if (typeof semLocalize === 'function') {
                    this._localizeReady = true;
                    clearInterval(this._localizeCheckTimer);
                    this._localizeCheckTimer = null;
                } else if (attempts >= 50) {
                    clearInterval(this._localizeCheckTimer);
                    this._localizeCheckTimer = null;
                }
            }, 200);
        }
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        if (window._semDebug) {
            console.log(`[SEM DEBUG] ${this.tagName} disconnectedCallback !!!`);
        }
        if (this._localizeCheckTimer) {
            clearInterval(this._localizeCheckTimer);
            this._localizeCheckTimer = null;
        }
        // Clean up debounce timer
        if (this._updateTimer) {
            clearTimeout(this._updateTimer);
            this._updateTimer = null;
        }
        // Clean up hold timers
        for (const id of Object.keys(this._holdTimers)) this._stopHold(id);
        // Clean up freeze timers
        for (const id of Object.keys(this._frozenEntities)) {
            clearTimeout(this._frozenEntities[id]?.timer);
        }
        this._frozenEntities = {};
    }

    // ── Config ──
    setConfig(config) {
        this._config = config;
    }

    getCardSize() {
        return 4;
    }

    static getStubConfig() {
        return {};
    }
}
