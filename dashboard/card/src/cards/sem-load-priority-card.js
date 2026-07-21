/**
 * SEM Load Priority Card — LitElement migration
 *
 * Drag-and-drop interface for load management priorities.
 * SortableJS v1.15.6 is inlined (MIT licensed).
 *
 * Key migration notes:
 * - render() produces the card skeleton (status bar, peak box, device list)
 * - firstUpdated() initialises Sortable on the list element
 * - updated() handles incremental DOM updates when device list is unchanged,
 *   or triggers a full re-render when device list changes
 * - disconnectedCallback() destroys the Sortable instance
 * - Drag interactions skip hass updates while in progress (_interacting flag)
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { repeat } from 'lit/directives/repeat.js';
import { moveToIndex, regroupChildren, computeDropIndex } from '../util/drag-reorder.js';
import { semTheme, semDefineCard, semFormatPower } from '../base/sem-shared.js';
import {
    ENTITY_DOMAINS,
    controlToFormValues,
    formValuesToServiceData,
    buildLoadConfigModalHTML,
    readFormValues,
    findDeviceForConfig,
} from './load-config-modal.js';

/* Drag-and-drop is Lit-native (pointer events) — see _dragStart/_dragMove/
   _dragEnd. SortableJS was removed (#576): an imperative DOM library and
   Lit fought over DOM ownership, causing the reorder/badge desync.  */

class SEMLoadPriorityCard extends SEMLitBase {
    constructor() {
        super();
        this.devices = [];
        this.targetPeakLimit = 5.0;
        this.currentPeak = 0;
        this.loadManagementStatus = 'normal';
        this._sortable = null;
        this._interacting = false;
        this._lastDeviceSig = '';
        this._showHelp = false;  // (#559) inline option help
        this._goalOpen = {};      // (#559) device_id -> goal editor expanded
        this._goalDrag = null;    // (#559) live drag state {id, which, value}
    }

    setConfig(config) {
        this._config      = config;
        this.entityPrefix = config.entity_prefix || 'sensor.sem_';
        this.requestUpdate();
    }

    // ── hass: key-based comparison to avoid full re-renders on every state push ──
    set hass(hass) {
        const oldLang = this._hass?.language;
        this._hass = hass;
        const lang = hass?.language;

        if (lang !== this._lang) {
            this._lang = lang;
            this._lastDeviceSig = '';
            this.requestUpdate();
            return;
        }

        if (this._interacting) return;

        // Skip while frozen (optimistic update in progress)
        if (this._isFrozen()) return;

        // Hold a just-dragged priority order until the backend refreshes the
        // sensor (~1 coordinator cycle), so a stale sensor push doesn't snap
        // the reorder back before it lands.
        if (this._priorityFrozenUntil && Date.now() < this._priorityFrozenUntil) return;

        const devState  = hass?.states[`${this.entityPrefix}controllable_devices_count`];
        const peakState = hass?.states[`${this.entityPrefix}consecutive_peak_15min`];
        const lmState   = hass?.states[`${this.entityPrefix}load_management_status`];
        const key = (devState?.state || '') + '|' + (peakState?.state || '') + '|' + (lmState?.state || '');

        if (key === this._lastKey) return;
        this._lastKey = key;

        this._updateDeviceData();
        this.requestUpdate();
    }

    get hass() { return this._hass; }

    disconnectedCallback() {
        super.disconnectedCallback();
        // A drag attaches window-level pointer listeners (_dragStart) that a
        // normal drop removes. If the card is torn down MID-drag (HA tab nav),
        // the drop never fires — remove them here so the card can be GC'd
        // instead of pinned until the next stray pointer event (ruflo LOW).
        if (this._drag) {
            window.removeEventListener('pointermove', this._dragMoveBound);
            window.removeEventListener('pointerup', this._dragEndBound);
            window.removeEventListener('pointercancel', this._dragEndBound);
            this._drag = null;
            this._interacting = false;
        }
    }

    // ── Bind delegated handlers after first render ──
    async firstUpdated() {
        this._bindEvents();
        // Load <ha-entity-picker> early so the stop-condition entity search is
        // ready the moment a goal editor opens (reuses the config-modal loader).
        this._ensureEntityPicker();
    }

    // ── Re-bind the delegated arrow/goal handlers when the list changes ──
    async updated(changedProps) {
        const sig = this.devices.map(d => d.id).join(',');
        if (sig !== this._lastDeviceSig) {
            this._lastDeviceSig = sig;
            this._bindEvents();
        }
    }

    // ── Static CSS ──
    static get styles() {
        return css`
            :host { display: block; }
            ha-card {
                overflow: visible;
                backdrop-filter: blur(18px) saturate(160%);
                -webkit-backdrop-filter: blur(18px) saturate(160%);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.08));
                border-radius: 16px !important;
                box-shadow: var(--ha-card-box-shadow, 0 4px 24px rgba(0,0,0,0.35));
            }
            .card-content { padding: 14px 16px; font-family: 'Segoe UI','Roboto',sans-serif; color: var(--primary-text-color); }
            .status-bar { display:flex; align-items:center; gap:8px; margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid var(--divider-color, rgba(128,128,128,0.12)); font-size:0.95em; }
            .status-text { text-transform:uppercase; letter-spacing:0.5px; font-weight:600; opacity:0.85; }
            .peak-dot { width:9px; height:9px; border-radius:50%; }
            .peak-box { background:var(--secondary-background-color, rgba(255,255,255,0.04)); border:1px solid var(--divider-color, rgba(255,255,255,0.08)); border-radius:12px; padding:12px; margin-bottom:10px; backdrop-filter: blur(8px); }
            .peak-row { display:flex; justify-content:space-between; margin-bottom:4px; font-size:1em; }
            .peak-row:last-of-type { margin-bottom:0; }
            .dim { opacity:0.55; font-size:1em; }
            .mono { font-variant-numeric:tabular-nums; font-weight:500; }
            .bar { width:100%; height:5px; background:var(--divider-color, rgba(128,128,128,0.12)); border-radius:3px; overflow:hidden; margin-top:8px; }
            .bar-fill { height:100%; border-radius:3px; transition:width 0.4s ease, background 0.4s ease; }
            .target-row { display:flex; align-items:center; gap:8px; margin-top:6px; }
            .target-row input { width:70px; padding:5px 8px; border:1px solid var(--divider-color, rgba(255,255,255,0.08)); border-radius:8px; background:var(--card-background-color, rgba(0,0,0,0.2)); color:var(--primary-text-color); text-align:center; font-size:1em; }
            .target-row input:focus { outline:none; border-color:#ff9800; }
            .target-row button { padding:5px 14px; border:none; border-radius:8px; background:#ff9800; color:#fff; cursor:pointer; font-size:0.95em; }
            .target-row button:hover { background:#e68900; }
            .section-label { font-size:0.95em; opacity:0.55; margin-bottom:10px; display:flex; align-items:center; gap:6px; }
            .device-list { min-height:40px; }
            .device { display:flex; align-items:stretch; background:var(--secondary-background-color, rgba(255,255,255,0.04)); border:1px solid var(--divider-color, rgba(255,255,255,0.08)); border-radius:12px; margin-bottom:6px; transition:transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease; overflow:hidden; backdrop-filter:blur(8px); }
            /* Pointer-drag (Lit-native): the lifted row follows the finger,
               a bright line shows where it will drop. box-shadow is not
               clipped by the row's overflow, so the drop-line always shows. */
            .device.dragging-row { opacity:0.95; z-index:20; position:relative; border-color:#ff9800; box-shadow:0 10px 26px rgba(0,0,0,0.45); cursor:grabbing; }
            .device.drop-above { box-shadow:0 -3px 0 0 #ff9800; }
            .device.drop-below { box-shadow:0 3px 0 0 #ff9800; }
            .drag-handle { display:flex; align-items:center; justify-content:center; width:32px; min-width:32px; cursor:grab; font-size:16px; opacity:0.3; user-select:none; touch-action:none; border-right:1px solid var(--divider-color, rgba(128,128,128,0.12)); }
            .drag-handle:hover { opacity:0.6; }
            .drag-handle:active { cursor:grabbing; }
            .device-body { flex:1; padding:10px 12px; min-width:0; }
            .device-top { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
            .device-name { display:flex; align-items:center; gap:6px; font-weight:500; font-size:0.95em; min-width:0; overflow:hidden; }
            .device-name span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
            .device-power { font-size:1em; font-weight:500; font-variant-numeric:tabular-nums; white-space:nowrap; opacity:0.7; }
            .device-bottom { display:flex; align-items:center; gap:8px; font-size:0.95em; flex-wrap:wrap; }
            .status-dot { width:7px; height:7px; border-radius:50%; background:var(--divider-color, rgba(128,128,128,0.12)); flex-shrink:0; }
            .status-dot.on { background:#4caf50; box-shadow:0 0 6px #4caf50; }
            .status-dot.shed { background:#f44336; box-shadow:0 0 6px #f44336; }
            .spacer { flex:1; }
            .badge { padding:2px 7px; border-radius:8px; font-size:0.95em; font-weight:600; }
            .badge.priority { background:#ff9800; color:#fff; min-width:14px; text-align:center; }
            .toggle-label { display:flex; align-items:center; gap:4px; }
            .arrows { display:flex; flex-direction:column; gap:1px; }
            .arrow-btn { border:none; background:none; cursor:pointer; font-size:11px; padding:0 4px; opacity:0.35; line-height:1; color:var(--primary-text-color,inherit); }
            .arrow-btn:hover { opacity:0.8; }
            .mode-select { background:var(--card-background-color,rgba(40,40,55,0.7)); color:var(--primary-text-color); border:1px solid var(--divider-color,rgba(255,255,255,0.08)); border-radius:6px; padding:2px 6px; font-size:13px; font-family:'Segoe UI','Roboto',sans-serif; cursor:pointer; -webkit-appearance:none; appearance:none; }
            .mode-select:focus { outline:none; border-color:rgba(255,152,0,0.5); }
            .configure-btn { display:inline-flex; align-items:center; gap:3px; padding:2px 6px; background:rgba(255,193,7,0.12); border:1px solid rgba(255,193,7,0.25); border-radius:5px; color:#ffc107; cursor:pointer; font-size:0.9em; }
            .configure-btn:hover { background:rgba(255,193,7,0.22); }
            .hint { text-align:center; font-size:0.95em; opacity:0.4; margin-top:10px; }
            .help-btn {
                width:24px; height:24px; border-radius:50%;
                border:1px solid var(--divider-color, rgba(255,255,255,0.2));
                background:transparent; color:var(--secondary-text-color,#999);
                font-weight:700; cursor:pointer; margin-left:8px; flex:0 0 auto;
            }
            .help-btn.active { color:#ff9800; border-color:#ff9800; }
            .help-panel {
                margin:4px 0 14px; padding:12px 14px; border-radius:10px;
                background:rgba(128,128,128,0.08);
                font-size:0.9em; line-height:1.5;
            }
            .help-item { margin-bottom:8px; }
            .help-item:last-child { margin-bottom:0; }
            .help-item b { color:var(--primary-text-color,#e0e0e0); }
            .goal-btn {
                width:26px; height:26px; border-radius:8px;
                border:1px solid var(--divider-color, rgba(255,255,255,0.15));
                background:transparent; color:var(--secondary-text-color,#999);
                cursor:pointer; display:flex; align-items:center; justify-content:center;
                margin-left:6px; flex:0 0 auto;
            }
            .goal-btn.active { color:#ff9800; border-color:#ff9800; }
            .goal-progress { display:flex; align-items:center; gap:8px; }
            .goal-bar {
                flex:1 1 auto; height:5px; border-radius:3px;
                background:rgba(128,128,128,0.2); overflow:hidden; max-width:220px;
            }
            .goal-bar-fill { height:100%; border-radius:3px; transition:width 0.4s; }
            .goal-progress-text { font-size:12px; color:var(--secondary-text-color,#999); white-space:nowrap; }
            .ge-spacer { margin-left:auto; }
            .ge-unit-select {
                appearance:none; -webkit-appearance:none;
                background-color:var(--secondary-background-color, rgba(255,255,255,0.07));
                background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat:no-repeat; background-position:right 4px center;
                background-size:12px;
                color:var(--primary-text-color,#e0e0e0);
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:6px; padding:2px 20px 2px 8px;
                font-size:11px; font-weight:600; cursor:pointer;
                text-transform:none; letter-spacing:0;
            }
            .range-wrap { padding:6px 8px 10px; }
            .range-labels {
                display:flex; justify-content:space-between;
                font-size:12px; color:var(--primary-text-color,#e0e0e0);
                margin-bottom:10px;
            }
            .range-labels b { font-variant-numeric:tabular-nums; }
            .range-track {
                position:relative; height:6px; border-radius:3px;
                background:rgba(255,255,255,0.14); margin:6px 9px;
                touch-action:none; cursor:pointer;
            }
            .range-fill {
                position:absolute; top:0; height:100%; border-radius:3px;
                background:linear-gradient(90deg, #8DC892, #ff9800);
                pointer-events:none;  /* never swallow the handle grab */
            }
            .range-handle {
                position:absolute; top:50%; width:18px; height:18px;
                border-radius:50%; transform:translate(-50%, -50%);
                background:#fff; box-shadow:0 1px 3px rgba(0,0,0,0.5);
                cursor:grab; touch-action:none; pointer-events:auto;
                z-index:2;  /* sit above the fill so pointerdown lands */
            }
            .range-handle:active { cursor:grabbing; }
            .range-handle-min { border:3px solid #8DC892; }
            .range-handle-max { border:3px solid #ff9800; }
            /* EV charge-target look (#559 UI merge) */
            .goal-editor {
                margin:8px 0 4px 28px; padding:10px 12px;
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:10px; background:rgba(255,255,255,0.025);
            }
            .ge-title {
                font-size:11px; text-transform:uppercase; letter-spacing:0.05em;
                color:var(--secondary-text-color,#999);
                display:flex; align-items:center; gap:5px; margin-bottom:4px;
            }
            .ge-row {
                display:flex; align-items:center; min-height:34px; padding:2px 0;
            }
            .ge-row + .ge-row { border-top:1px solid rgba(255,255,255,0.06); }
            .ge-label { font-size:12px; color:var(--primary-text-color,#e0e0e0); }
            .ge-ctl { margin-left:auto; display:flex; align-items:center; gap:7px; }
            .ge-unit { font-size:12px; color:var(--secondary-text-color,#999); }
            .ge-mode-select {
                appearance:none; -webkit-appearance:none;
                background-color:var(--secondary-background-color, rgba(255,255,255,0.07));
                background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat:no-repeat; background-position:right 6px center;
                background-size:14px;
                color:var(--primary-text-color,#e0e0e0);
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:8px; padding:4px 24px 4px 10px;
                font-size:12px; font-weight:600; cursor:pointer;
            }
            .goal-editor input[type=number], .goal-editor input[type=time], .goal-editor input[type=text] {
                background:var(--secondary-background-color, rgba(255,255,255,0.07));
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:8px; color:var(--primary-text-color,#e0e0e0);
                padding:4px 8px; width:72px; font-size:12px;
                font-variant-numeric:tabular-nums;
            }
            .goal-editor input.ge-entity { width:160px; max-width:100%; }
            /* Mobile: the stop-when row (entity + ≥ + number) overflows a
               phone width and squeezes the label onto two lines. Stack the
               label above the control and let the entity field flex. */
            @media (max-width: 480px) {
                .goal-editor { margin-left:6px; padding:10px; }
                .ge-row { flex-wrap:wrap; align-items:flex-start; }
                .ge-label { flex:1 0 100%; margin-bottom:4px; }
                .ge-ctl { margin-left:0; width:100%; }
                .goal-editor input.ge-entity { flex:1; width:auto; }
            }
            .ge-hint {
                display:flex; align-items:center; gap:6px;
                font-size:12px; color:var(--secondary-text-color,#999); padding:4px 0 6px;
            }
            /* (#620) battery-overnight toggle switch */
            .batt-toggle {
                width:34px; height:19px; border-radius:11px; border:none; padding:0;
                position:relative; cursor:pointer; background:rgba(255,255,255,0.15);
                transition:background .2s;
            }
            .batt-toggle.on { background:#4db6ac; }
            .batt-toggle .knob {
                position:absolute; top:2px; left:2px; width:15px; height:15px;
                border-radius:50%; background:#fff; transition:left .2s;
            }
            .batt-toggle.on .knob { left:17px; }
            .empty { text-align:center; padding:20px 0; opacity:0.4; font-size:1em; }
        `;
    }

    // ── Device data extraction ──
    _updateDeviceData() {
        if (!this._hass) return;
        const targetPeakEntity  = this._hass.states[`${this.entityPrefix}target_peak_limit`];
        const currentPeakEntity = this._hass.states[`${this.entityPrefix}consecutive_peak_15min`];
        const statusEntity      = this._hass.states[`${this.entityPrefix}load_management_status`];
        const devicesEntity     = this._hass.states[`${this.entityPrefix}controllable_devices_count`];

        if (targetPeakEntity)  this.targetPeakLimit      = parseFloat(targetPeakEntity.state)  || 5.0;
        if (currentPeakEntity) this.currentPeak          = parseFloat(currentPeakEntity.state) || 0;
        if (statusEntity)      this.loadManagementStatus = statusEntity.state || 'normal';

        if (devicesEntity?.attributes?.devices) {
            this.devices = Object.entries(devicesEntity.attributes.devices)
                .map(([id, info]) => ({
                    id,
                    name: info.name || id.replace(/^(load_device_|energy_dashboard_)/, '').replace(/_/g, ' '),
                    power: (info.current_power || 0) / 1000,
                    // (#577) self-calibrated rated power (W) — shown dimmed when
                    // the load is off so the row keeps a meaningful number
                    // instead of a bare "OFF".
                    rating: info.power_rating || 0,
                    priority: info.priority || 5,
                    isOn: info.is_on || false,
                    isShed: info.is_shed || false,
                    shedReason: info.shed_reason || null,
                    isControllable: info.is_controllable !== false,
                    isCritical: info.is_critical || false,
                    deviceType: info.device_type || 'unknown',
                    isAvailable: info.is_available || false,
                    hasManualMapping: info.has_manual_mapping || false,
                    energySensor: info.energy_sensor || '',
                    control: info.control || null,
                    controlEntity: info.control?.entity || info.switch_entity || '',
                    controlType: info.control?.type || 'switch',
                    controlMode: info.control_mode || 'peak_only',
                    dependsOn: info.depends_on || [],
                    goals: info.goals || null,
                    progress: info.progress || null,
                    blockedBy: info.blocked_by || null,
                    soc: info.soc,   // (#576) battery row only
                    icon: this._resolveDeviceIcon(info),
                }))
                .sort((a, b) => a.priority - b.priority);
        }
    }

    // ── Render ──
    render() {
        if (!this._config) return nothing;

        const peakColor  = this._getPeakColor();
        const peakMargin = this.targetPeakLimit - this.currentPeak;
        const peakPct    = this.targetPeakLimit > 0 ? Math.min((this.currentPeak / this.targetPeakLimit) * 100, 100) : 0;

        return html`
            <ha-card>
                <div class="card-content">
                    <div class="status-bar">
                        <div class="peak-dot" style="background:${peakColor};box-shadow:0 0 8px ${peakColor}"></div>
                        <span id="lm-status" class="status-text">${this._t(this.loadManagementStatus || 'normal').toUpperCase()}</span>
                        <div class="spacer"></div>
                        <span class="dim">${this._t('peak')}</span>
                        <span id="peak-current" class="mono">${this.currentPeak.toFixed(2)} kW</span>
                        <span class="dim">/ ${this.targetPeakLimit.toFixed(1)}</span>
                        <button class="help-btn ${this._showHelp ? 'active' : ''}" data-action="toggle-help"
                                title="${this._t('help')}">?</button>
                    </div>

                    <div class="peak-box">
                        <div class="peak-row">
                            <span class="dim">${this._t('current_peak')}</span>
                            <span id="peak-current2" class="mono">${this.currentPeak.toFixed(2)} kW</span>
                        </div>
                        <div class="peak-row">
                            <span class="dim">${this._t('target_limit')}</span>
                            <span id="peak-target" class="mono">${this.targetPeakLimit.toFixed(2)} kW</span>
                        </div>
                        <div class="peak-row">
                            <span class="dim">${this._t('margin')}</span>
                            <span id="peak-margin" class="mono" style="color:${peakMargin > 0 ? '#4caf50' : '#f44336'}">${peakMargin.toFixed(2)} kW</span>
                        </div>
                        <div class="bar">
                            <div id="peak-bar" class="bar-fill" style="width:${peakPct}%;background:${peakColor}"></div>
                        </div>
                    </div>

                    <div class="peak-box" style="margin-bottom:16px">
                        <span class="dim">${this._t('adjust_target_peak')}</span>
                        <div class="target-row">
                            <input type="number" id="targetInput" min="1" max="20" step="0.1" .value="${String(this.targetPeakLimit)}">
                            <span class="dim">kW</span>
                            <button id="setTargetBtn">${this._t('set')}</button>
                        </div>
                    </div>

                    ${this._showHelp ? html`
                    <div class="help-panel">
                        <div class="help-item"><b>${this._t('off')}</b> — ${this._t('help_mode_off')}</div>
                        <div class="help-item"><b>${this._t('peak_only')}</b> — ${this._t('help_mode_peak_only')}</div>
                        <div class="help-item"><b>${this._t('mode_solar_only')}</b> — ${this._t('help_mode_surplus')}</div>
                        <div class="help-item"><b>${this._t('mode_solar_battery')}</b> — ${this._t('battery_overnight_hint')}</div>
                        <div class="help-item"><b>${this._t('priority')}</b> — ${this._t('help_device_priority')}</div>
                        <div class="help-item"><b>${this._t('requires')}</b> — ${this._t('help_device_requires')}</div>
                        <div class="help-item"><b>${this._t('configure')}</b> — ${this._t('help_device_configure')}</div>
                        <div class="help-item"><b>${this._t('target_limit')}</b> — ${this._t('help_device_peak')}</div>
                        <div class="help-item"><b>${this._t('daily_target')}</b> — ${this._t('help_device_target')}</div>
                    </div>` : nothing}

                    <div class="section-label">
                        <ha-icon icon="mdi:drag-vertical" style="--mdc-icon-size:18px"></ha-icon>
                        ${this._t('drag_to_reorder')}
                    </div>

                    <div id="device-list" class="device-list">
                        ${this.devices.length === 0
                            ? html`<div class="empty">${this._t('no_devices_yet')}</div>`
                            : repeat(
                                this.devices,
                                (d) => d.id,   // KEY by stable id so Lit tracks
                                // each row by identity, not position — else it
                                // desyncs with SortableJS's DOM moves (the
                                // "device in the wrong spot" bug).
                                (d, i) => this._renderDevice(d, i + 1),
                              )}
                    </div>

                    ${this.devices.length > 0
                        ? html`<div class="hint">${this._t('drag_hint')}</div>`
                        : nothing}

                    <div class="hint" style="margin-top:12px;padding:10px;background:rgba(128,128,128,0.06);border-radius:10px">
                        ${this._t('devices_auto_discovered').replace(/<br\s*\/?>/g, ' — ')}
                    </div>
                </div>
            </ha-card>
        `;
    }

    _renderDevice(device, priority) {
        // Power-aware ON detection: if the switch reports OFF but the device draws > 10W, it's clearly on
        const onOff  = device.isOn || device.power > 0.01;
        // (#576) the home battery is a positioned sink — draggable, but no
        // on/off, no mode, no dependencies, no goals. Its position (and SOC)
        // are the whole story.
        const isBattery = device.deviceType === 'battery';
        const isChild = device.dependsOn.length > 0;
        const depth  = this._getDependencyDepth(device);
        const indentStyle = depth > 0
            ? `margin-left:${depth * 24}px;border-left:2px solid rgba(255,152,0,${0.3 + depth * 0.1});`
            : '';

        return html`
        <div class="device${isChild ? ' is-child' : ''}" data-id="${device.id}" style="${indentStyle}">
            <div class="drag-handle"
                 title="${isChild ? this._t('locked_under_parent') : this._t('drag_to_reorder')}"
                 @pointerdown=${isChild ? null : (e) => this._dragStart(e, device.id)}
                 style="${isChild ? 'opacity:0.3;cursor:default' : ''}">${isChild ? '\u00B7' : '\u2261'}</div>
            <div class="device-body">
                <div class="device-top">
                    <div class="device-name">
                        ${isChild ? html`<span style="color:#ff9800;font-size:12px;margin-right:4px">&#8618;</span>` : nothing}
                        <ha-icon icon="${device.icon}" style="--mdc-icon-size:20px;color:${onOff ? '#ff9800' : '#666'}"></ha-icon>
                        <span>${device.name}</span>
                        ${isBattery ? nothing : html`
                        <span class="configure-btn" data-action="configure" data-device="${device.id}" data-name="${device.name}">
                            <ha-icon icon="mdi:${device.hasManualMapping ? 'wrench' : 'cog'}" style="--mdc-icon-size:14px"></ha-icon> ${device.isControllable ? this._t('configure_device') : this._t('configure')}
                        </span>`}
                    </div>
                    <div class="device-power" data-field="power-${device.id}">
                        ${isBattery
                            ? html`<span style="opacity:0.7">${device.soc != null ? device.soc + '% · ' : ''}${onOff ? semFormatPower(device.power * 1000) : this._t('off')}</span>`
                            : (onOff
                                ? semFormatPower(device.power * 1000)
                                : (device.isShed
                                    ? this._t('shed_label')
                                    : (device.rating > 0
                                        ? html`<span style="opacity:0.5" title="${this._t('rated_power_hint')}">~${semFormatPower(device.rating)}</span>`
                                        : this._t('off'))))}
                    </div>
                </div>
                ${device.blockedBy ? html`<div style="font-size:13px;color:#ff9800;padding:2px 0 0 28px">&#9203; Waiting for: ${device.blockedBy}</div>` : nothing}
                ${device.dependsOn.length ? html`<div style="font-size:13px;opacity:0.55;padding:0 0 0 28px">&#8618; ${this._t('requires')}: ${device.dependsOn.join(', ')}</div>` : nothing}
                ${device.isShed && device.shedReason ? html`<div style="font-size:13px;color:#f44336;padding:2px 0 0 28px">${device.shedReason === 'emergency' ? this._t('shed_emergency') : this._t('shed_peak')}</div>` : nothing}
                <div class="device-bottom">
                    <div class="status-dot ${onOff ? 'on' : (device.isShed ? 'shed' : '')}" data-field="status-${device.id}"></div>
                    <span class="dim" data-field="onoff-${device.id}">${onOff ? this._t('on') : (device.isShed ? this._t('shed_label') : this._t('off'))}</span>
                    <span class="badge priority" data-field="pri-${device.id}">${priority}</span>
                    <div class="spacer"></div>
                    ${isBattery ? html`<span class="dim" title="${this._t('battery_role_help')}">${this._t('battery_role_label')}</span>` : nothing}
                    ${device.deviceType === 'ev_charger' || device.deviceType === 'ev_charging' || isBattery ? nothing : html`
                    <label class="toggle-label" title="${this._t('mode_tooltip')}">
                        <span class="dim">${this._t('mode')}</span>
                        <select class="mode-select" data-action="combined_mode" data-device="${device.id}">
                            <option value="off" ?selected="${this._mergedMode(device) === 'off'}">${this._t('off')}</option>
                            <option value="peak_only" ?selected="${this._mergedMode(device) === 'peak_only'}">${this._t('peak_only')}</option>
                            <option value="solar_only" ?selected="${this._mergedMode(device) === 'solar_only'}">${this._t('mode_solar_only')}</option>
                            <option value="solar_battery" ?selected="${this._mergedMode(device) === 'solar_battery'}">${this._t('mode_solar_battery')}</option>
                        </select>
                    </label>`}
                    ${isBattery ? nothing : html`
                    <label class="toggle-label" title="${this._t('requires_tooltip')}">
                        <span class="dim">${this._t('requires')}</span>
                        <select class="mode-select" data-action="depends_on" data-device="${device.id}">
                            <option value="" ?selected="${!device.dependsOn.length}">${this._t('action_none')}</option>
                            ${this.devices.filter(d => d.id !== device.id).map(d =>
                                html`<option value="${d.id}" ?selected="${device.dependsOn.includes(d.id)}">${d.name}</option>`
                            )}
                        </select>
                    </label>`}
                    <div class="arrows">
                        <button class="arrow-btn" data-action="move-up"   data-device="${device.id}" title="${this._t('move_up')}">&#9650;</button>
                        <button class="arrow-btn" data-action="move-down" data-device="${device.id}" title="${this._t('move_down')}">&#9660;</button>
                    </div>
                    ${(device.deviceType === 'ev_charger' || device.deviceType === 'ev_charging' || isBattery
                       || (this._mergedMode(device) !== 'solar_only'
                           && this._mergedMode(device) !== 'solar_battery')) ? nothing : html`
                    <button class="goal-btn ${this._goalOpen[device.id] ? 'active' : ''}"
                            data-action="toggle-goal" data-device="${device.id}"
                            title="${this._t('daily_target')}">
                        <ha-icon icon="mdi:target" style="--mdc-icon-size:16px;pointer-events:none"></ha-icon>
                    </button>`}
                </div>
                ${this._renderGoalProgress(device)}
                ${this._goalOpen[device.id] ? this._renderGoalEditor(device) : nothing}
            </div>
        </div>`;
    }

    // ── (#559) goal engine UI — EV-charger look (one merged mode picker) ──

    _mergedMode(device) {
        // (#620) four modes — off / peak_only / solar_only / solar_battery.
        // control_mode=surplus splits on battery_assist_enabled: with it on the
        // battery assists above the buffer (solar_battery); off = solar_only
        // (battery reserved for the house). off/peak_only unchanged.
        const cm = device.controlMode || 'peak_only';
        if (cm !== 'surplus') return cm;
        return (device.goals || {}).battery_assist_enabled ? 'solar_battery' : 'solar_only';
    }

    _mergedModeLabel(device) {
        const m = this._mergedMode(device);
        const key = { off: 'off', peak_only: 'peak_only',
                      solar_only: 'mode_solar_only',
                      solar_battery: 'mode_solar_battery' }[m] || m;
        return this._t(key);
    }

    _applyMergedMode(device, merged) {
        // Both solar modes are control_mode=surplus; battery_assist_enabled is
        // the discriminator (Tier-1 daytime assist, #620).
        const controlMode = (merged === 'off' || merged === 'peak_only') ? merged : 'surplus';
        device.controlMode = controlMode;
        this._sendDeviceUpdate(device.id, 'control_mode', controlMode);
        if (controlMode === 'surplus') {
            const assist = merged === 'solar_battery';
            device.goals = device.goals || {};
            device.goals.battery_assist_enabled = assist;
            this._sendDeviceUpdate(device.id, 'battery_assist_enabled', String(assist));
            // migrate a legacy 'always' policy off the removed value
            if (device.goals.top_up_policy === 'always') {
                device.goals.top_up_policy = 'solar_only';
                this._sendDeviceUpdate(device.id, 'top_up_policy', 'solar_only');
            }
        }
        this.requestUpdate();
    }

    _hasTarget(device) {
        return parseFloat((device.goals || {}).daily_min_runtime_min) > 0;
    }

    _goalPct(device) {
        const g = device.goals, p = device.progress;
        if (!g || !p) return null;
        const target = parseFloat(g.daily_min_runtime_min);
        if (!(target > 0)) return null;
        return Math.min(100, (p.runtime_today_min / target) * 100);
    }

    // Dual-handle Min/Max runtime slider in hours (#620) — mirrors the EV
    // charge-target range. Green handle = Minimum (floor, daily_min_runtime_min),
    // orange handle = Maximum (cap, daily_max_runtime_min; full scale = uncapped).
    _renderGoalSlider(device) {
        const SCALE_H = 12;
        const g = device.goals || {};
        const drag = this._goalDrag;
        let minH = (parseFloat(g.daily_min_runtime_min) || 0) / 60;
        let maxRaw = parseFloat(g.daily_max_runtime_min) || 0;
        let maxH = maxRaw > 0 ? maxRaw / 60 : SCALE_H;  // 0 = uncapped = full scale
        if (drag && drag.id === device.id) {
            if (drag.handle === 'min') minH = drag.value;
            else maxH = drag.value;
        }
        if (maxH < minH) maxH = minH;
        const minPct = Math.min(100, (minH / SCALE_H) * 100);
        const maxPct = Math.min(100, (maxH / SCALE_H) * 100);
        const atFull = maxH >= SCALE_H - 1e-6;
        const fmt = (h) => (h % 1 === 0 ? String(h) : h.toFixed(1));
        return html`
            <div class="range-wrap">
                <div class="range-labels">
                    <span>${this._t('at_least')} <b style="color:#8DC892">${minH <= 0 ? this._t('no_target') : fmt(minH) + ' h'}</b></span>
                    <span>${this._t('up_to')} <b style="color:#ff9800">${atFull ? this._t('uncapped') : fmt(maxH) + ' h'}</b></span>
                </div>
                <div class="range-track">
                    <div class="range-fill" style="left:${minPct}%;width:${Math.max(0, maxPct - minPct)}%;background:linear-gradient(90deg,#8DC892,#ff9800)"></div>
                    <div class="range-handle range-handle-min" style="left:${minPct}%"
                         @pointerdown=${(e) => this._goalSliderStart(e, device, 'min')}></div>
                    <div class="range-handle range-handle-max" style="left:${maxPct}%"
                         @pointerdown=${(e) => this._goalSliderStart(e, device, 'max')}></div>
                </div>
            </div>`;
    }

    _goalSliderStart(e, device, handle) {
        e.stopPropagation();
        e.preventDefault();
        const SCALE_H = 12, STEP_H = 0.5;
        const track = e.currentTarget.parentElement;  // handle → .range-track
        const g = device.goals = device.goals || {};
        const rect = track.getBoundingClientRect();
        const curMinH = (parseFloat(g.daily_min_runtime_min) || 0) / 60;
        const rawMax = parseFloat(g.daily_max_runtime_min) || 0;
        const curMaxH = rawMax > 0 ? rawMax / 60 : SCALE_H;
        const toVal = (clientX) => {
            let frac = (clientX - rect.left) / (rect.width || 1);
            frac = Math.max(0, Math.min(1, frac));
            let v = Math.round((frac * SCALE_H) / STEP_H) * STEP_H;
            // Clamp so the handles can't cross.
            if (handle === 'min') v = Math.min(v, curMaxH);
            else v = Math.max(v, curMinH);
            return v;
        };
        const apply = (clientX) => {
            this._goalDrag = { id: device.id, handle, value: toVal(clientX) };
            this.requestUpdate();
        };
        apply(e.clientX);
        const onMove = (ev) => apply(ev.clientX);
        const onUp = (ev) => {
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
            window.removeEventListener('pointercancel', onUp);
            const hours = toVal(ev.clientX);
            this._goalDrag = null;
            if (handle === 'min') {
                const minutes = Math.round(hours * 60);
                g.daily_min_runtime_min = minutes;
                this._sendDeviceUpdate(device.id, 'daily_min_runtime_min', String(minutes));
            } else {
                // Full scale = uncapped (store 0); otherwise the cap in minutes.
                const minutes = hours >= SCALE_H - 1e-6 ? 0 : Math.round(hours * 60);
                g.daily_max_runtime_min = minutes;
                this._sendDeviceUpdate(device.id, 'daily_max_runtime_min', String(minutes));
            }
            this.requestUpdate();
        };
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
        window.addEventListener('pointercancel', onUp);
    }

    _onStopEntity(device, e) {
        // <ha-entity-picker> fires value-changed (not change) with the chosen
        // entity in e.detail.value. Persist via the same goal path as the text
        // input — the backend _goal_write_lock makes the entity + threshold
        // writes atomic even though they arrive as two calls.
        e.stopPropagation();
        const v = (e.detail && e.detail.value) || '';
        device.goals = device.goals || {};
        device.goals.stop_entity = v;
        this._sendDeviceUpdate(device.id, 'stop_entity', v);
    }

    _toggleBatteryOvernight(device) {
        const g = device.goals = device.goals || {};
        const next = !g.battery_eligible_overnight;
        g.battery_eligible_overnight = next;
        this._sendDeviceUpdate(device.id, 'battery_eligible_overnight', String(next));
        this.requestUpdate();
    }

    _renderGoalProgress(device) {
        // Only meaningful in the two solar modes (#620) — in Off / Peak-only
        // the daily solar budget doesn't apply, so hide the row rather than
        // show a stale/counting timer (#559 alex "Issue 6").
        const _m = this._mergedMode(device);
        if (_m !== 'solar_only' && _m !== 'solar_battery') return nothing;
        const pct = this._goalPct(device);
        if (pct === null) return nothing;
        const g = device.goals, p = device.progress;
        const done = p.targets_met || pct >= 100;
        const h = (min) => { const v = min / 60; return v % 1 === 0 ? String(v) : v.toFixed(1); };
        const txt = h(p.runtime_today_min) + '/' + h(parseFloat(g.daily_min_runtime_min))
            + ' ' + this._t('hours_on_solar_today');
        return html`
            <div class="goal-progress" style="padding:2px 0 0 28px">
                <div class="goal-bar"><div class="goal-bar-fill" style="width:${pct}%;background:#8DC892"></div></div>
                <span class="goal-progress-text">${txt}${done ? ' ✓' : ''}</span>
            </div>`;
    }

    _renderGoalEditor(device) {
        // Mode-gated disclosure — shown in the two solar modes (#620).
        const mode = this._mergedMode(device);
        if (mode !== 'solar_only' && mode !== 'solar_battery') return nothing;
        const g = device.goals || {};
        const overnight = !!g.battery_eligible_overnight;
        return html`
            <div class="goal-editor">
                <div class="ge-title">
                    <ha-icon icon="mdi:target" style="--mdc-icon-size:14px;color:#8DC892"></ha-icon>
                    ${this._t('daily_target')}
                </div>
                ${this._renderGoalSlider(device)}
                ${mode === 'solar_battery' ? html`
                <div class="ge-row">
                    <span class="ge-label">${this._t('battery_overnight_label')}</span>
                    <span class="ge-ctl">
                        <button class="batt-toggle ${overnight ? 'on' : ''}"
                                data-action="toggle-battery-overnight" data-device="${device.id}"
                                title="${this._t('battery_overnight_help')}">
                            <span class="knob"></span>
                        </button>
                    </span>
                </div>
                <div class="ge-hint">${this._t('battery_overnight_hint')}</div>
                ` : html`<div class="ge-hint">${this._t('solar_only_hint')}</div>`}
                <div class="ge-row">
                    <span class="ge-label">${this._t('stop_condition')}</span>
                    <span class="ge-ctl">
                        ${this.hass && customElements.get('ha-entity-picker') ? html`
                        <ha-entity-picker class="ge-entity"
                               .hass=${this.hass}
                               .value=${g.stop_entity || ''}
                               .includeDomains=${['sensor', 'number', 'input_number']}
                               .placeholder=${this._t('stop_entity_placeholder')}
                               allow-custom-entity hide-clear-icon
                               @value-changed=${(e) => this._onStopEntity(device, e)}
                               @click=${(e) => e.stopPropagation()}></ha-entity-picker>
                        ` : html`
                        <input type="text" class="ge-entity" placeholder="${this._t('stop_entity_placeholder')}"
                               .value="${g.stop_entity || ''}"
                               data-goal="stop_entity" data-device="${device.id}">`}
                        <span class="ge-unit">≥</span>
                        <input type="number" min="0" step="1" style="width:56px"
                               .value="${String(g.stop_at || 0)}"
                               data-goal="stop_at" data-device="${device.id}">
                    </span>
                </div>
                <div class="ge-hint">${this._t('stop_condition_hint')}</div>
            </div>`;
    }

    // ── Lit-native pointer-drag reorder (no SortableJS) ──
    // Only DATA (this.devices) is reordered, and only on DROP — then Lit
    // re-renders. One DOM owner, so the row can never desync from its badge.
    // During the gesture only transient visuals are applied (a lifted row +
    // a drop-line) and Lit is paused (_interacting), so nothing fights it.
    _dragStart(e, deviceId) {
        const dev = this.devices.find(d => d.id === deviceId);
        if (!dev || (dev.dependsOn && dev.dependsOn.length)) return;  // children locked
        if (e.button != null && e.button !== 0) return;
        e.preventDefault();
        const handle = e.currentTarget;
        const row = handle.closest('.device');
        const list = this.renderRoot.getElementById('device-list');
        if (!row || !list) return;
        const rows = Array.from(list.querySelectorAll('.device'));
        // Snapshot original row centres — only the dragged row moves, so these
        // stay valid for a stable drop-target computation.
        const centres = rows.map(r => { const b = r.getBoundingClientRect(); return b.top + b.height / 2; });
        this._interacting = true;
        const fromIndex = rows.indexOf(row);
        this._drag = { id: deviceId, handle, row, rows, centres, pointerY0: e.clientY,
                       fromIndex, dropIndex: fromIndex, pointerId: e.pointerId };
        row.classList.add('dragging-row');
        try { handle.setPointerCapture(e.pointerId); } catch (_) {}
        this._dragMoveBound = this._dragMoveBound || this._dragMove.bind(this);
        this._dragEndBound = this._dragEndBound || this._dragEnd.bind(this);
        // Listen on window so the drag tracks the pointer anywhere, independent
        // of pointer-capture support (robust + testable).
        window.addEventListener('pointermove', this._dragMoveBound);
        window.addEventListener('pointerup', this._dragEndBound);
        window.addEventListener('pointercancel', this._dragEndBound);
    }

    _dragMove(e) {
        const d = this._drag;
        if (!d) return;
        e.preventDefault();
        d.row.style.transform = `translateY(${e.clientY - d.pointerY0}px)`;
        const idx = computeDropIndex(d.centres, d.fromIndex, e.clientY);
        if (idx !== d.dropIndex) { d.dropIndex = idx; this._paintDropLine(d, idx); }
    }

    _paintDropLine(d, idx) {
        d.rows.forEach(r => r.classList.remove('drop-above', 'drop-below'));
        // Map the reduced-array insertion index back to a full-list row.
        const target = d.rows[idx < d.fromIndex ? idx : idx + 1];
        if (target && target !== d.row) target.classList.add('drop-above');
        else d.rows[d.rows.length - 1]?.classList.add('drop-below');
    }

    _dragEnd(e) {
        const d = this._drag;
        if (!d) return;
        window.removeEventListener('pointermove', this._dragMoveBound);
        window.removeEventListener('pointerup', this._dragEndBound);
        window.removeEventListener('pointercancel', this._dragEndBound);
        try { d.handle.releasePointerCapture(d.pointerId); } catch (_) {}
        d.row.style.transform = '';
        d.row.classList.remove('dragging-row');
        d.rows.forEach(r => r.classList.remove('drop-above', 'drop-below'));
        this._interacting = false;
        this._drag = null;
        if (e.type !== 'pointercancel' && d.dropIndex !== d.fromIndex) {
            this._moveDeviceToIndex(d.id, d.dropIndex);
        }
    }

    // Move a device to an arbitrary slot, regroup children, renumber, render,
    // send. Shared contract with the ▲▼ arrows (_moveDevice): the badge is
    // always the row's position, so number and order cannot disagree.
    _moveDeviceToIndex(deviceId, targetIndex) {
        this.devices = moveToIndex(this.devices, deviceId, targetIndex);
        this.requestUpdate();
        this._sendPriorityUpdate();
    }

    // ── Event binding (called from firstUpdated + updated) ──
    _bindEvents() {
        const root = this.renderRoot;
        const setBtn = root.getElementById('setTargetBtn');
        if (setBtn && !setBtn._semBound) {
            setBtn._semBound = true;
            setBtn.addEventListener('click', () => {
                const input = root.getElementById('targetInput');
                const val = parseFloat(input?.value);
                if (val && val > 0 && val <= 20) {
                    this.targetPeakLimit = val;
                    this._sendTargetPeakUpdate(val);
                    this.requestUpdate();
                }
            });
        }

        const delegateClick = (e) => {
            const target = e.target.closest('[data-action]');
            if (!target) return;
            const action   = target.dataset.action;
            const deviceId = target.dataset.device;

            if (action === 'controllable') {
                const device = this.devices.find(d => d.id === deviceId);
                if (device) {
                    device.isControllable = !device.isControllable;
                    this._sendDeviceUpdate(deviceId, 'controllable', device.isControllable);
                    this.requestUpdate();
                }
            } else if (action === 'move-up' || action === 'move-down') {
                this._moveDevice(deviceId, action === 'move-up' ? -1 : 1);
            } else if (action === 'configure') {
                this._showConfigureModal(deviceId, target.dataset.name);
            } else if (action === 'toggle-help') {
                this._showHelp = !this._showHelp;
                this.requestUpdate();
            } else if (action === 'toggle-goal') {
                this._goalOpen[deviceId] = !this._goalOpen[deviceId];
                this.requestUpdate();
            } else if (action === 'toggle-battery-overnight') {
                const device = this.devices.find(d => d.id === deviceId);
                if (device) this._toggleBatteryOvernight(device);
            }
        };

        const delegateChange = (e) => {
            const modeTarget = e.target.closest('[data-action="combined_mode"]');
            if (modeTarget) {
                const deviceId = modeTarget.dataset.device;
                const device = this.devices.find(d => d.id === deviceId);
                if (device) this._applyMergedMode(device, modeTarget.value);
                return;
            }
            const goalTarget = e.target.closest('[data-goal]');
            if (goalTarget) {
                const deviceId = goalTarget.dataset.device;
                const prop = goalTarget.dataset.goal;
                let value = goalTarget.value;
                const device = this.devices.find(d => d.id === deviceId);
                if (device) { device.goals = device.goals || {}; device.goals[prop] = value; }
                this._sendDeviceUpdate(deviceId, prop, String(value));
                return;
            }
            const depTarget = e.target.closest('[data-action="depends_on"]');
            if (depTarget) {
                const deviceId = depTarget.dataset.device;
                const device = this.devices.find(d => d.id === deviceId);
                if (device) {
                    const depValue = depTarget.value;
                    device.dependsOn = depValue ? [depValue] : [];
                    this._sendDeviceUpdate(deviceId, 'depends_on', depValue);
                    this._regroupChildren();
                    this.devices.forEach((d, i) => { d.priority = i + 1; });
                    this.requestUpdate();
                    this._sendPriorityUpdate();
                }
            }
        };

        // Re-bind only if not already bound (guard with a marker on the ha-card element)
        const card = root.querySelector('ha-card');
        if (card && !card._semEvtBound) {
            card._semEvtBound = true;
            card.addEventListener('click', delegateClick);
            card.addEventListener('change', delegateChange);
        }
    }

    // ── Device movement (arrows share moveToIndex with the pointer-drag) ──
    _moveDevice(deviceId, direction) {
        const idx = this.devices.findIndex(d => d.id === deviceId);
        if (idx === -1) return;
        const newIdx = idx + direction;
        if (newIdx < 0 || newIdx >= this.devices.length) return;
        if (this.devices[idx].dependsOn.length) return; // children locked
        this._moveDeviceToIndex(deviceId, newIdx);
    }

    // ── Dependency grouping ──
    _getDependencyDepth(device) {
        let depth = 0, current = device;
        const visited = new Set();
        while (current.dependsOn.length > 0 && depth < 5) {
            visited.add(current.id);
            const parentId = current.dependsOn[0];
            if (visited.has(parentId)) break;
            const parent = this.devices.find(d => d.id === parentId);
            if (!parent) break;
            depth++;
            current = parent;
        }
        return depth;
    }

    _regroupChildren() {
        this.devices = regroupChildren(this.devices);
    }

    // ── Service calls ──
    _sendPriorityUpdate() {
        if (!this._hass) return;
        this._hass.callService('solar_energy_management', 'update_device_priorities', {
            priorities: this.devices.map(d => ({ device_id: d.id, priority: d.priority })),
        });
        // Hold the just-dragged order until the backend re-emits the sensor
        // (~1 coordinator cycle). Without this the next hass push re-renders
        // the STALE sensor order and the drag snaps back — the "not taking it"
        // symptom. 15 s comfortably covers the ~10 s cycle; a fresh drag resets
        // it, and the sensor (now with the new order) takes over on expiry.
        this._priorityFrozenUntil = Date.now() + 15000;
    }

    _sendDeviceUpdate(deviceId, property, value) {
        if (!this._hass) return;
        this._hass.callService('solar_energy_management', 'update_device_config', {
            device_id: deviceId, property, value,
        });
    }

    _sendTargetPeakUpdate(val) {
        if (!this._hass) return;
        this._hass.callService('solar_energy_management', 'update_target_peak', {
            target_peak_limit: val,
        });
    }

    // ── Configure modal ──
    // Pre-fills from the saved mapping so reopening shows what is stored (the
    // #219 "empty on reopen" bug), and supports all four control types SEM can
    // shed/restore: switch, current, input_boolean (entity-based) and service.
    // ha-entity-picker is lazy-loaded by HA and is NOT registered on a custom
    // dashboard by default, so creating one cold yields nothing. Loading the
    // card helpers + an entities-card config element forces its registration.
    async _ensureEntityPicker() {
        if (customElements.get('ha-entity-picker')) return;
        try {
            const helpers = await window.loadCardHelpers?.();
            if (helpers?.createCardElement) {
                const el = await helpers.createCardElement({ type: 'entities', entities: [] });
                await el.constructor?.getConfigElement?.();
            }
        } catch (e) {
            // Falls back to the plain text input below.
        }
    }

    async _showConfigureModal(deviceId, deviceName) {
        const existing = this.renderRoot.getElementById('sem-config-modal');
        if (existing) existing.remove();
        // Resolve by the row's UNIQUE id — NOT by energySensor, which is
        // null/'' for every device without an Energy-Dashboard energy counter
        // (service-registered loads, direct heat-pump/hot-water, the battery
        // row). Keying on energySensor collided all such rows onto the FIRST
        // empty-key device, so opening the config card for one showed a
        // sibling's control entity (#621 — car socket showed the pool pump's
        // switch). The mapping service is still keyed by energy_sensor, taken
        // from the resolved device below.
        const dev = findDeviceForConfig(this.devices, deviceId);
        const energySensor = dev?.energySensor || '';
        const values = controlToFormValues(dev?.control);
        const hasManual = dev?.control?.discovered_via === 'manual_mapping';
        await this._ensureEntityPicker();

        const overlay = document.createElement('div');
        overlay.id = 'sem-config-modal';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:999;display:flex;align-items:center;justify-content:center';
        overlay.innerHTML = buildLoadConfigModalHTML({
            deviceName, values, t: (k) => this._t(k), hasManual,
        });
        this.renderRoot.appendChild(overlay);

        const typeSel      = overlay.querySelector('#cfg-type');
        const entityGroup  = overlay.querySelector('#cfg-entity-group');
        const serviceGroup = overlay.querySelector('#cfg-service-group');
        const entityInput  = overlay.querySelector('#cfg-entity');
        const errDiv       = overlay.querySelector('.cfg-error');
        const showError    = (msg) => { errDiv.textContent = msg; errDiv.style.display = 'block'; };

        // Upgrade the plain text box to an ha-entity-picker when HA has it
        // registered, so the user chooses a valid entity (filtered by control
        // type) instead of typing — the wrong-switch trap in #219. Falls back
        // to the text input if the picker element isn't available.
        let picker = null;
        if (customElements.get('ha-entity-picker')) {
            picker = document.createElement('ha-entity-picker');
            picker.hass = this._hass;
            picker.allowCustomEntity = true;
            picker.value = entityInput.value;
            picker.includeDomains = ENTITY_DOMAINS[typeSel.value];
            picker.style.cssText = 'display:block;margin:6px 0 12px';
            picker.addEventListener('value-changed', (e) => { entityInput.value = e.detail.value || ''; });
            entityInput.style.display = 'none';
            entityInput.parentNode.insertBefore(picker, entityInput);
        }

        const applyType = () => {
            const isService = typeSel.value === 'service';
            entityGroup.style.display  = isService ? 'none' : 'block';
            serviceGroup.style.display = isService ? 'block' : 'none';
            if (picker && !isService) picker.includeDomains = ENTITY_DOMAINS[typeSel.value];
        };
        typeSel.addEventListener('change', applyType);

        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
        overlay.querySelector('#cfg-cancel').addEventListener('click', () => overlay.remove());
        const removeBtn = overlay.querySelector('#cfg-remove');
        if (removeBtn) {
            removeBtn.addEventListener('click', () => {
                this._hass.callService('solar_energy_management', 'remove_device_control_mapping', {
                    energy_sensor: energySensor,
                }).then(() => {
                    // Optimistically clear locally so an immediate reopen reflects it;
                    // the next authoritative refresh restores any auto-discovered control.
                    if (dev) { dev.control = null; this.requestUpdate(); }
                    overlay.remove();
                }).catch(err => showError(err.message));
            });
        }
        overlay.querySelector('#cfg-save').addEventListener('click', () => {
            const formVals = readFormValues(overlay);
            if (picker) formVals.entity = (picker.value || '').trim();
            let data;
            try {
                data = formValuesToServiceData(energySensor, formVals);
            } catch (err) {
                showError(this._t(err.message));   // err.message is a translation key
                return;
            }
            this._hass.callService('solar_energy_management', 'set_device_control_mapping', data)
                .then(() => {
                    // Optimistically update local state so reopening the dialog in the
                    // same session shows the saved mapping (the card's hass-update gate
                    // keys on sensor STATE, not the per-device control attribute, so a
                    // control-only change wouldn't otherwise refresh this.devices). The
                    // next authoritative refresh confirms it.
                    if (dev) {
                        dev.control = data.control_type === 'service'
                            ? { type: 'service', service: data.service, param: data.param,
                                shed_value: data.shed_value, restore_value: data.restore_value,
                                discovered_via: 'manual_mapping' }
                            : { type: data.control_type, entity: data.control_entity,
                                discovered_via: 'manual_mapping' };
                        this.requestUpdate();
                    }
                    overlay.remove();
                })
                .catch(err => showError(err.message));
        });
    }

    // ── Helpers ──
    _getPeakColor() {
        const pct = this.targetPeakLimit > 0 ? (this.currentPeak / this.targetPeakLimit) * 100 : 0;
        if (pct >= 100) return '#f44336';
        if (pct >= 90)  return '#ff9800';
        if (pct >= 70)  return '#2196f3';
        return '#4caf50';
    }

    _resolveDeviceIcon(info) {
        // Try the original HA entity icon first (user-customizable)
        for (const eid of [info.switch_entity, info.power_entity, info.control?.entity]) {
            if (eid) {
                const s = this._hass?.states[eid];
                if (s?.attributes?.icon) return s.attributes.icon;
            }
        }
        // Fall back to device_type mapping
        const map = {
            ev_charger: 'mdi:ev-station', ev_charging: 'mdi:ev-station',
            battery: 'mdi:home-battery',
            heating: 'mdi:radiator', heat_pump: 'mdi:heat-pump',
            water_heater: 'mdi:water-boiler', hot_water: 'mdi:water-boiler',
            pool_pump: 'mdi:pool', appliance: 'mdi:washing-machine',
            climate: 'mdi:thermostat', light: 'mdi:lightbulb',
            printer: 'mdi:printer', computer: 'mdi:desktop-classic',
            network: 'mdi:network', fan: 'mdi:fan',
            dryer: 'mdi:tumble-dryer', dishwasher: 'mdi:dishwasher',
            freezer: 'mdi:fridge', refrigerator: 'mdi:fridge',
        };
        return map[info.device_type] || 'mdi:power-plug';
    }

    getCardSize() {
        return Math.max(5, 3 + this.devices.length);
    }

    static getStubConfig() {
        return { entity_prefix: 'sensor.sem_' };
    }
}

semDefineCard('sem-load-priority-card', SEMLoadPriorityCard, {
    type: 'sem-load-priority-card',
    name: 'SEM Load Priority Card',
    description: 'Drag and drop interface for managing load shedding priorities',
    preview: true,
});
