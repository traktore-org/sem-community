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

import { LitElement, html, css, svg, nothing } from 'lit';
import { semTheme } from './sem-shared.js';

export { html, css, svg, nothing };

/**
 * #617 — the "glass card" chrome, formerly applied from the dashboard
 * template via a card-mod ``*glass_card`` YAML anchor (the last thing
 * that made card-mod a REQUIRED HACS download). Baked into the four
 * consuming cards' own shadow styles instead: identical look, zero
 * external dependency, works wherever the card is used.
 */
export const semGlassCss = css`
    ha-card {
        background-color: var(--card-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
        border-radius: 16px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0, 0, 0, 0.08));
        max-width: 900px;
        font-family: 'Segoe UI', 'Roboto', sans-serif;
        transition: box-shadow 0.3s cubic-bezier(0.4, 0, 0.2, 1),
                    border-color 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        --chip-background: var(--secondary-background-color);
        --primary-font-family: 'Segoe UI', 'Roboto', sans-serif;
    }
    ha-card:hover {
        box-shadow: var(--ha-card-box-shadow, 0 4px 16px rgba(0, 0, 0, 0.12));
    }
`;

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

        // Skip transient unavailable states caused by coordinator refresh —
        // async_request_refresh() briefly marks all entities unavailable before
        // new data arrives (~600ms). Rendering during this window causes visual flashes.
        if (watched.length > 0 && !localeChanged) {
            const firstState = hass.states[watched[0]]?.state;
            if (firstState === 'unavailable' || firstState === 'unknown') return;
        }

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

    // ── Theme (cached per dark/light mode — recomputed on mode switch) ──
    _theme() {
        const isDark = getComputedStyle(document.documentElement)
            .getPropertyValue('--primary-background-color').trim();
        if (!this._cachedTheme || this._cachedThemeKey !== isDark) {
            this._cachedThemeKey = isDark;
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

    // Map a raw forecast source id (sensor.sem_forecast_source) to its
    // brand name. Shared so the Home hero and the Config tab agree —
    // the Config tab used to show the raw 'forecast_solar' / 'FORECAST_SOLAR'
    // while Home showed 'Forecast.Solar' (#514). Falls back to the raw
    // string for any source we haven't mapped yet.
    _forecastProviderLabel(raw) {
        if (!raw) return '';
        const LABELS = {
            solcast: 'Solcast',
            forecast_solar: 'Forecast.Solar',
            open_meteo: 'Open-Meteo',
            custom: this._t('custom') || 'Custom',
        };
        return LABELS[raw] || raw;
    }

    // ── Entity state readers ──
    _state(entityId, fallback = 0) {
        const frozen = this._frozenEntities[entityId];
        if (frozen) return frozen.value;
        const e = this._hass?.states[entityId];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _stateStr(entityId) {
        const frozen = this._frozenEntities[entityId];
        if (frozen) return String(frozen.value);
        const e = this._hass?.states[entityId];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }

    // #727 — the entity's CURRENT display unit. HA converts a sensor to the
    // user's unit system (e.g. a °C-native temperature sensor is served as °F on
    // a US install), so a card that hardcodes the native unit mislabels the value
    // it just read from ``.state``. Read the unit HA actually attached instead.
    _unitOf(entityId) {
        const e = this._hass?.states[entityId];
        return (e && e.attributes && e.attributes.unit_of_measurement) || '';
    }

    // Resolve the primary charger's per-charger entity id for a setting suffix,
    // falling back to the legacy global id (#255 — global EV setting entities were
    // removed; per-charger is canonical). e.g. _pcEntity('number', 'daily_ev_target',
    // 'number.sem_daily_ev_target').
    _pcEntity(domain, suffix, globalFallback) {
        const st = this._hass?.states || {};
        const re = new RegExp(`^${domain}\\.sem_charger_.+_${suffix}$`);
        let match = Object.keys(st).filter(id => re.test(id));
        // `_${suffix}$` over-matches when one key is a tail of a longer one:
        // `night_charging` also matches `smart_night_charging`. Drop the longer key so a
        // request for the plain switch can never resolve to the smart one (only clash).
        if (suffix === 'night_charging') {
            match = match.filter(id => !id.endsWith('_smart_night_charging'));
        }
        match.sort();
        return match.length ? match[0] : globalFallback;
    }

    _stateAttrs(entityId) {
        return this._hass?.states[entityId]?.attributes || {};
    }

    // ── Freeze/thaw for optimistic updates ──
    // Shows the new value instantly while the service call round-trips.
    // With async_write_ha_state() on the backend, HA confirms within ~50ms
    // so the freeze is just a visual bridge — no extend logic needed.
    _freezeEntity(entityId, value) {
        const existing = this._frozenEntities[entityId];
        if (existing?.timer) clearTimeout(existing.timer);
        this._frozenEntities[entityId] = {
            value,
            timer: setTimeout(() => {
                delete this._frozenEntities[entityId];
                this.requestUpdate();
            }, 1500),
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
        // Wait for semLocalize via event (instant) instead of polling
        if (!this._localizeReady && typeof semLocalize !== 'function') {
            this._onLocalizeReady = () => {
                document.removeEventListener('sem-localize-ready', this._onLocalizeReady);
                this._onLocalizeReady = null;
                this._localizeReady = true;
                if (this._hass) this.requestUpdate();
            };
            document.addEventListener('sem-localize-ready', this._onLocalizeReady);
        } else if (typeof semLocalize === 'function') {
            this._localizeReady = true;
        }
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        if (window._semDebug) {
            console.log(`[SEM DEBUG] ${this.tagName} disconnectedCallback !!!`);
        }
        if (this._onLocalizeReady) {
            document.removeEventListener('sem-localize-ready', this._onLocalizeReady);
            this._onLocalizeReady = null;
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
