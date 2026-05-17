(window.semReady || (fn => { window._semReadyQueue = window._semReadyQueue || []; window._semReadyQueue.push(fn); }))(function() {
/**
 * SEM Control Card — Consolidated control panel
 *
 * Replaces all mushroom cards on the Control tab with a single,
 * interactive card featuring collapsible sections, toggles,
 * number steppers, select dropdowns, and read-only displays.
 *
 * Config:
 *   type: custom:sem-control-card
 *   entity_prefix: sensor.sem_   # optional, default
 */

const SECTIONS = [
    {
        id: 'ev', icon: 'mdi:ev-station', color: '#8DC892', titleKey: 'ev_charging_title',
        subtitleFn: (c) => {
            const state = c._stateStr('charging_state') || '—';
            const daily = c._state('daily_ev_energy').toFixed(1);
            const target = c._numState('daily_ev_target').toFixed(0);
            return `${state} · ${daily}/${target} kWh`;
        },
    },
    {
        id: 'surplus', icon: 'mdi:solar-power', color: '#ff9800', titleKey: 'surplus_control',
        subtitleFn: (c) => {
            const active = c._state('surplus_active_devices').toFixed(0);
            const total = c._state('surplus_total_devices').toFixed(0);
            const alloc = c._state('surplus_allocated_w').toFixed(0);
            return `${active}/${total} ${c._t('devices')} · ${alloc}W`;
        },
    },
    {
        id: 'battery', icon: 'mdi:battery-medium', color: '#4db6ac', titleKey: 'battery_management',
        subtitleFn: (c) => {
            const soc = c._state('battery_soc').toFixed(0);
            const status = c._stateStr('battery_status') || '—';
            return `SOC ${soc}% · ${status}`;
        },
    },
    {
        id: 'hotwater', icon: 'mdi:water-thermometer', color: '#f06292', titleKey: 'hot_water_title',
        subtitleFn: () => '',
    },
    {
        id: 'solar', icon: 'mdi:solar-panel-large', color: '#ff9800', titleKey: 'solar_power_section',
        subtitleFn: () => '',
    },
    {
        id: 'tariff', icon: 'mdi:cash-multiple', color: '#96CAEE', titleKey: 'tariff_pricing',
        subtitleFn: (c) => {
            const provider = c._stateStr('tariff_provider') || '—';
            const level = c._stateStr('tariff_price_level') || '';
            return level ? `${provider} · ${level}` : provider;
        },
    },
    {
        id: 'peak', icon: 'mdi:flash-alert', color: '#ff9800', titleKey: 'peak_load_management',
        subtitleFn: (c) => {
            const peak = c._state('consecutive_peak_15min').toFixed(1);
            const monthly = c._state('monthly_consecutive_peak').toFixed(1);
            return `${c._t('peak')} ${peak} kW · ${c._t('monthly_peak')} ${monthly} kW`;
        },
    },
    {
        id: 'system', icon: 'mdi:cog-outline', color: '#96CAEE', titleKey: 'system',
        subtitleFn: () => '',
    },
];

class SEMControlCard extends SEMBaseCard {
    constructor() {
        super();
        this._rendered = false;
        this._lastKey = '';
        this._collapsed = {};
        this._holdTimers = {};
        this._holdIntervals = {};
        this._frozenEntities = {};
        this._debugLog = [];
        this._instanceId = ++SEMControlCard._instanceCount;
        this._dbg('CONSTRUCTOR #' + this._instanceId);
    }

    _dbg(msg) {
        const t = new Date().toLocaleTimeString('en', {hour12:false, hour:'2-digit', minute:'2-digit', second:'2-digit'});
        this._debugLog.push(`${t} ${msg}`);
        if (this._debugLog.length > 12) this._debugLog.shift();
        const el = this.shadowRoot?.querySelector('.dbg-panel');
        if (el) el.textContent = this._debugLog.join('\n');
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
        this._dbg('setConfig');
    }

    // Read a sensor state as number
    _state(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    // Read a number.sem_ entity state
    _numState(suffix, fallback = 0) {
        const e = this._hass?.states[`number.sem_${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    // Read a number entity's attributes (min, max, step)
    _numAttrs(suffix) {
        const e = this._hass?.states[`number.sem_${suffix}`];
        if (!e) return { min: 0, max: 100, step: 1 };
        return {
            min: parseFloat(e.attributes.min) || 0,
            max: parseFloat(e.attributes.max) || 100,
            step: parseFloat(e.attributes.step) || 1,
        };
    }

    // Read a sensor/switch/select string state
    _stateStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return (e && e.state !== 'unavailable' && e.state !== 'unknown') ? e.state : '';
    }

    // Read switch state
    _switchState(suffix) {
        const e = this._hass?.states[`switch.sem_${suffix}`];
        return e?.state === 'on';
    }

    // Read select state + options
    _selectState(suffix) {
        const e = this._hass?.states[`select.sem_${suffix}`];
        if (!e) return { value: '', options: [] };
        return { value: e.state, options: e.attributes.options || [] };
    }

    // ── Freeze/thaw pattern: suppress hass updates for 1s after service call ──
    _freezeEntity(entityId, optimisticValue) {
        const existing = this._frozenEntities[entityId];
        if (existing?.timer) clearTimeout(existing.timer);
        this._frozenEntities[entityId] = {
            value: optimisticValue,
            timer: setTimeout(() => {
                delete this._frozenEntities[entityId];
                // Accept confirmed value from HA
                if (this._hass) this._update();
            }, 1000),
        };
    }

    _isFrozen() {
        return Object.keys(this._frozenEntities).length > 0;
    }

    set hass(hass) {
        const localeChanged = this._checkLocaleChange(hass);

        // While entities are frozen (user just clicked), skip full update
        if (this._isFrozen() && !localeChanged) {
            this._dbg('hass SKIP (frozen)');
            return;
        }

        // Build reactivity key from all relevant entities
        const watchKeys = [
            'sensor.sem_charging_state', 'sensor.sem_daily_ev_energy',
            'number.sem_daily_ev_target', 'select.sem_ev_charging_mode',
            'switch.sem_night_charging', 'switch.sem_smart_night_charging',
            'number.sem_ev_night_initial_current', 'number.sem_ev_minimum_current',
            'number.sem_ev_stall_cooldown', 'number.sem_ev_phases',
            'sensor.sem_surplus_active_devices', 'sensor.sem_surplus_total_devices',
            'sensor.sem_surplus_allocated_w', 'sensor.sem_surplus_total_w',
            'sensor.sem_surplus_distributable_w', 'sensor.sem_surplus_unallocated_w',
            'number.sem_regulation_offset',
            'sensor.sem_battery_soc', 'sensor.sem_battery_status',
            'number.sem_battery_priority_soc', 'number.sem_battery_minimum_soc',
            'number.sem_battery_resume_soc', 'sensor.sem_diag_battery_capacity',
            'number.sem_hot_water_solar_target', 'number.sem_legionella_target_temp',
            'number.sem_minimum_solar_power', 'number.sem_maximum_grid_import',
            'sensor.sem_tariff_provider', 'sensor.sem_tariff_price_level',
            'sensor.sem_tariff_current_import_rate',
            'number.sem_cheap_price_threshold', 'number.sem_expensive_price_threshold',
            'sensor.sem_consecutive_peak_15min', 'sensor.sem_monthly_consecutive_peak',
            'sensor.sem_current_vs_peak_percentage', 'sensor.sem_load_management_status',
            'sensor.sem_load_management_recommendation',
            'sensor.sem_peak_margin', 'sensor.sem_available_load_reduction',
            'sensor.sem_controllable_devices_count',
            'switch.sem_observer_mode',
        ];
        const key = watchKeys.map(k => hass.states[k]?.state || '').join(',');

        if (key === this._lastKey && !localeChanged) {
            this._dbg('hass SKIP (key same)');
            return;
        }
        this._lastKey = key;

        if (!this._rendered || localeChanged) {
            this._dbg('RENDER SKELETON (rendered=' + this._rendered + ' locale=' + localeChanged + ')');
            this.style.visibility = 'hidden';
            this._renderSkeleton();
            this._rendered = true;
            this._update();
            requestAnimationFrame(() => { this.style.visibility = ''; });
            return;
        }
        this._dbg('_update (key changed)');
        this._update();
    }

    _toggleSection(id) {
        this._collapsed[id] = !this._collapsed[id];
        const section = this.shadowRoot.querySelector(`[data-section="${id}"]`);
        if (!section) return;
        const body = section.querySelector('.section-body');
        const chevron = section.querySelector('.chevron');
        if (this._collapsed[id]) {
            body.style.maxHeight = '0';
            body.style.opacity = '0';
            chevron.style.transform = 'rotate(-90deg)';
        } else {
            body.style.maxHeight = body.scrollHeight + 'px';
            body.style.opacity = '1';
            chevron.style.transform = 'rotate(0deg)';
            // Allow dynamic content to expand
            setTimeout(() => { if (!this._collapsed[id]) body.style.maxHeight = 'none'; }, 350);
        }
    }

    async _callService(domain, service, data) {
        if (!this._hass) return;
        try {
            await this._hass.callService(domain, service, data);
        } catch (e) {
            console.error('[SEM Control]', domain, service, data, e);
        }
    }

    _toggleSwitch(entityId) {
        const state = this._hass?.states[entityId];
        if (!state) return;
        const newState = state.state === 'on' ? 'off' : 'on';
        this._freezeEntity(entityId, newState);
        const svc = state.state === 'on' ? 'turn_off' : 'turn_on';
        this._callService('switch', svc, { entity_id: entityId });
    }

    _setNumber(entityId, value) {
        const entity = this._hass?.states[entityId];
        if (!entity) return;
        const min = parseFloat(entity.attributes.min) || 0;
        const max = parseFloat(entity.attributes.max) || 100;
        const clamped = Math.max(min, Math.min(max, value));
        this._freezeEntity(entityId, clamped);
        this._callService('number', 'set_value', { entity_id: entityId, value: clamped });
    }

    _stepNumber(entityId, delta) {
        const entity = this._hass?.states[entityId];
        if (!entity) return;
        const frozen = this._frozenEntities[entityId];
        const current = frozen ? frozen.value : (parseFloat(entity.state) || 0);
        const step = parseFloat(entity.attributes.step) || 1;
        this._setNumber(entityId, current + delta * step);
        this._update(); // show optimistic value immediately
    }

    _selectOption(entityId, option) {
        this._freezeEntity(entityId, option);
        this._callService('select', 'select_option', { entity_id: entityId, option });
    }

    // Start hold-to-repeat for number stepper
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

    _update() {
        if (!this._hass) return;
        const $ = (sel) => this.shadowRoot.querySelector(sel);
        const setVal = (sel, text) => { const el = $(sel); if (el && el.textContent !== text) el.textContent = text; };

        // Observer mode warning — use height/opacity instead of display to avoid layout shift
        const obsOn = this._switchState('observer_mode');
        if (obsOn !== this._lastObsState) {
            this._lastObsState = obsOn;
            const obsWarn = $('.observer-warning');
            if (obsWarn) {
                obsWarn.style.maxHeight = obsOn ? '60px' : '0';
                obsWarn.style.opacity = obsOn ? '1' : '0';
                obsWarn.style.marginBottom = obsOn ? '12px' : '0';
                obsWarn.style.padding = obsOn ? '12px 16px' : '0 16px';
            }
        }

        // Section subtitles
        for (const s of SECTIONS) {
            setVal(`[data-section="${s.id}"] .section-subtitle`, s.subtitleFn(this));
            setVal(`[data-section="${s.id}"] .section-title-text`, this._t(s.titleKey));
        }

        // ── EV Charging ──
        this._updateSelect('.ev-mode', 'select.sem_ev_charging_mode');
        this._updateToggle('.ev-night', 'switch.sem_night_charging', 'night_charging');
        this._updateToggle('.ev-smart', 'switch.sem_smart_night_charging', 'smart_night');
        this._updateStepper('.ev-target', 'number.sem_daily_ev_target');
        this._updateStepper('.ev-initial', 'number.sem_ev_night_initial_current');
        this._updateStepper('.ev-stall', 'number.sem_ev_stall_cooldown');

        // Conditional: min current
        const minCurEnt = this._hass.states['number.sem_ev_minimum_current'];
        const minCurRow = $('.ev-mincur-row');
        if (minCurRow) {
            const show = minCurEnt && parseFloat(minCurEnt.state) > 0;
            const mcDisplay = show ? '' : 'none';
            if (minCurRow.style.display !== mcDisplay) minCurRow.style.display = mcDisplay;
            if (show) this._updateStepper('.ev-mincur', 'number.sem_ev_minimum_current');
        }

        // Conditional: phases
        const phasesEnt = this._hass.states['number.sem_ev_phases'];
        const phasesRow = $('.ev-phases-row');
        if (phasesRow) {
            const show = phasesEnt && parseFloat(phasesEnt.state) > 0;
            const phDisplay = show ? '' : 'none';
            if (phasesRow.style.display !== phDisplay) phasesRow.style.display = phDisplay;
            if (show) this._updateStepper('.ev-phases', 'number.sem_ev_phases');
        }

        // ── Surplus ──
        const surplusTotal = this._state('surplus_total_w').toFixed(0);
        const surplusDist = this._state('surplus_distributable_w').toFixed(0);
        const surplusAlloc = this._state('surplus_allocated_w').toFixed(0);
        const surplusFree = this._state('surplus_unallocated_w').toFixed(0);
        setVal('.surplus-total-val', `${surplusTotal}W`);
        setVal('.surplus-dist-val', `${surplusDist}W`);
        setVal('.surplus-alloc-val', `${surplusAlloc}W`);
        setVal('.surplus-free-val', `${surplusFree}W`);
        this._updateStepper('.surplus-offset', 'number.sem_regulation_offset');

        // ── Battery ──
        this._updateStepper('.batt-priority', 'number.sem_battery_priority_soc');
        this._updateStepper('.batt-min', 'number.sem_battery_minimum_soc');
        this._updateStepper('.batt-resume', 'number.sem_battery_resume_soc');
        const capacity = this._state('diag_battery_capacity');
        setVal('.batt-capacity-val', capacity > 0 ? capacity.toFixed(1) + ' kWh' : '—');

        // ── Hot Water ──
        this._updateStepper('.hw-solar', 'number.sem_hot_water_solar_target');
        this._updateStepper('.hw-legionella', 'number.sem_legionella_target_temp');

        // ── Solar & Power ──
        this._updateStepper('.sp-min-solar', 'number.sem_minimum_solar_power');
        this._updateStepper('.sp-max-grid', 'number.sem_maximum_grid_import');

        // ── Tariff ──
        const rateEnt = this._hass.states['sensor.sem_tariff_current_import_rate'];
        const rate = rateEnt ? rateEnt.state : '—';
        const rateUnit = rateEnt?.attributes?.unit_of_measurement || '';
        setVal('.tariff-rate-val', `${rate} ${rateUnit}`);
        this._updateStepper('.tariff-cheap', 'number.sem_cheap_price_threshold');
        this._updateStepper('.tariff-expensive', 'number.sem_expensive_price_threshold');

        // ── Peak ──
        const peakPct = this._state('current_vs_peak_percentage');
        const peakPctEl = $('.peak-pct');
        if (peakPctEl) {
            const peakText = `${peakPct.toFixed(0)}%`;
            if (peakPctEl.textContent !== peakText) peakPctEl.textContent = peakText;
            const peakColor = peakPct > 90 ? '#f44336' : peakPct > 70 ? '#ff9800' : '#8DC892';
            if (peakPctEl.style.color !== peakColor) peakPctEl.style.color = peakColor;
        }
        const lmStatus = this._stateStr('load_management_status') || '—';
        setVal('.peak-status', this._t(lmStatus) || lmStatus);
        const lmRec = this._stateStr('load_management_recommendation') || '';
        setVal('.peak-rec', this._t(lmRec) || lmRec);
        setVal('.peak-margin-val', this._state('peak_margin').toFixed(1) + ' kW');
        const shed = this._state('available_load_reduction');
        const shedDevices = this._state('controllable_devices_count').toFixed(0);
        setVal('.peak-shed-val', `${shed.toFixed(1)} kW · ${shedDevices} ${this._t('devices')}`);

        // ── System ──
        this._updateToggle('.sys-observer', 'switch.sem_observer_mode', 'observer_mode');

        // Update all labels
        this._updateLabels();
    }

    _updateToggle(selector, entityId, labelKey) {
        const el = this.shadowRoot.querySelector(selector);
        if (!el) return;
        const state = this._hass?.states[entityId];
        const isOn = state?.state === 'on';
        const track = el.querySelector('.toggle-track');
        const label = el.querySelector('.toggle-label');
        if (track) {
            track.classList.toggle('on', isOn);
            // Bind handler only once
            if (!track._semBound) {
                track._semBound = true;
                track.addEventListener('click', () => this._toggleSwitch(entityId));
            }
        }
        const translated = this._t(labelKey);
        if (label && label.textContent !== translated) label.textContent = translated;
    }

    _updateSelect(selector, entityId) {
        const el = this.shadowRoot.querySelector(selector);
        if (!el) return;
        const state = this._hass?.states[entityId];
        if (!state) return;
        const selectEl = el.querySelector('select');
        if (selectEl) {
            // Rebuild options if changed
            const opts = state.attributes.options || [];
            if (selectEl.children.length !== opts.length) {
                selectEl.innerHTML = opts.map(o =>
                    `<option value="${o}">${o}</option>`
                ).join('');
            }
            selectEl.value = state.state;
            selectEl.onchange = (e) => this._selectOption(entityId, e.target.value);
        }
    }

    _updateStepper(selector, entityId) {
        const el = this.shadowRoot.querySelector(selector);
        if (!el) return;
        const entity = this._hass?.states[entityId];
        if (!entity) return;
        // Use frozen optimistic value if available
        const frozen = this._frozenEntities[entityId];
        const val = frozen ? frozen.value : (parseFloat(entity.state) || 0);
        const step = parseFloat(entity.attributes.step) || 1;
        const unit = entity.attributes.unit_of_measurement || '';
        const valEl = el.querySelector('.stepper-value');
        if (valEl) {
            const decimals = step < 1 ? 1 : 0;
            const text = val.toFixed(decimals) + (unit ? ' ' + unit : '');
            if (valEl.textContent !== text) valEl.textContent = text;
        }
        // Bind handlers only once
        if (!el._semBound) {
            el._semBound = true;
            const minBtn = el.querySelector('.stepper-minus');
            const plusBtn = el.querySelector('.stepper-plus');
            if (minBtn) {
                minBtn.addEventListener('click', () => this._stepNumber(entityId, -1));
                minBtn.addEventListener('pointerdown', () => this._startHold(entityId, -1));
                minBtn.addEventListener('pointerup', () => this._stopHold(entityId));
                minBtn.addEventListener('pointerleave', () => this._stopHold(entityId));
            }
            if (plusBtn) {
                plusBtn.addEventListener('click', () => this._stepNumber(entityId, 1));
                plusBtn.addEventListener('pointerdown', () => this._startHold(entityId, 1));
                plusBtn.addEventListener('pointerup', () => this._stopHold(entityId));
                plusBtn.addEventListener('pointerleave', () => this._stopHold(entityId));
            }
        }
    }

    _updateLabels() {
        const setLabel = (sel, key) => {
            const el = this.shadowRoot.querySelector(sel);
            const text = this._t(key);
            if (el && el.textContent !== text) el.textContent = text;
        };
        // EV
        setLabel('.ev-mode .ctrl-label', 'ev_charging_mode');
        setLabel('.ev-target .stepper-label', 'night_charge_target');
        setLabel('.ev-initial .stepper-label', 'night_start_amps');
        setLabel('.ev-mincur .stepper-label', 'min_current');
        setLabel('.ev-stall .stepper-label', 'stall_cooldown');
        setLabel('.ev-phases .stepper-label', 'charger_phases');
        // Surplus
        setLabel('.surplus-total-lbl', 'surplus_available');
        setLabel('.surplus-alloc-lbl', 'surplus_allocation');
        setLabel('.surplus-offset .stepper-label', 'regulation_offset');
        // Battery
        setLabel('.batt-priority .stepper-label', 'priority_soc');
        setLabel('.batt-min .stepper-label', 'minimum_soc');
        setLabel('.batt-resume .stepper-label', 'resume_soc');
        setLabel('.batt-capacity-lbl', 'capacity_kwh');
        // Hot Water
        setLabel('.hw-solar .stepper-label', 'solar_boost_target');
        setLabel('.hw-legionella .stepper-label', 'legionella_target');
        setLabel('.hw-info-title', 'legionella_prevention');
        // Solar
        setLabel('.sp-min-solar .stepper-label', 'min_solar');
        setLabel('.sp-max-grid .stepper-label', 'max_grid_import');
        // Tariff
        setLabel('.tariff-rate-lbl', 'current_electricity_price');
        setLabel('.tariff-cheap .stepper-label', 'cheap_threshold');
        setLabel('.tariff-expensive .stepper-label', 'expensive_threshold');
        // Peak
        setLabel('.peak-margin-lbl', 'peak_margin');
        setLabel('.peak-shed-lbl', 'sheddable');
    }

    _makeToggleHTML(cls, labelKey) {
        return `
            <div class="${cls} toggle-row">
                <span class="toggle-label">${this._t(labelKey)}</span>
                <div class="toggle-track"><div class="toggle-thumb"></div></div>
            </div>`;
    }

    _makeStepperHTML(cls, labelKey) {
        return `
            <div class="${cls} stepper-row">
                <span class="stepper-label">${this._t(labelKey)}</span>
                <div class="stepper-controls">
                    <button class="stepper-minus" aria-label="Decrease">−</button>
                    <span class="stepper-value">—</span>
                    <button class="stepper-plus" aria-label="Increase">+</button>
                </div>
            </div>`;
    }

    _makeSectionHTML(section, bodyHTML) {
        const collapsed = this._collapsed[section.id];
        return `
            <div class="section" data-section="${section.id}">
                <div class="section-header" tabindex="0" role="button" aria-expanded="${!collapsed}">
                    <ha-icon icon="${section.icon}" style="--mdc-icon-size:20px;color:${section.color}"></ha-icon>
                    <span class="section-title-text">${this._t(section.titleKey)}</span>
                    <span class="section-subtitle"></span>
                    <ha-icon class="chevron" icon="mdi:chevron-down"
                             style="--mdc-icon-size:18px;transform:rotate(${collapsed ? '-90deg' : '0deg'})"></ha-icon>
                </div>
                <div class="section-body" style="max-height:${collapsed ? '0' : 'none'};opacity:${collapsed ? '0' : '1'}">
                    ${bodyHTML}
                </div>
            </div>`;
    }

    _renderSkeleton() {
        const T = (typeof semTheme === 'function') ? semTheme() : {};
        const textCol = T.text || '#e0e0e0';
        const textSecCol = T.textSec || '#999';
        const surfaceCol = T.surface || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.12)';
        const surfHover = T.surfaceHover || 'rgba(255,255,255,0.10)';
        const dotCol = T.dotColor || 'rgba(128,128,128,0.05)';
        const isDark = T.isDark !== false;
        const accent = T.accent || '#42a5f5';

        // Build section bodies
        const evBody = `
            <div class="ev-mode ctrl-row">
                <span class="ctrl-label">${this._t('ev_charging_mode')}</span>
                <select class="sem-select"></select>
            </div>
            <div class="toggle-group">
                ${this._makeToggleHTML('ev-night', 'night_charging')}
                ${this._makeToggleHTML('ev-smart', 'smart_night')}
            </div>
            ${this._makeStepperHTML('ev-target', 'night_charge_target')}
            <div class="stepper-pair">
                ${this._makeStepperHTML('ev-initial', 'night_start')}
                <div class="ev-mincur-row">
                    ${this._makeStepperHTML('ev-mincur', 'min_current')}
                </div>
            </div>
            <div class="stepper-pair">
                ${this._makeStepperHTML('ev-stall', 'stall_cooldown')}
                <div class="ev-phases-row">
                    ${this._makeStepperHTML('ev-phases', 'charger_phases')}
                </div>
            </div>`;

        const surplusBody = `
            <div class="info-tiles">
                <div class="info-tile">
                    <ha-icon icon="mdi:solar-power" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                    <div class="info-tile-content">
                        <span class="surplus-total-lbl info-tile-label">${this._t('surplus_available')}</span>
                        <span class="info-tile-values">
                            <span class="surplus-total-val">—</span>
                            <span class="info-tile-sep">·</span>
                            <span class="surplus-dist-val">—</span>
                        </span>
                    </div>
                </div>
                <div class="info-tile">
                    <ha-icon icon="mdi:chart-pie" style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                    <div class="info-tile-content">
                        <span class="surplus-alloc-lbl info-tile-label">${this._t('surplus_allocation')}</span>
                        <span class="info-tile-values">
                            <span class="surplus-alloc-val">—</span>
                            <span class="info-tile-sep">·</span>
                            <span class="surplus-free-val">—</span>
                        </span>
                    </div>
                </div>
            </div>
            ${this._makeStepperHTML('surplus-offset', 'regulation_offset')}`;

        const battBody = `
            <div class="stepper-pair">
                ${this._makeStepperHTML('batt-priority', 'priority_soc')}
                ${this._makeStepperHTML('batt-min', 'minimum_soc')}
            </div>
            <div class="stepper-pair">
                ${this._makeStepperHTML('batt-resume', 'resume_soc')}
                <div class="readonly-row">
                    <span class="batt-capacity-lbl ctrl-label">${this._t('capacity_kwh')}</span>
                    <span class="batt-capacity-val readonly-value">—</span>
                </div>
            </div>`;

        const hwBody = `
            <div class="stepper-pair">
                ${this._makeStepperHTML('hw-solar', 'solar_boost_target')}
                ${this._makeStepperHTML('hw-legionella', 'legionella_target')}
            </div>
            <div class="info-box">
                <ha-icon icon="mdi:shield-alert" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                <div>
                    <div class="hw-info-title info-box-title">${this._t('legionella_prevention')}</div>
                    <div class="info-box-text">
                        DE (DVGW W 551): ≥ 60°C · CH (SIA 385/1): ≥ 60°C · AT (ÖNORM B 5019): 60°C / 70°C 3 min
                    </div>
                </div>
            </div>`;

        const solarBody = `
            <div class="stepper-pair">
                ${this._makeStepperHTML('sp-min-solar', 'min_solar')}
                ${this._makeStepperHTML('sp-max-grid', 'max_grid_import')}
            </div>`;

        const tariffBody = `
            <div class="readonly-row tariff-rate-row">
                <ha-icon icon="mdi:flash" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                <span class="tariff-rate-lbl ctrl-label">${this._t('current_electricity_price')}</span>
                <span class="tariff-rate-val readonly-value">—</span>
            </div>
            <div class="stepper-pair">
                ${this._makeStepperHTML('tariff-cheap', 'cheap_threshold')}
                ${this._makeStepperHTML('tariff-expensive', 'expensive_threshold')}
            </div>`;

        const peakBody = `
            <div class="peak-hero">
                <span class="peak-pct">—</span>
                <span class="peak-of-limit">${this._t('of_limit')}</span>
            </div>
            <div class="peak-detail">
                <span class="peak-status">—</span>
                <span class="peak-sep">·</span>
                <span class="peak-rec"></span>
            </div>
            <div class="info-tiles">
                <div class="info-tile">
                    <ha-icon icon="mdi:shield-check" style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                    <div class="info-tile-content">
                        <span class="peak-margin-lbl info-tile-label">${this._t('peak_margin')}</span>
                        <span class="peak-margin-val info-tile-value">—</span>
                    </div>
                </div>
                <div class="info-tile">
                    <ha-icon icon="mdi:power-plug-off" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                    <div class="info-tile-content">
                        <span class="peak-shed-lbl info-tile-label">${this._t('sheddable')}</span>
                        <span class="peak-shed-val info-tile-value">—</span>
                    </div>
                </div>
            </div>`;

        const systemBody = `
            ${this._makeToggleHTML('sys-observer', 'observer_mode')}`;

        const bodies = { ev: evBody, surplus: surplusBody, battery: battBody, hotwater: hwBody, solar: solarBody, tariff: tariffBody, peak: peakBody, system: systemBody };

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 20%, rgba(150,202,238,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${textCol});
                }

                /* ── Observer Warning ── */
                .observer-warning {
                    display: flex;
                    align-items: center; gap: 10px;
                    padding: 0 16px; margin-bottom: 0;
                    max-height: 0; opacity: 0;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease, margin-bottom 0.3s ease, padding 0.3s ease;
                    border-radius: 12px;
                    background: radial-gradient(ellipse 60% 50% at 50% 40%, rgba(244,67,54,0.12) 0%, transparent 100%),
                                radial-gradient(circle at 2px 2px, rgba(244,67,54,0.05) 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    border: 1px solid rgba(244,67,54,0.35);
                    color: #f44336;
                    font-size: 13px; font-weight: 500;
                }
                .observer-warning ha-icon { flex-shrink: 0; }

                /* ── Sections ── */
                .section {
                    margin-bottom: 8px;
                    border-radius: 14px;
                    background: ${surfaceCol};
                    border: 1px solid ${surfBorder};
                    overflow: hidden;
                    transition: border-color 0.2s;
                }
                .section:hover { border-color: ${isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.12)'}; }

                .section-header {
                    display: flex; align-items: center; gap: 8px;
                    padding: 12px 14px;
                    cursor: pointer;
                    user-select: none;
                    -webkit-user-select: none;
                    transition: background 0.15s;
                }
                .section-header:hover { background: ${surfHover}; }
                .section-title-text {
                    font-size: 14px; font-weight: 600;
                    white-space: nowrap;
                }
                .section-subtitle {
                    flex: 1;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${textSecCol});
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-right: 4px;
                }
                .chevron {
                    transition: transform 0.25s ease;
                    color: var(--secondary-text-color, ${textSecCol});
                    flex-shrink: 0;
                }

                .section-body {
                    padding: 0 14px;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.25s ease;
                }
                .section-body > *:last-child { margin-bottom: 14px; }

                /* ── Toggle ── */
                .toggle-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 8px 0;
                }
                .toggle-group {
                    border-bottom: 1px solid ${surfBorder};
                    margin-bottom: 8px;
                    padding-bottom: 4px;
                }
                .toggle-label {
                    font-size: 13px; font-weight: 500;
                }
                .toggle-track {
                    position: relative;
                    width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.18)'};
                    cursor: pointer;
                    transition: background 0.2s;
                    flex-shrink: 0;
                }
                .toggle-track.on {
                    background: ${accent};
                }
                .toggle-thumb {
                    position: absolute;
                    top: 2px; left: 2px;
                    width: 20px; height: 20px;
                    border-radius: 50%;
                    background: white;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                    transition: left 0.2s;
                }
                .toggle-track.on .toggle-thumb { left: 20px; }

                /* ── Select ── */
                .ctrl-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 8px 0;
                    border-bottom: 1px solid ${surfBorder};
                    margin-bottom: 4px;
                }
                .ctrl-label {
                    font-size: 13px; font-weight: 500;
                }
                .sem-select {
                    background: ${surfaceCol};
                    border: 1px solid ${surfBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${textCol});
                    padding: 6px 10px;
                    font-size: 13px;
                    font-family: inherit;
                    cursor: pointer;
                    min-width: 120px;
                    outline: none;
                }
                .sem-select:focus { border-color: ${accent}; }
                .sem-select option {
                    background: ${isDark ? '#1e232d' : '#fff'};
                    color: ${isDark ? '#e0e0e0' : '#333'};
                }

                /* ── Number Stepper ── */
                .stepper-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                }
                .stepper-label {
                    font-size: 13px; font-weight: 500;
                    flex: 1;
                    min-width: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .stepper-controls {
                    display: flex; align-items: center; gap: 2px;
                    flex-shrink: 0;
                }
                .stepper-minus, .stepper-plus {
                    width: 30px; height: 30px;
                    border-radius: 8px;
                    border: 1px solid ${surfBorder};
                    background: ${surfaceCol};
                    color: var(--primary-text-color, ${textCol});
                    font-size: 16px; font-weight: 600;
                    cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.15s, border-color 0.15s;
                    user-select: none;
                    -webkit-user-select: none;
                    touch-action: manipulation;
                    padding: 0;
                    line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover {
                    background: ${surfHover};
                    border-color: ${accent};
                }
                .stepper-minus:active, .stepper-plus:active {
                    background: ${isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.08)'};
                }
                .stepper-value {
                    font-size: 13px; font-weight: 600;
                    min-width: 60px; text-align: center;
                    font-variant-numeric: tabular-nums;
                }

                .stepper-pair {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 0 16px;
                }
                @media (max-width: 480px) {
                    .stepper-pair { grid-template-columns: 1fr; }
                }

                /* ── Read-only row ── */
                .readonly-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                }
                .readonly-value {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--secondary-text-color, ${textSecCol});
                }
                .tariff-rate-row {
                    gap: 8px;
                    border-bottom: 1px solid ${surfBorder};
                    margin-bottom: 8px;
                    padding-bottom: 10px;
                }
                .tariff-rate-row .ctrl-label { flex: 1; }
                .tariff-rate-row .readonly-value { font-size: 15px; font-weight: 700; color: ${textCol}; }

                /* ── Info tiles (surplus, peak) ── */
                .info-tiles {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 8px;
                    margin: 8px 0;
                }
                .info-tile {
                    display: flex; align-items: flex-start; gap: 8px;
                    padding: 10px;
                    border-radius: 10px;
                    background: ${isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)'};
                    border: 1px solid ${surfBorder};
                }
                .info-tile ha-icon { margin-top: 1px; flex-shrink: 0; }
                .info-tile-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
                .info-tile-label {
                    font-size: 11px; font-weight: 500; text-transform: uppercase;
                    color: var(--secondary-text-color, ${textSecCol});
                    letter-spacing: 0.3px;
                }
                .info-tile-values {
                    font-size: 13px; font-weight: 600;
                    display: flex; gap: 4px; flex-wrap: wrap;
                }
                .info-tile-value {
                    font-size: 13px; font-weight: 600;
                }
                .info-tile-sep {
                    color: var(--secondary-text-color, ${textSecCol});
                }

                /* ── Info box (legionella) ── */
                .info-box {
                    display: flex; gap: 8px;
                    padding: 10px 12px;
                    border-radius: 10px;
                    background: ${isDark ? 'rgba(255,152,0,0.06)' : 'rgba(255,152,0,0.05)'};
                    border: 1px solid rgba(255,152,0,0.2);
                    margin-top: 8px;
                }
                .info-box ha-icon { flex-shrink: 0; margin-top: 1px; }
                .info-box-title {
                    font-size: 12px; font-weight: 600; margin-bottom: 2px;
                }
                .info-box-text {
                    font-size: 11px; line-height: 1.4;
                    color: var(--secondary-text-color, ${textSecCol});
                }

                /* ── Peak hero ── */
                .peak-hero {
                    display: flex; align-items: baseline; justify-content: center;
                    gap: 6px; padding: 4px 0;
                }
                .peak-pct {
                    font-size: 28px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                }
                .peak-of-limit {
                    font-size: 12px; font-weight: 500;
                    color: var(--secondary-text-color, ${textSecCol});
                    text-transform: uppercase;
                }
                .peak-detail {
                    text-align: center; padding: 0 0 8px;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${textSecCol});
                }
                .peak-sep { margin: 0 4px; }

                @media (max-width: 480px) {
                    .info-tiles { grid-template-columns: 1fr; }
                }
            </style>
            <div class="wrap">
                <pre class="dbg-panel" style="font-size:9px;color:#888;background:rgba(0,0,0,0.3);padding:6px 8px;border-radius:6px;margin-bottom:8px;white-space:pre;overflow:hidden;max-height:120px;font-family:monospace;line-height:1.3">${this._debugLog.join('\n')}</pre>
                <div class="observer-warning">
                    <ha-icon icon="mdi:eye-outline" style="--mdc-icon-size:20px;color:#f44336"></ha-icon>
                    <span>${this._t('observer_mode_active')} — ${this._t('observer_mode_readonly')}</span>
                </div>
                ${SECTIONS.map(s => this._makeSectionHTML(s, bodies[s.id])).join('')}
            </div>`;

        // Bind section header clicks
        for (const s of SECTIONS) {
            const header = this.shadowRoot.querySelector(`[data-section="${s.id}"] .section-header`);
            if (header) {
                header.addEventListener('click', () => this._toggleSection(s.id));
                header.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this._toggleSection(s.id); }
                });
            }
        }
    }

    getCardSize() { return 12; }

    static getStubConfig() {
        return { entity_prefix: 'sensor.sem_' };
    }
}

SEMControlCard._instanceCount = 0;
semDefineCard('sem-control-card', SEMControlCard, {
    type: 'custom:sem-control-card',
    name: 'SEM Control Card',
    description: 'Consolidated control panel for Solar Energy Management',
    preview: false,
});

});
