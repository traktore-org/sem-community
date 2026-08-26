/**
 * SEM Battery Card — LitElement migration
 *
 * Battery hero card with SOC arc ring, session section, and daily/monthly chips.
 * Matches the Lumina-styled design from the original sem-battery-card.js exactly,
 * but uses Lit reactive rendering instead of innerHTML + manual DOM patching.
 *
 * Config:
 *   type: custom:sem-battery-card
 *   entity_prefix: sensor.sem_   # default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semGetCurrency, semCardSurfaceCSS, SEM_COLORS, semDefineCard } from '../base/sem-shared.js';
import { temperatureUnit } from '../util/temperature.js';

const DEFAULT_PREFIX = 'sensor.sem_';

const WATCHED_SUFFIXES = [
    'battery_soc', 'battery_power', 'battery_charge_power', 'battery_discharge_power',
    'battery_status', 'battery_health_score', 'battery_cycles_estimated',
    'battery_temperature', 'battery_session_type', 'battery_session_energy',
    'battery_session_solar_share', 'battery_session_duration', 'battery_session_avg_power',
    'battery_session_cost', 'battery_session_savings',
    'daily_battery_charge_energy', 'daily_battery_discharge_energy', 'daily_battery_savings',
    'flow_solar_to_battery_energy', 'flow_grid_to_battery_energy',
    'monthly_battery_charge_energy', 'monthly_battery_discharge_energy',
];

// Phase B of per-battery card mirror — same shape as the EV card
// ``CHARGER_COLORS`` palette: one stable colour per discovered
// battery, indexed by discovery order. Drawn from the SEM device
// palette so it visually rhymes with the EV side.
const BATTERY_COLORS = ['#4db6ac', '#FFB74D', '#BA68C8', '#64B5F6'];

class SEMBatteryCard extends SEMLitBase {
    constructor() {
        super();
        // Phase B: dynamic per-battery discovery. ``_batteries`` is
        // the list of short slugs found in ``hass.states`` (``b1``,
        // ``b2`` …); empty on single-battery installs so the card
        // renders the legacy hero-only layout unchanged.
        this._batteries = [];
        this._lastStateCount = 0;
    }

    static get watchedEntities() {
        return WATCHED_SUFFIXES.map(s => `${DEFAULT_PREFIX}${s}`);
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;
    }

    // Override hass setter: key-based comparison since entities are prefix-dynamic
    set hass(hass) {
        this._hass = hass;

        const lang = hass?.language;
        const hasLocalize = typeof semLocalize === 'function';
        let localeChanged = false;
        if (lang !== this._lang || (hasLocalize && !this._localizeReady)) {
            this._lang = lang;
            this._localizeReady = hasLocalize;
            localeChanged = true;
        }

        // Re-discover per-battery sensors when the entity count
        // changes. Single-battery installs find zero matches and the
        // render stays the legacy hero-only layout.
        const stateCount = Object.keys(hass.states).length;
        if (stateCount !== this._lastStateCount) {
            this._lastStateCount = stateCount;
            const batteries = [];
            for (const eid of Object.keys(hass.states)) {
                const m = eid.match(/^sensor\.sem_battery_(b\d+)_power$/);
                if (m) batteries.push(m[1]);
            }
            batteries.sort();
            this._batteries = batteries;
        }

        // Skip while frozen (optimistic update in progress)
        if (this._isFrozen() && !localeChanged) return;

        // Skip transient unavailable states caused by coordinator refresh —
        // async_request_refresh() briefly marks all entities unavailable before
        // new data arrives (~600ms). Rendering during this window shows "Idle".
        const statusState = hass?.states[`${this._prefix}battery_status`]?.state;
        if (statusState === 'unavailable' || statusState === 'unknown') {
            if (!localeChanged) return;
        }

        let key = WATCHED_SUFFIXES
            .map(s => hass?.states[`${this._prefix}${s}`]?.state || '')
            .join(',') + '|' + lang;

        // Per-battery reactivity — re-render whenever any per-battery
        // sensor value changes. No-op on single-battery installs
        // (``_batteries`` is empty).
        if (this._batteries.length) {
            key += '|' + this._batteries.map(bid => {
                const sensors = [
                    `battery_${bid}_power`, `battery_${bid}_soc`,
                    `battery_${bid}_status`, `battery_${bid}_capacity_kwh`,
                ].map(s => hass?.states[`${this._prefix}${s}`]?.state || '').join(':');
                // Per-battery control entities (#523) — re-render when the
                // mode / reserve change so the dropdown + stepper stay live.
                const ctrl = [
                    `select.sem_battery_${bid}_mode`,
                    `number.sem_battery_${bid}_reserve_soc`,
                ].map(e => hass?.states[e]?.state || '').join(':');
                return sensors + ':' + ctrl;
            }).join('|');
        } else {
            // Single-battery (#523): track the global mode + reserve so the
            // hero control stays live.
            key += '|' + [
                'select.sem_battery_mode',
                'number.sem_battery_reserve_soc',
            ].map(e => hass?.states[e]?.state || '').join(':');
        }

        if (key === this._lastBattKey && !localeChanged) return;
        this._lastBattKey = key;
        this._scheduleUpdate();
    }

    get hass() { return this._hass; }

    /* ── Prefix-scoped helpers ── */
    _val(suffix, fallback = 0) {
        return this._state(`${this._prefix}${suffix}`, fallback);
    }

    _valStr(suffix) {
        return this._stateStr(`${this._prefix}${suffix}`);
    }

    // (#820) One line: what charge pacing is doing right now. Reads the
    // pacing sensor's ACTION token (wrote/held/restored/idle/observer) and
    // cap — never the prose reason (translated 16 ways; rewording must not
    // change what renders). Absent sensor = feature absent = no line.
    _renderPacingLine() {
        const st = this._hass?.states?.['sensor.sem_battery_charge_pacing'];
        if (!st) return nothing;
        const act = st.state;                 // the action token IS the state
        if (!act || act === 'idle' || act === 'unavailable') return nothing;
        const capW = Number(st.attributes?.cap_w);
        const cap = Number.isFinite(capW) && capW > 0
            ? `${(capW / 1000).toFixed(1)} kW` : '';
        const key = act === 'observer' ? 'pacing_observer'
            : (act === 'restored' ? 'pacing_restored' : 'pacing_active');
        return html`
            <div class="tonight-row" style="opacity:.85">
                <span>${this._t('charge_pacing')}</span>
                <span>${this._t(key)}${cap ? ` · ${cap}` : ''}</span>
            </div>`;
    }

    _fmt(val, decimals = 1) {
        if (val == null || isNaN(val)) return '—';
        return val.toFixed(decimals);
    }

    // Show sub-90-minute sessions as plain minutes ("47 min"); switch
    // to "Hh Mm" once the user is past the point where the minute
    // count stops reading at a glance.
    _fmtDuration(min) {
        if (min == null || isNaN(min)) return '—';
        const m = Math.round(min);
        if (m < 90) return `${m} min`;
        const h = Math.floor(m / 60);
        const rem = m - h * 60;
        return rem === 0 ? `${h} h` : `${h} h ${rem} min`;
    }

    /* ── Per-battery section helpers (Phase B) ── */
    _batteryName(bid) {
        const e = this._hass?.states[`${this._prefix}battery_${bid}_power`];
        let name = bid.toUpperCase();
        if (e?.attributes?.friendly_name) {
            // Strip the SEM prefix + "Power" suffix that HA adds so the
            // section header reads cleanly ("B1" instead of "Battery
            // B1 Power"). Keeps the user's chosen battery name when
            // they override it via the entity registry.
            name = e.attributes.friendly_name
                .replace(/^SEM\s+/i, '')
                .replace(/\s+Power$/i, '');
        }
        return name;
    }

    _renderMiniSocRing(soc, color) {
        const socVal = soc != null ? Math.max(0, Math.min(100, soc)) : 0;
        const r = 22;
        const circumference = 2 * Math.PI * r;
        const offset = circumference * (1 - socVal / 100);
        return html`
            <svg viewBox="0 0 56 56" width="56" height="56"
                 style="display:block;">
                <circle cx="28" cy="28" r="${r}" fill="none"
                        stroke="rgba(255,255,255,0.12)" stroke-width="4" />
                <circle cx="28" cy="28" r="${r}" fill="none"
                        stroke="${color}" stroke-width="4"
                        stroke-linecap="round"
                        stroke-dasharray="${circumference.toFixed(1)}"
                        stroke-dashoffset="${offset.toFixed(1)}"
                        transform="rotate(-90 28 28)" />
                <text x="28" y="32" text-anchor="middle"
                      fill="${color}" font-size="13" font-weight="800"
                      font-family="'Segoe UI','Roboto',sans-serif"
                      style="paint-order:stroke;stroke:rgba(0,0,0,0.45);stroke-width:0.5px;">
                    ${soc != null ? Math.round(socVal) + '%' : '—'}
                </text>
            </svg>
        `;
    }

    // Vertical filled-battery glyph — the same visual language as the EV
    // card's SOC gauge (``_renderSocGauge``) so the two tabs read alike.
    // Fill colour follows the live flow (charge pink / discharge teal /
    // selling gold / idle grey) and gently pulses while power moves.
    _renderBatteryGlyph(soc, color, active) {
        const socVal = soc != null ? Math.max(0, Math.min(100, soc)) : 0;
        const socFill = Math.max(2, (socVal / 100) * 52);
        const anim = active ? 'socPulse 2s ease-in-out infinite' : 'none';
        return html`
            <svg viewBox="0 0 44 76" width="40" height="69">
                <rect x="14" y="0" width="16" height="5" rx="2" fill="rgba(255,255,255,0.15)"/>
                <rect x="6" y="4" width="32" height="60" rx="4"
                    fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="2"/>
                <rect x="9" y="${(7 + (52 - socFill)).toFixed(1)}" width="26"
                    height="${socFill.toFixed(1)}" rx="2"
                    fill="${color}" opacity="0.78" style="animation:${anim}"/>
                <text x="22" y="40" text-anchor="middle"
                    fill="white" font-size="13" font-weight="700"
                    font-family="'Segoe UI','Roboto',sans-serif" opacity="0.95">
                    ${soc != null ? Math.round(socVal) + '%' : '—'}
                </text>
            </svg>
        `;
    }

    _fmtHours(h) {
        if (h == null || !isFinite(h) || h <= 0) return '—';
        if (h < 1) return `${Math.round(h * 60)} min`;
        const hh = Math.floor(h);
        const mm = Math.round((h - hh) * 60);
        return mm === 0 ? `${hh} h` : `${hh} h ${mm} min`;
    }

    // Derived ETA — no per-battery energy sensor needed: charge time to
    // 100% or discharge time to empty from SOC × capacity ÷ current power.
    _batteryEta(soc, capacity, power) {
        if (soc == null || capacity <= 0 || Math.abs(power) < 50) return null;
        if (power > 50) {
            const kwhToFull = (100 - soc) / 100 * capacity;
            return { key: 'until_full', text: this._fmtHours(kwhToFull / (power / 1000)) };
        }
        const kwhToEmpty = soc / 100 * capacity;
        return { key: 'until_empty', text: this._fmtHours(kwhToEmpty / (Math.abs(power) / 1000)) };
    }

    // Mode dropdown + reserve stepper for a battery (#523). Shared by the
    // per-battery sections (multi-battery) and the fleet hero (single battery).
    // Renders nothing when the backend mode entity doesn't exist.
    _renderModeControls(modeEntityId, reserveEntityId) {
        const modeState = this._hass?.states[modeEntityId];
        if (!modeState) return nothing;
        const reserveState = this._hass?.states[reserveEntityId];
        const modeVal = modeState.state;
        const showReserve = reserveState
            && (modeVal === 'allow_arbitrage' || modeVal === 'force_discharge');
        // Decision-explanation line — what this mode makes SEM do (mirrors the
        // EV charger card's charge-mode hints). Translated per mode; falls back
        // to empty so an unknown/stale mode just hides the hint.
        const modeHint = this._t('battery_mode_hint_' + modeVal) || '';
        return html`
            <div class="battery-section-controls">
                <div class="bsc-row">
                    <span class="bsc-label">${this._t('mode')}</span>
                    <select class="bsc-select" .value=${modeVal}
                            @click=${(e) => e.stopPropagation()}
                            @change=${(e) => this._selectOption(modeEntityId, e.target.value)}>
                        ${(modeState.attributes.options || []).map(o => html`
                            <option value=${o} ?selected=${o === modeVal}>
                                ${this._t('battery_mode_' + o) || o}
                            </option>`)}
                    </select>
                </div>
                ${modeHint ? html`
                    <div class="bsc-hint">
                        <ha-icon icon="mdi:information-outline"></ha-icon>
                        <span>${modeHint}</span>
                    </div>
                ` : nothing}
                ${showReserve ? html`
                    <div class="bsc-row">
                        <span class="bsc-label">${this._t('reserve_soc')}</span>
                        <span class="bsc-stepper">
                            <button class="bsc-btn"
                                @click=${() => this._stepNumber(reserveEntityId, -1)}>−</button>
                            <span class="bsc-stepval">${Math.round(parseFloat(reserveState.state) || 0)}%</span>
                            <button class="bsc-btn"
                                @click=${() => this._stepNumber(reserveEntityId, 1)}>+</button>
                        </span>
                    </div>
                ` : nothing}
            </div>
        `;
    }

    _renderBatterySection(bid, idx) {
        const color = BATTERY_COLORS[idx % BATTERY_COLORS.length];
        const power = this._val(`battery_${bid}_power`, 0);
        const soc = this._val(`battery_${bid}_soc`, null);
        const statusRaw = (this._valStr(`battery_${bid}_status`) || 'idle').toLowerCase();
        const capacity = this._val(`battery_${bid}_capacity_kwh`, 0);
        const name = this._batteryName(bid);

        const isSelling = statusRaw === 'selling';
        const isCharging = !isSelling && (statusRaw === 'charging' || power > 50);
        const isDischarging = !isSelling && (statusRaw === 'discharging' || power < -50);
        const active = isCharging || isDischarging || isSelling;

        const statusKey = isSelling ? 'selling_to_grid'
            : isCharging ? 'charging'
            : isDischarging ? 'discharging' : 'idle';
        const flowColor = isSelling ? '#FCD170'
            : isCharging ? '#f06292'
            : isDischarging ? '#4db6ac' : '#999';

        // Derived metrics (no extra backend sensors): stored energy and ETA.
        const stored = (soc != null && capacity > 0) ? (soc / 100) * capacity : null;
        const eta = this._batteryEta(soc, capacity, power);

        return html`
            <div class="battery-section">
                <div class="battery-section-header">
                    <div class="battery-dot" style="background:${color}"></div>
                    <span class="battery-section-name">${name}</span>
                    <span class="battery-section-status"
                          style="color:${flowColor}">
                        ${this._t(statusKey)}
                    </span>
                </div>
                <div class="battery-section-body">
                    <div class="battery-section-glyph">
                        ${this._renderBatteryGlyph(soc, flowColor, active)}
                        <span class="battery-section-soc-label">SOC</span>
                    </div>
                    <div class="battery-section-metrics">
                        <div class="bs-row">
                            <span class="bs-label">${this._t('power')}</span>
                            <span class="bs-val"
                                  style="color:${power > 50 || power < -50 ? flowColor : ''}">
                                ${semFormatPower(power)}
                            </span>
                        </div>
                        ${stored != null ? html`
                            <div class="bs-row">
                                <span class="bs-label">${this._t('stored')}</span>
                                <span class="bs-val">${this._fmt(stored, 1)} kWh</span>
                            </div>
                        ` : nothing}
                        ${capacity > 0 ? html`
                            <div class="bs-row">
                                <span class="bs-label">${this._t('capacity')}</span>
                                <span class="bs-val">${this._fmt(capacity, 1)} kWh</span>
                            </div>
                        ` : nothing}
                        ${eta ? html`
                            <div class="bs-row">
                                <span class="bs-label">${this._t(eta.key)}</span>
                                <span class="bs-val">${eta.text}</span>
                            </div>
                        ` : nothing}
                    </div>
                </div>
                ${this._renderModeControls(
                    `select.sem_battery_${bid}_mode`,
                    `number.sem_battery_${bid}_reserve_soc`,
                )}
            </div>
        `;
    }

    /* ── Render ── */
    /* ── (#778) Tonight — the forecast budget, in the three states a person
       has to be able to tell apart.

       Every fresh install sits in "learning" for at least five nights, and
       today that state renders as a bare 0.0 beside five sensors reading
       "Unavailable" — the same word HA shows for a dead integration. The
       whole explanation already lives on ONE entity's attributes, so this
       reads one entity and switches on the published ``phase`` token. It
       never matches on the reason prose: that text is translated into
       sixteen languages and rewording it must not change what renders. ── */
    _renderTonight(T) {
        const eid = `${this._prefix}battery_spendable_kwh`;
        const ent = this._hass?.states[eid];
        if (!ent) return nothing;          // pre-2.1 install — nothing to say
        const a = this._stateAttrs(eid);
        const phase = a.phase;
        if (!phase) return nothing;        // evidence not published yet

        const num = (v) => (v == null || v === '' || isNaN(parseFloat(v)))
            ? null : parseFloat(v);

        const spendable = num(ent.state);
        const floor = num(a.dynamic_floor_pct);
        const nights = num(a.nights_sealed) ?? 0;
        const needed = num(a.nights_required) ?? 5;
        const days = num(a.forecast_days_d1) ?? 0;
        const daysNeeded = num(a.forecast_days_required) ?? 7;

        const PALETTE = {
            learning: T.warning || '#e0a943',
            holding: '#5bc8d8',
            spending: '#4db6ac',
        };
        const accent = PALETTE[phase] || (T.textSec || '#888');

        // The headline differs per phase because the three states are three
        // different sentences, not one sentence with a different number.
        let headline, unit;
        if (phase === 'learning') {
            headline = `${Math.min(nights, needed)}`;
            unit = `${this._t('of')} ${needed} ${this._t('nights')}`;
        } else {
            headline = this._fmt(spendable ?? 0, 1);
            unit = `kWh ${this._t('spendable_tonight')}`;
        }

        // The working, in the order a person would check it. Only rows whose
        // value actually exists — a dash teaches nobody anything.
        const rows = [];
        if (phase === 'learning') {
            rows.push([this._t('nights_recorded'), `${nights}`]);
            rows.push([this._t('forecast_days_settled'), `${days} / ${daysNeeded}`]);
        } else {
            const need = num(a.overnight_need_kwh);
            const refill = num(a.expected_refill_kwh);
            if (need != null) rows.push([this._t('overnight_need'), `${this._fmt(need, 1)} kWh`]);
            if (refill != null) rows.push([this._t('expected_refill'), `${this._fmt(refill, 1)} kWh`]);
            if (floor != null) rows.push([this._t('floor_tonight'), `${Math.round(floor)}%`]);
        }

        const pips = [];
        for (let i = 0; i < needed; i++) pips.push(i < nights);

        return html`
            <div class="tonight" style="--tn-accent:${accent}">
                <div class="tonight-head">
                    <span class="tonight-title">${this._t('tonight')}</span>
                    <span class="tonight-pill">${this._t(`planning_phase_${phase}`)}</span>
                </div>
                <div class="tonight-big ${phase === 'spending' ? 'tn-live' : 'tn-dim'}">
                    ${headline}<span class="tonight-unit">${unit}</span>
                </div>
                ${phase === 'learning' ? html`
                    <div class="tonight-prog">
                        ${pips.map((on) => html`<i class="${on ? 'on' : ''}"></i>`)}
                    </div>` : nothing}
                <div class="tonight-why">${a.why || ''}</div>
                ${this._renderPacingLine()}
                ${rows.length ? html`
                    <div class="tonight-work">
                        ${rows.map(([k, v]) => html`
                            <div class="tonight-row"><span>${k}</span><span>${v}</span></div>`)}
                    </div>` : nothing}
            </div>
        `;
    }

    /* ── (#778) The evidence strip — why the number above deserves belief.

       Three cells, and the important design point is that "still learning"
       and "no source publishes this" are DIFFERENT answers. Both surface as
       an empty sensor today, but only one of them resolves by waiting: on
       the .175 rig Forecast.Solar exposes day-2 per string only, so that
       horizon never fills, and a user staring at a permanently blank figure
       deserves to be told which of the two they are looking at. ── */
    _renderEvidence(T) {
        const eid = `${this._prefix}battery_spendable_kwh`;
        const a = this._stateAttrs(eid);
        if (!a.phase) return nothing;

        const num = (v) => (v == null || v === '' || isNaN(parseFloat(v)))
            ? null : parseFloat(v);
        const pct = (v) => `${Math.round(v * 100)}%`;

        const daysNeeded = num(a.forecast_days_required) ?? 7;
        const nightsNeeded = num(a.nights_required) ?? 5;

        const horizon = (trustKey, daysKey, availKey, label) => {
            const trust = num(a[trustKey]);
            const days = num(a[daysKey]) ?? 0;
            const available = a[availKey];
            if (available === false) {
                return { label, value: this._t('no_source'),
                         sub: this._t('no_source_hint'), dim: true };
            }
            if (trust == null) {
                return { label, value: this._t('learning'),
                         sub: `${days} / ${daysNeeded} ${this._t('days_settled')}`, dim: true };
            }
            return { label, value: pct(trust),
                     sub: `${days} ${this._t('days_settled')}`, dim: false };
        };

        const cells = [
            horizon('forecast_trust_d1', 'forecast_days_d1', 'forecast_d1_available',
                    `${this._t('forecast_accuracy')} · 1${this._t('day_short')}`),
            horizon('forecast_trust_d2', 'forecast_days_d2', 'forecast_d2_available',
                    `${this._t('forecast_accuracy')} · 2${this._t('day_short')}`),
        ];

        const cap = num(a.measured_capacity_kwh);
        const samples = num(a.capacity_samples) ?? 0;
        const drift = num(a.capacity_drift_pct);
        const nameplate = num(a.nameplate_capacity_kwh);
        if (cap == null) {
            cells.push({
                label: this._t('measured_pack_size'), value: this._t('learning'),
                sub: `${samples} / ${nightsNeeded} ${this._t('nights')}` +
                     (nameplate != null ? ` · ${this._fmt(nameplate, 1)} kWh ${this._t('nameplate')}` : ''),
                dim: true,
            });
        } else {
            cells.push({
                label: this._t('measured_pack_size'),
                value: `${this._fmt(cap, 1)} kWh`,
                sub: drift == null ? `${samples} ${this._t('nights')}`
                     : `${drift > 0 ? '+' : ''}${this._fmt(drift, 1)}% ${this._t('vs_nameplate')}`,
                dim: false,
            });
        }

        return html`
            <div class="evidence">
                ${cells.map((c) => html`
                    <div class="ev-cell">
                        <div class="ev-key">${c.label}</div>
                        <div class="ev-val ${c.dim ? 'ev-dim' : ''}">${c.value}</div>
                        <div class="ev-sub">${c.sub}</div>
                    </div>`)}
            </div>
        `;
    }

    render() {
        if (!this._hass || !this._config) return nothing;

        const T = this._theme();
        const circumference = 2 * Math.PI * 42;
        const circumferenceFixed = circumference.toFixed(1);

        // State reads
        const soc = this._val('battery_soc', 0);
        const power = this._val('battery_power', 0);
        const chargePower = this._val('battery_charge_power', 0);
        const dischargePower = this._val('battery_discharge_power', 0);
        // Lowercase — the sensor publishes title-cased values ("Selling",
        // "Charging"); the string comparisons below expect lowercase.
        const statusRaw = (this._valStr('battery_status') || '').toLowerCase();
        const health = this._val('battery_health_score', 0);
        const cycles = this._val('battery_cycles_estimated', 0);
        const dailyCharge = this._val('daily_battery_charge_energy', 0);
        const dailyDischarge = this._val('daily_battery_discharge_energy', 0);
        const dailySavings = this._val('daily_battery_savings', 0);
        const monthCharge = this._val('monthly_battery_charge_energy', 0);
        const monthDischarge = this._val('monthly_battery_discharge_energy', 0);
        const solarToBatt = this._val('flow_solar_to_battery_energy', 0);
        const currency = semGetCurrency(this._hass);

        // Temperature — may be unavailable
        const tempEntity = this._hass?.states[`${this._prefix}battery_temperature`];
        const temp = (tempEntity && tempEntity.state !== 'unavailable' && tempEntity.state !== 'unknown')
            ? parseFloat(tempEntity.state) : null;
        // #727 — label with HA's actual display unit (°F on US installs, where the
        // °C-native sensor is converted), not a hardcoded °C that mislabels it.
        const tempUnit = temperatureUnit(tempEntity);

        // Charge state. #523: "selling" = the scheduler is exporting the
        // battery to the grid for arbitrage — a distinct gold state.
        const isSelling = statusRaw === 'selling';
        const isCharging = !isSelling && (statusRaw === 'charging' || chargePower > 10);
        const isDischarging = !isSelling && (statusRaw === 'discharging' || dischargePower > 10);
        const exportEnt = this._hass?.states['sensor.sem_tariff_current_export_rate'];
        const exportRate = (exportEnt && exportEnt.state !== 'unavailable' && exportEnt.state !== 'unknown')
            ? parseFloat(exportEnt.state) : null;
        const SELL = '#FCD170';
        const statusText = isSelling ? this._t('selling_to_grid')
            : isCharging ? this._t('charging')
            : isDischarging ? this._t('discharging')
            : this._t('idle');
        const arcColor = isSelling ? SELL : (isCharging ? '#f06292' : '#4db6ac');
        const statusColor = isSelling ? SELL
            : isCharging ? '#f06292' : isDischarging ? '#4db6ac' : (T.textSec || '#888');
        const glowOpacity = (isCharging || isDischarging || isSelling) ? '0.5' : '0.2';
        const arcAnim = (isCharging || isDischarging || isSelling) ? 'socPulse 2s ease-in-out infinite' : 'none';

        // SOC arc
        const pct = Math.min(Math.max(soc / 100, 0), 1);
        const arcOffset = (circumference * (1 - pct)).toFixed(1);

        // Solar attribution
        const solarPct = dailyCharge > 0 ? Math.round(solarToBatt / dailyCharge * 100) : 0;

        // Session
        const sessionType = this._valStr('battery_session_type');
        const sessionActive = sessionType === 'charge' || sessionType === 'discharge';
        const isChargeSess = sessionType === 'charge';
        const sEnergy = sessionActive ? this._val('battery_session_energy', 0) : 0;
        const sDuration = sessionActive ? this._val('battery_session_duration', 0) : 0;
        const sAvgPower = sessionActive ? this._val('battery_session_avg_power', 0) : 0;
        const sSolarShare = sessionActive ? this._val('battery_session_solar_share', 0) : 0;
        const sCost = sessionActive ? this._val('battery_session_cost', 0) : 0;
        const sSavings = sessionActive ? this._val('battery_session_savings', 0) : 0;
        const sessColor = isChargeSess ? '#f06292' : '#4db6ac';

        const dotCol = T.dotColor || 'rgba(128,128,128,0.05)';
        const surfaceCol = T.surface || 'rgba(255,255,255,0.06)';
        const surfBorder = T.surfaceBorder || 'rgba(255,255,255,0.05)';
        const surfHover = T.surfaceHover || 'rgba(255,255,255,0.12)';
        const textSecCol = T.textSec || '#999';
        const chipLblCol = T.textTertiary || '#888';

        return html`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${semCardSurfaceCSS(T, SEM_COLORS.battery)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                }
                .glow-svg { position: absolute; width: 0; height: 0; }
                .hero { display: flex; align-items: center; gap: 20px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 12px; } }
                .battery-ring { position: relative; width: 100px; height: 100px; flex-shrink: 0; }
                .battery-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
                .ring-bg { fill: none; stroke: rgba(77,182,172,0.12); stroke-width: 5; }
                .soc-arc {
                    fill: none; stroke-width: 5; stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#batt-glow);
                }
                .glow-ring {
                    fill: none; stroke-width: 8; opacity: 0.2;
                    filter: url(#batt-glow-soft);
                    animation: glowPulse 3s ease-in-out infinite;
                }
                @keyframes glowPulse { 0%,100% { opacity: 0.2; } 50% { opacity: 0.08; } }
                @keyframes socPulse  { 0%,100% { opacity: 1; }   50% { opacity: 0.6; } }
                .ring-center {
                    position: absolute; top: 50%; left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center; pointer-events: none;
                }
                .battery-icon { display: block; margin: 0 auto 1px; }
                .soc-value {
                    font-size: 14px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    text-shadow: 0 0 8px rgba(77,182,172,0.3); line-height: 1;
                }
                .metrics-col { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0; gap: 8px;
                }
                .metric-label { font-size: 12px; color: var(--secondary-text-color, ${textSecCol}); font-weight: 500; }
                .metric-val { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; color: #4db6ac; }
                .chips { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
                .chip {
                    flex: 1; min-width: 80px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 10px; padding: 8px 10px; text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .chip:hover { border-color: var(--divider-color, ${surfHover}); }
                .chip-label {
                    font-size: 11px; color: var(--secondary-text-color, ${chipLblCol});
                    font-weight: 500; letter-spacing: 0.3px; margin-bottom: 3px;
                }
                .chip-value { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
                .c-charge { color: #f06292; }
                .c-discharge { color: #4db6ac; }
                .c-savings { color: #8DC892; }
                .chip-src { font-size: 10px; color: var(--secondary-text-color, ${chipLblCol}); margin-top: 1px; }
                .session-section {
                    margin-top: 14px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 10px;
                }
                .sess-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
                .sess-title {
                    font-size: 12px; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }
                .sess-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; }
                .sess-item-label { font-size: 11px; color: var(--secondary-text-color, ${chipLblCol}); }
                .sess-item-value {
                    font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                }
                .monthly-section { display: flex; gap: 8px; margin-top: 10px; }

                /* ── Per-battery sections (Phase B). Same structural
                       shape as the EV card's per-charger sections so
                       a user who already knows the EV tab reads the
                       battery tab without re-learning the layout. ── */
                /* (#778) Tonight — the forecast budget panel. Accent is set
                   per phase from JS so the three states read at a glance
                   without three copies of this block. */
                .tonight {
                    background: rgba(255,255,255,.03);
                    border: 1px solid rgba(255,255,255,.08);
                    border-left: 3px solid var(--tn-accent, #4db6ac);
                    border-radius: 12px;
                    padding: 14px 16px 15px;
                    margin: 4px 0 14px;
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                }
                .tonight-head {
                    display: flex;
                    align-items: baseline;
                    justify-content: space-between;
                    gap: 12px;
                }
                .tonight-title {
                    font-size: 14px;
                    font-weight: 500;
                    color: var(--sem-text, #e8eeed);
                }
                .tonight-pill {
                    font-size: 10px;
                    letter-spacing: .08em;
                    text-transform: uppercase;
                    padding: 3px 8px;
                    border-radius: 20px;
                    border: 1px solid var(--tn-accent, #4db6ac);
                    color: var(--tn-accent, #4db6ac);
                    white-space: nowrap;
                }
                .tonight-big {
                    font-size: 32px;
                    font-weight: 300;
                    line-height: 1;
                    font-variant-numeric: tabular-nums;
                    display: flex;
                    align-items: baseline;
                    gap: 6px;
                    flex-wrap: wrap;
                }
                .tonight-big.tn-live { color: var(--tn-accent, #4db6ac); }
                .tonight-big.tn-dim { color: var(--sem-text-sec, #9bb0ab); }
                .tonight-unit {
                    font-size: 13px;
                    font-weight: 400;
                    color: var(--sem-text-sec, #9bb0ab);
                }
                .tonight-prog { display: flex; gap: 4px; }
                .tonight-prog i {
                    flex: 1;
                    height: 5px;
                    border-radius: 3px;
                    background: rgba(255,255,255,.13);
                }
                .tonight-prog i.on { background: var(--tn-accent, #e0a943); }
                .tonight-why {
                    font-size: 12.5px;
                    line-height: 1.45;
                    color: var(--sem-text-sec, #9bb0ab);
                }
                .tonight-work {
                    display: flex;
                    flex-direction: column;
                    gap: 4px;
                    border-top: 1px solid rgba(255,255,255,.08);
                    padding-top: 9px;
                }
                .tonight-row {
                    display: flex;
                    justify-content: space-between;
                    gap: 16px;
                    font-size: 11.5px;
                    color: var(--sem-text-sec, #8fa3a0);
                }
                .tonight-row span:last-child {
                    font-variant-numeric: tabular-nums;
                    color: var(--sem-text, #cfdad7);
                }

                /* (#778) the evidence strip */
                .evidence {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 8px;
                    margin: 0 0 14px;
                }
                .ev-cell {
                    background: rgba(255,255,255,.03);
                    border: 1px solid rgba(255,255,255,.07);
                    border-radius: 10px;
                    padding: 10px 12px;
                    display: flex;
                    flex-direction: column;
                    gap: 3px;
                }
                .ev-key {
                    font-size: 10px;
                    letter-spacing: .07em;
                    text-transform: uppercase;
                    color: var(--sem-text-sec, #8fa3a0);
                }
                .ev-val {
                    font-size: 19px;
                    font-weight: 300;
                    font-variant-numeric: tabular-nums;
                    color: var(--sem-text, #e8eeed);
                }
                .ev-val.ev-dim { font-size: 15px; color: var(--sem-text-sec, #9bb0ab); }
                .ev-sub {
                    font-size: 11px;
                    line-height: 1.35;
                    color: var(--sem-text-sec, #8fa3a0);
                }

                .battery-sections {
                    margin-top: 16px;
                    display: flex; flex-direction: column;
                    gap: 12px;
                }
                .battery-section {
                    background: ${surfaceCol};
                    border: 1px solid ${surfBorder};
                    border-radius: 12px;
                    padding: 12px 14px;
                }
                .battery-section-header {
                    display: flex; align-items: center; gap: 8px;
                    margin-bottom: 10px;
                }
                .battery-dot {
                    width: 8px; height: 8px;
                    border-radius: 50%;
                    flex-shrink: 0;
                }
                .battery-section-name {
                    flex: 1; font-weight: 600; font-size: 0.95em;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                }
                .battery-section-status {
                    font-size: 0.8em; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.05em;
                }
                .battery-section-body {
                    display: flex; align-items: center; gap: 12px;
                }
                .battery-section-ring {
                    flex-shrink: 0; width: 56px; text-align: center;
                }
                .battery-section-glyph {
                    flex-shrink: 0; width: 44px; text-align: center;
                }
                .battery-section-soc-label {
                    display: block;
                    font-size: 10px; color: ${textSecCol};
                    margin-top: 2px;
                    text-transform: uppercase; letter-spacing: 0.05em;
                }
                .battery-section-metrics {
                    flex: 1;
                    display: flex; flex-direction: column; gap: 2px;
                }
                .bs-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 2px 0;
                }
                .bs-label {
                    font-size: 11px; color: ${textSecCol};
                    font-weight: 500;
                }
                .bs-val {
                    font-size: 12px; font-weight: 600;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                    font-variant-numeric: tabular-nums;
                }
                /* Per-battery controls (#523) — mode select + reserve stepper */
                .battery-section-controls {
                    margin-top: 10px; padding-top: 10px;
                    border-top: 1px solid ${surfBorder};
                    display: flex; flex-direction: column; gap: 8px;
                }
                .bsc-row {
                    display: flex; align-items: center; justify-content: space-between;
                    gap: 8px;
                }
                .bsc-hint {
                    display: flex; align-items: flex-start; gap: 5px;
                    font-size: 11px; line-height: 1.35;
                    color: ${textSecCol};
                    margin: -2px 0 1px 0;
                    opacity: 0.92;
                }
                .bsc-hint ha-icon {
                    --mdc-icon-size: 13px;
                    flex: 0 0 auto; margin-top: 1px; opacity: 0.8;
                }
                .bsc-label {
                    font-size: 12px; color: ${textSecCol}; font-weight: 500;
                }
                .bsc-select {
                    background: ${surfaceCol};
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                    border: 1px solid ${surfBorder};
                    border-radius: 8px; padding: 5px 8px; font-size: 12px;
                    font-weight: 600; cursor: pointer; min-width: 150px;
                }
                .bsc-stepper { display: flex; align-items: center; gap: 8px; }
                .bsc-btn {
                    width: 24px; height: 24px; border-radius: 6px;
                    background: ${surfaceCol}; border: 1px solid ${surfBorder};
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                    font-size: 15px; font-weight: 700; cursor: pointer; line-height: 1;
                }
                .bsc-btn:hover { border-color: ${surfHover}; }
                .bsc-stepval {
                    min-width: 38px; text-align: center; font-size: 13px;
                    font-weight: 700; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                }
                /* Phase B mobile breakpoint — single column from the
                   ring + metrics layout collapses to stacked at
                   < 480 px (mirrors the sem-solar-card pattern). */
                @media (max-width: 480px) {
                    .battery-section-body {
                        flex-direction: column;
                        align-items: stretch;
                    }
                    .battery-section-ring { margin: 0 auto; }
                    .battery-section-glyph { margin: 0 auto; }
                }
                .month-chip {
                    flex: 1; text-align: center; padding: 6px 8px;
                    background: var(--secondary-background-color, ${surfaceCol});
                    border: 1px solid var(--divider-color, ${surfBorder});
                    border-radius: 8px;
                }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="batt-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood flood-color="${arcColor}" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="batt-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">
                    <div class="hero">
                        <div class="battery-ring">
                            <svg viewBox="0 0 100 100">
                                <circle class="glow-ring" cx="50" cy="50" r="42"
                                    style="stroke:${arcColor};opacity:${glowOpacity}"/>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="soc-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${circumferenceFixed}"
                                    style="stroke-dashoffset:${arcOffset};stroke:${arcColor};animation:${arcAnim}"/>
                            </svg>
                            <div class="ring-center">
                                <!-- #523/#524 follow-up: filled SOC-level
                                     battery glyph matching the system card
                                     (was a flat outline). Fills bottom-up to
                                     SOC, tints with the arc colour, and shows a
                                     charging bolt. -->
                                <svg class="battery-icon" width="18" height="26" viewBox="0 0 20 30">
                                    <rect x="6" y="0" width="8" height="4" rx="1.5"
                                        fill="${arcColor}" opacity="0.7"/>
                                    <rect x="2" y="4" width="16" height="26" rx="3"
                                        fill="rgba(0,0,0,0.30)" stroke="${arcColor}"
                                        stroke-width="1.6" opacity="0.9"/>
                                    <rect x="4" y="${(28 - 22 * pct).toFixed(1)}" width="12"
                                        height="${(22 * pct).toFixed(1)}" rx="1.5"
                                        fill="${arcColor}" opacity="0.55"/>
                                    <path d="M11,9.5 L6.5,18.5 L9.5,18.5 L8.5,24.5 L13.5,15 L10.5,15 Z"
                                        fill="#FCD170" opacity="${isCharging ? 0.95 : 0}"/>
                                </svg>
                                <div class="soc-value" style="color:${arcColor}">
                                    ${soc.toFixed(0)}%
                                </div>
                            </div>
                        </div>

                        <div class="metrics-col">
                            <div class="metric-row">
                                <span class="metric-label">${this._t('soc')}</span>
                                <span class="metric-val">${this._fmt(soc, 1)}%</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('power')}</span>
                                <span class="metric-val">${semFormatPower(power)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('status')}</span>
                                <span class="metric-val" style="color:${statusColor}">${statusText}</span>
                            </div>
                            ${isSelling && exportRate != null ? html`
                            <div class="metric-row">
                                <span class="metric-label">${this._t('export_rate')}</span>
                                <span class="metric-val" style="color:${SELL}">${this._fmt(exportRate, 3)} ${currency}/kWh</span>
                            </div>
                            ` : nothing}
                            <div class="metric-row">
                                <span class="metric-label">${this._t('health')}</span>
                                <span class="metric-val">${this._fmt(health, 1)}%</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t('cycles')}</span>
                                <span class="metric-val">${this._fmt(cycles, 1)}</span>
                            </div>
                            ${this._batteries.length > 1 ? '' : html`
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('temperature')}</span>
                                    <span class="metric-val">
                                        ${temp != null ? `${this._fmt(temp, 1)} ${tempUnit}` : '—'}
                                    </span>
                                </div>
                            `}
                            <!-- #404: On multi-battery installs (length > 1)
                                 the fleet-tile temperature is hidden because
                                 each battery has its own temperature shown in
                                 its per-battery section. Per RienduPre's UX
                                 confirmation 2026-06-04. Single-battery
                                 installs (today's PROD majority) unchanged. -->
                        </div>
                    </div>

                    ${this._batteries.length >= 1 ? html`
                        <div class="battery-sections">
                            ${this._batteries.map(
                                (bid, idx) => this._renderBatterySection(bid, idx),
                            )}
                        </div>
                    ` : html`
                        <!-- Single-battery install (#523): global mode control
                             on the hero, no per-battery section. -->
                        ${this._renderModeControls(
                            'select.sem_battery_mode',
                            'number.sem_battery_reserve_soc',
                        )}
                    `}

                    <div class="session-section">
                        <div class="sess-header">
                            <ha-icon icon="mdi:battery-sync"
                                style="--mdc-icon-size:14px;color:${sessionActive ? sessColor : T.textSec}">
                            </ha-icon>
                            <span class="sess-title" style="color:${sessionActive ? sessColor : T.textSec}">
                                ${this._t('current_session')}
                            </span>
                        </div>
                        ${sessionActive ? html`
                        <div class="sess-grid">
                            <div>
                                <div class="sess-item-label">${this._t('energy')}</div>
                                <div class="sess-item-value">${this._fmt(sEnergy, 2)} kWh</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('duration')}</div>
                                <div class="sess-item-value">${this._fmtDuration(sDuration)}</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('avg_power')}</div>
                                <div class="sess-item-value">${semFormatPower(sAvgPower)}</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('source')}</div>
                                <div class="sess-item-value">
                                    ${isChargeSess ? `${this._t('solar')}: ${this._fmt(sSolarShare, 0)}%` : ''}
                                </div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t('cost')}</div>
                                <div class="sess-item-value">
                                    ${isChargeSess
                                        ? `${this._fmt(sCost, 2)} ${currency}`
                                        : `${this._t('saved')} ${this._fmt(sSavings, 2)} ${currency}`}
                                </div>
                            </div>
                        </div>
                        ` : html``}
                    </div>

                    ${this._renderTonight(T)}
                    ${this._renderEvidence(T)}

                    <div class="chips">
                        <div class="chip">
                            <div class="chip-label">${this._t('charge_today')}</div>
                            <div class="chip-value c-charge">${this._fmt(dailyCharge, 2)} kWh</div>
                            <div class="chip-src">
                                ${solarPct > 0 ? `${solarPct}% ${this._t('solar')}` : ''}
                            </div>
                        </div>
                        <div class="chip">
                            <div class="chip-label">${this._t('discharge_today')}</div>
                            <div class="chip-value c-discharge">${this._fmt(dailyDischarge, 2)} kWh</div>
                        </div>
                        <div class="chip">
                            <div class="chip-label">${this._t('savings_today')}</div>
                            <div class="chip-value c-savings">
                                ${this._fmt(dailySavings, 2)} ${currency}
                            </div>
                        </div>
                    </div>

                    <div class="monthly-section">
                        <div class="month-chip">
                            <div class="chip-label">
                                ${this._t('monthly')} ${this._t('charge')}
                            </div>
                            <div class="chip-value c-charge">${this._fmt(monthCharge, 1)} kWh</div>
                        </div>
                        <div class="month-chip">
                            <div class="chip-label">
                                ${this._t('monthly')} ${this._t('discharge')}
                            </div>
                            <div class="chip-value c-discharge">${this._fmt(monthDischarge, 1)} kWh</div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 3; }

    static getStubConfig() { return {}; }
}

semDefineCard('sem-battery-card', SEMBatteryCard, {
    type: 'sem-battery-card',
    name: 'SEM Battery',
    description: 'Lumina-styled battery hero card with SOC arc ring and key metrics',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-battery-card',
});
