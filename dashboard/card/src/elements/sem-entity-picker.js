/**
 * SEM Entity Picker (#442 Phase 3)
 *
 * Thin Lit wrapper around HA's public ``<ha-entity-picker>`` widget that
 * persists the selected entity directly into the SEM ConfigEntry options
 * via the public ``config_entries/update`` WebSocket API.
 *
 * The wrapper supports two write-modes:
 *   - flat: writes ``{ [key]: value }`` to entry.options
 *   - nested-list: writes ``ev_chargers[index][key] = value`` (preserves
 *     list shape, copies other charger fields verbatim)
 *
 * No coupling to HA internals beyond the two public surfaces (the
 * `<ha-entity-picker>` custom element, which has been stable for years,
 * and the `config_entries/update` WebSocket command, which is the same
 * call HA's own UI uses).
 *
 * Usage from a parent card:
 *   <sem-entity-picker
 *     .hass=${hass}
 *     entry-id=${entryId}
 *     option-key="tariff_entity"
 *     domain="sensor"
 *     include-device-class="monetary">
 *   </sem-entity-picker>
 */

import { LitElement, html, css, nothing } from 'lit';

class SEMEntityPicker extends LitElement {
    static get properties() {
        return {
            hass: { type: Object },
            entryId: { type: String, attribute: 'entry-id' },
            optionKey: { type: String, attribute: 'option-key' },
            // ev_chargers[index].<charger-key>
            chargerIndex: { type: Number, attribute: 'charger-index' },
            chargerKey: { type: String, attribute: 'charger-key' },
            domain: { type: String },
            includeDeviceClass: { type: String, attribute: 'include-device-class' },
            label: { type: String },
            _saving: { state: true },
            _error: { state: true },
        };
    }

    constructor() {
        super();
        this.entryId = '';
        this.optionKey = '';
        this.chargerIndex = -1;
        this.chargerKey = '';
        this.domain = '';
        this.includeDeviceClass = '';
        this.label = '';
        this._saving = false;
        this._error = '';
    }

    static get styles() {
        return css`
            :host { display: block; padding: 6px 0; }
            .picker-row { display: flex; align-items: center; gap: 8px; }
            .picker-label {
                font-size: 14px; font-weight: 500;
                color: var(--primary-text-color);
                min-width: 140px; flex-shrink: 0;
            }
            ha-entity-picker { flex: 1; min-width: 0; }
            .status {
                font-size: 11px; color: var(--secondary-text-color);
                margin-top: 3px;
            }
            .status.error { color: var(--error-color, #d33); }
            .status.ok { color: var(--success-color, #8DC892); }
        `;
    }

    _entry() {
        if (!this.hass || !this.entryId) return null;
        return (this.hass.config_entries || [])
            .find(e => e.entry_id === this.entryId) || null;
    }

    _currentValue() {
        // Look up via the config entry; fall back to '' so the
        // picker renders the "select an entity" placeholder.
        const entry = this._entry();
        if (!entry || !entry.options) return '';
        if (this.chargerKey && this.chargerIndex >= 0) {
            const chargers = entry.options.ev_chargers || [];
            return chargers[this.chargerIndex]?.[this.chargerKey] || '';
        }
        return entry.options[this.optionKey] || '';
    }

    async _onChange(ev) {
        const value = ev.detail?.value || '';
        const entry = this._entry();
        if (!entry) {
            this._error = 'config entry not found';
            return;
        }

        this._saving = true;
        this._error = '';

        // Compute the new options dict (immutable merge).
        let newOptions;
        if (this.chargerKey && this.chargerIndex >= 0) {
            const chargers = (entry.options?.ev_chargers || []).map(c => ({ ...c }));
            if (!chargers[this.chargerIndex]) chargers[this.chargerIndex] = {};
            chargers[this.chargerIndex][this.chargerKey] = value;
            newOptions = { ...entry.options, ev_chargers: chargers };
        } else {
            newOptions = { ...entry.options, [this.optionKey]: value };
        }

        try {
            await this.hass.callWS({
                type: 'config_entries/update',
                entry_id: this.entryId,
                options: newOptions,
            });
            this._saving = false;
            // Trigger a refresh so dependent entities pick up the change.
            // HA reloads the entry automatically on options change for
            // config flows that declare ``async_setup_entry`` returns
            // True for update_listener — SEM does (see __init__.py).
        } catch (err) {
            this._saving = false;
            this._error = err?.message || String(err);
            console.error('[sem-entity-picker] save failed', err);
        }
    }

    render() {
        if (!this.hass) return nothing;
        const cur = this._currentValue();

        // Filter object for ha-entity-picker.
        const includeFilter = {};
        if (this.domain) includeFilter.domain = this.domain;
        if (this.includeDeviceClass) includeFilter.device_class = this.includeDeviceClass;

        return html`
            <div class="picker-row">
                ${this.label ? html`<span class="picker-label">${this.label}</span>` : nothing}
                <ha-entity-picker
                    .hass=${this.hass}
                    .value=${cur}
                    .includeDomains=${this.domain ? [this.domain] : undefined}
                    .includeDeviceClasses=${this.includeDeviceClass ? [this.includeDeviceClass] : undefined}
                    .allowCustomEntity=${false}
                    @value-changed=${this._onChange}>
                </ha-entity-picker>
            </div>
            ${this._error
                ? html`<div class="status error">⚠ ${this._error}</div>`
                : this._saving
                    ? html`<div class="status">saving…</div>`
                    : nothing}
        `;
    }
}

if (!customElements.get('sem-entity-picker')) {
    customElements.define('sem-entity-picker', SEMEntityPicker);
}

export { SEMEntityPicker };
