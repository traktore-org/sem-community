/**
 * SEM System Diagram Card — Pure-Reactive (Lit) Rewrite
 *
 * Power flow visualization with inline SVG illustrations for each energy
 * component. Pure reactive: every value flows through render() — no
 * imperative getElementById / textContent / setAttribute on lit-bound nodes.
 *
 * Layout:
 *   Desktop (>=500px): viewBox 0 0 700 510 — left-to-right flow
 *   Compact (<500px):  viewBox 0 0 400 680 — vertical stack
 *
 * Reactivity model:
 *   - set hass() — entity-state dirty check + counter-target update + rAF tick
 *   - rAF tick — eased numeric counters → batched reactive-property write
 *   - render() — reads state inline each cycle (matches sem-battery-card.js
 *     and the other 21 cards in the bundle)
 *   - updated() — single isolated DOM-measurement bit for the sun-arc
 *     position (getPointAtLength is the canonical Lit escape hatch);
 *     dirty-guarded to break the loop
 *
 * Fixes #457 — eliminates the lit-html / imperative DOM conflict that
 * crashed requestUpdate() and blocked #453.
 */

import { SEMLitBase, html, css, svg, nothing } from '../base/sem-lit-base.js';
import {
    semFormatPower, semFormatTime, semCalcDuration, semDefineCard, SEM_DEVICE_COLORS,
    semDiscoverPVStrings, semPVStringsCSS, semPVStringStatesKey,
} from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

// Suffixes the diagram card reads. Used both for static watchedEntities
// (informational; set hass override does prefix-aware dirty check) and the
// runtime per-prefix key build.
const WATCHED_SUFFIXES = [
    'solar_power', 'battery_power', 'grid_import_power', 'grid_export_power',
    'ev_power', 'battery_soc', 'battery_temperature', 'charging_state',
    'home_consumption_power',  // card reads the held sensor, not a residual
    'daily_solar_energy', 'daily_battery_charge_energy', 'daily_battery_discharge_energy',
    'daily_ev_energy', 'daily_home_energy', 'daily_grid_import_energy', 'daily_grid_export_energy',
    'forecast_today_kwh', 'controllable_devices_count',
];

class SEMSystemDiagramCard extends SEMLitBase {
    // Reactive properties exist ONLY for values driven by the rAF counter tick
    // and the sun-arc measure loop. Everything else flows through render()
    // reading from this._hass inline (the bundle's standard pattern).
    static properties = {
        _solarDisp:     { state: true },
        _battDisp:      { state: true },
        _homeDisp:      { state: true },
        _evDisp:        { state: true },
        _gridDisp:      { state: true },
        _gridDispMode:  { state: true },
        _sunTransform:  { state: true },
        _moonTransform: { state: true },
        _sunPowerX:     { state: true },
        _sunPowerY:     { state: true },
        _sunPtX:        { state: true },
        _sunPtY:        { state: true },
    };

    static get watchedEntities() {
        return WATCHED_SUFFIXES.map(s => `${DEFAULT_PREFIX}${s}`);
    }

    constructor() {
        super();
        this._prefix = DEFAULT_PREFIX;
        this._mode = 'prefix';      // #455
        this._entities = null;      // #455
        this._compact = false;
        this._visible = true;
        this._resizeObserver = null;
        this._intersectionObserver = null;
        this._resizeTimeout = null;
        this._counterRaf = null;
        this._targets = null;
        this._lastDiagKey = '';
        this._sunSparkProps = null;
        this._sunSparkSig = '';
    }

    setConfig(config) {
        super.setConfig(config);
        // #455 — parity with sem-flow-card: explicit ``entities:`` map
        // points the diagram at arbitrary HA entities; ``entity_prefix``
        // stays the default/fallback and wins when both are set (same
        // precedence as sem-flow-card.setConfig).
        if (config.entities && !config.entity_prefix) {
            this._mode = 'entities';
            this._entities = config.entities;
        } else {
            this._mode = 'prefix';
            this._entities = null;
        }
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;
    }

    /** Resolve a logical suffix to an entity id (#455).
     *
     * Prefix mode: ``<entity_prefix><suffix>`` (pre-#455 behaviour).
     * Entities mode: the sem-flow-card schema map — unmapped keys
     * return null and read as 0 / empty so the matching diagram
     * element degrades gracefully instead of pointing at a phantom
     * ``sensor.sem_*`` id.
     */
    _eid(suffix) {
        if (this._mode !== 'entities') return `${this._prefix}${suffix}`;
        const e = this._entities;
        if (!e) return null;
        const map = {
            solar_power: e.solar?.entity,
            battery_power: e.battery?.entity,
            battery_charge_power: e.battery?.charge,
            battery_discharge_power: e.battery?.discharge,
            grid_power: e.grid?.entity,
            grid_import_power: e.grid?.consumption,
            grid_export_power: e.grid?.production,
            ev_power: e.ev?.entity || e.individual?.[0]?.entity,
            battery_soc: e.battery?.state_of_charge,
            battery_temperature: e.battery?.temperature,
            home_consumption_power: e.home?.entity,
            charging_state: e.inverter?.entity,
            daily_solar_energy: e.solar?.daily_energy,
            daily_ev_energy: e.ev?.daily_energy || e.individual?.[0]?.daily_energy,
            daily_grid_import_energy: e.grid?.daily_import_energy,
            daily_grid_export_energy: e.grid?.daily_export_energy,
            daily_battery_charge_energy: e.battery?.daily_charge_energy,
            daily_battery_discharge_energy: e.battery?.daily_discharge_energy,
            daily_home_energy: e.home?.daily_energy,
            autarky_rate: e.home?.autarky,
            self_consumption_rate: e.home?.self_consumption,
            forecast_today_kwh: e.solar?.forecast_remaining,
            controllable_devices_count: e.devices?.count_entity,
        };
        return map[suffix] || null;
    }

    // ── #455 flow-value helpers — entities-mode semantics mirror
    //    sem-flow-card (split battery, combined grid, reverse/invert
    //    flags). Prefix mode passes through unchanged. ──
    _flowSolar() {
        const s = this._val('solar_power');
        return this._entities?.solar?.reverse ? -s : s;
    }

    _flowBattery() {
        const e = this._entities;
        if (e?.battery?.charge || e?.battery?.discharge) {
            return this._val('battery_charge_power') - this._val('battery_discharge_power');
        }
        const raw = this._val('battery_power');
        return e?.battery?.reverse ? -raw : raw;
    }

    _flowGridPair() {
        const e = this._entities;
        if (this._mode === 'entities' && e?.grid?.entity) {
            const gp = this._state(e.grid.entity, 0);
            const rev = e.grid.reverse;
            return {
                gridImport: Math.max(0, rev ? -gp : gp),
                gridExport: Math.max(0, rev ? gp : -gp),
            };
        }
        return {
            gridImport: this._val('grid_import_power'),
            gridExport: this._val('grid_export_power'),
        };
    }

    _flowEv() {
        const v = this._val('ev_power');
        return this._entities?.ev?.invert ? -v : v;
    }

    _flowHome(solar, gridImport, gridExport, battCharge, battDischarge, ev) {
        // Prefer the PUBLISHED home sensor over a client-side residual.
        // The coordinator already bridges the input-update skew — the
        // Huawei inverter refreshes on a ~17-30 s modbus cadence while
        // the KEBA EV meter updates every ~2 s, so a client-side
        // ``solar − ev − …`` recompute pairs a stale solar reading with
        // a fresh EV reading and the residual briefly goes negative →
        // clamps Home to 0 (the on-and-off "Home 0 W" flicker while the
        // EV charges). ``sensor.sem_home_consumption_power`` carries the
        // #237/#444 hold that rides out that window, so it does NOT
        // flicker. Read it directly (both prefix and entities mode) and
        // only fall back to the residual when it's genuinely
        // unavailable.
        const eid = this._eid('home_consumption_power');
        const st = eid ? this._hass?.states[eid] : null;
        if (st && st.state !== 'unavailable' && st.state !== 'unknown') {
            let h = this._state(eid, 0);
            if (this._entities?.home?.invert) h = -h;
            return Math.max(0, h);
        }
        return Math.max(0, solar + gridImport + battDischarge - gridExport - battCharge - ev);
    }

    // ── hass setter: prefix-aware dirty check + target update + tick start ──
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

        if (this._isFrozen() && !localeChanged) return;

        // Skip transient unavailable states caused by coordinator refresh —
        // matches sem-battery-card.js:89-92. ~600ms window after every cycle.
        // #455: routed through _eid; in entities mode an unmapped solar key
        // resolves to null and the skip never blocks updates.
        const solarEid = this._eid('solar_power');
        const solarState = solarEid ? hass?.states[solarEid]?.state : undefined;
        if ((solarState === 'unavailable' || solarState === 'unknown') && !localeChanged) {
            return;
        }

        // Build the dirty-check key across everything the diagram reads.
        const stateOf = (suffix) => {
            const eid = this._eid(suffix);
            return eid ? (hass?.states[eid]?.state || '') : '';
        };
        let key = WATCHED_SUFFIXES.map(stateOf).join(',') + '|' + lang;
        key += '|' + semPVStringStatesKey(hass, this._prefix);
        key += '|' + (hass?.states['binary_sensor.sem_ev_connected']?.state || '');
        key += '|' + (hass?.states['binary_sensor.sem_ev_charging']?.state || '');
        const sun = hass?.states['sun.sun'];
        key += '|' + (sun?.attributes?.elevation ?? '')
             + ':' + (sun?.attributes?.next_rising || '')
             + ':' + (sun?.attributes?.next_setting || '');

        if (key === this._lastDiagKey && !localeChanged) return;
        this._lastDiagKey = key;

        // Compute counter targets — eased into the reactive properties
        // by the rAF tick. #455: flow helpers apply entities-mode
        // semantics (split battery / combined grid / reverse / invert);
        // prefix mode is identical to pre-#455.
        const solar = this._flowSolar();
        const battery = this._flowBattery();
        const battCharge = Math.max(0, battery);
        const battDischarge = Math.max(0, -battery);
        const { gridImport, gridExport } = this._flowGridPair();
        const ev = this._flowEv();
        const home = this._flowHome(solar, gridImport, gridExport, battCharge, battDischarge, ev);
        this._targets = {
            solar,
            batt: Math.abs(battery),
            home,
            ev,
            grid: gridExport > 10 ? gridExport : (gridImport > 10 ? gridImport : 0),
            gridMode: gridExport > 10 ? '↑' : (gridImport > 10 ? '↓' : null),
        };
        this._startTickIfIdle();

        this._scheduleUpdate();
    }

    get hass() { return this._hass; }

    // ── Suffix-scoped state readers (matches sem-battery-card.js:116-122;
    //    #455: routed through _eid so entities mode resolves too) ──
    _val(suffix, fallback = 0) {
        const eid = this._eid(suffix);
        return eid ? this._state(eid, fallback) : fallback;
    }

    _valStr(suffix) {
        const eid = this._eid(suffix);
        return eid ? this._stateStr(eid) : '';
    }

    /**
     * Read a numeric sensor with a "hold last good value" buffer for the
     * Huawei modbus flicker class. Returns ``{value, stale}``:
     *
     *  - Entity available and parseable → cache & return ``{value, stale:false}``.
     *  - Entity unavailable/unknown but a cached value exists from less
     *    than ``maxStaleMs`` ago → return the cached value with
     *    ``{stale:false}`` so the UI doesn't visibly flicker.
     *  - Entity unavailable/unknown and either no cache OR cache older
     *    than ``maxStaleMs`` → return ``{value:0, stale:true}`` so the
     *    caller can surface a real-stale indicator.
     *
     * Cache is stored under ``cacheKey`` on the instance (string field name
     * so the linter can flag accidental collisions). Holds across re-renders
     * because instance fields survive Lit re-render cycles.
     */
    _readWithHold(suffix, cacheKey, maxStaleMs) {
        const eid = this._eid(suffix);
        const entity = eid ? this._hass?.states[eid] : undefined;
        const raw = entity?.state;
        const available = entity && raw !== 'unavailable' && raw !== 'unknown';
        const now = Date.now();
        const tsKey = cacheKey + 'Ts';
        // ``cacheKey`` is something like 'this._lastBattPower' — strip the
        // ``this.`` prefix so we can use bracket access on the instance.
        const k = cacheKey.startsWith('this.') ? cacheKey.slice(5) : cacheKey;
        const t = tsKey.startsWith('this.') ? tsKey.slice(5) : tsKey;
        if (available) {
            const v = parseFloat(raw);
            if (!Number.isNaN(v)) {
                this[k] = v;
                this[t] = now;
                return { value: v, stale: false };
            }
        }
        if (this[k] != null && (now - (this[t] || 0)) < maxStaleMs) {
            return { value: this[k], stale: false };
        }
        return { value: 0, stale: true };
    }

    // ── Animated counter tick: damped-lerp + batched property write per frame ──
    _startTickIfIdle() {
        if (this._counterRaf) return;
        const ease = (cur, target) => {
            const c = cur ?? 0;
            const delta = target - c;
            if (Math.abs(delta) < 0.5) return target;
            return c + delta * 0.18;
        };
        const step = () => {
            if (!this._targets) { this._counterRaf = null; return; }
            const t = this._targets;
            const ns = ease(this._solarDisp, t.solar);
            const nb = ease(this._battDisp,  t.batt);
            const nh = ease(this._homeDisp,  t.home);
            const ne = ease(this._evDisp,    t.ev);
            const ng = ease(this._gridDisp,  t.grid);
            const done = ns === t.solar && nb === t.batt && nh === t.home
                      && ne === t.ev && ng === t.grid
                      && this._gridDispMode === t.gridMode;

            this._solarDisp = ns;
            this._battDisp  = nb;
            this._homeDisp  = nh;
            this._evDisp    = ne;
            this._gridDisp  = ng;
            this._gridDispMode = t.gridMode;

            this._counterRaf = done ? null : requestAnimationFrame(step);
        };
        this._counterRaf = requestAnimationFrame(step);
    }

    // ── Observers: compact toggle + visibility ──
    firstUpdated() {
        this._resizeObserver = new ResizeObserver(entries => {
            if (this._resizeTimeout) clearTimeout(this._resizeTimeout);
            this._resizeTimeout = setTimeout(() => {
                for (const entry of entries) {
                    const compact = entry.contentRect.width < 500;
                    if (compact !== this._compact) {
                        this._compact = compact;
                        this._sunSparkSig = ''; // layout changed; re-randomize spark
                        this._lastDiagKey = '';
                        this.requestUpdate();
                    }
                }
            }, 100);
        });
        this._resizeObserver.observe(this);

        this._intersectionObserver = new IntersectionObserver(entries => {
            this._visible = entries[0].isIntersecting;
            const root = this.renderRoot.querySelector('svg');
            if (root) root.style.animationPlayState = this._visible ? 'running' : 'paused';
        }, { threshold: 0.01 });
        this._intersectionObserver.observe(this);
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        if (this._resizeObserver) { this._resizeObserver.disconnect(); this._resizeObserver = null; }
        if (this._intersectionObserver) { this._intersectionObserver.disconnect(); this._intersectionObserver = null; }
        clearTimeout(this._resizeTimeout);
        if (this._counterRaf) { cancelAnimationFrame(this._counterRaf); this._counterRaf = null; }
    }

    // ── Sun arc: the one legitimate DOM-measurement bit, dirty-guarded ──
    updated(changed) {
        super.updated(changed);
        if (!this._hass) return;
        const arcPath = this.renderRoot.querySelector('#sun-arc-path');
        if (!arcPath) return;
        const L = this._getLayout();
        const pose = this._computeSunPose();
        try {
            const len = arcPath.getTotalLength();
            const pt = arcPath.getPointAtLength(pose.pos * len);
            const dx = pt.x - L.sunX;
            const dy = pt.y - L.sunY;
            const newSunT = `translate(${dx.toFixed(1)},${dy.toFixed(1)}) translate(${L.sunX},${L.sunY}) scale(${pose.scale.toFixed(2)}) translate(${(-L.sunX).toFixed(1)},${(-L.sunY).toFixed(1)})`;
            const newMoonT = pose.isNight ? `translate(${dx.toFixed(1)},${dy.toFixed(1)})` : '';
            const newPLX = pt.x.toFixed(1);
            const newPLY = (pt.y + L.sunR * pose.scale + 16).toFixed(1);
            const newSPtX = +pt.x.toFixed(1);
            const newSPtY = +pt.y.toFixed(1);
            if (this._sunTransform === newSunT
                && this._moonTransform === newMoonT
                && this._sunPowerX === newPLX
                && this._sunPowerY === newPLY
                && this._sunPtX === newSPtX
                && this._sunPtY === newSPtY) return;
            this._sunTransform = newSunT;
            this._moonTransform = newMoonT;
            this._sunPowerX = newPLX;
            this._sunPowerY = newPLY;
            this._sunPtX = newSPtX;
            this._sunPtY = newSPtY;
        } catch (_) {
            // Arc not laid out yet — will retry on next render
        }
    }

    // Pure helper: returns sun pose {pos, scale, isNight} — no DOM access.
    _computeSunPose() {
        const sunEntity = this._hass?.states['sun.sun'];
        const elevation = sunEntity ? (parseFloat(sunEntity.attributes?.elevation) || -90) : -90;
        const isNight = elevation < 0;
        const solar = this._val('solar_power');
        const a = sunEntity?.attributes;
        let pos = 0.5;
        if (a) {
            const nextRiseTs = a.next_rising ? new Date(a.next_rising).getTime() : 0;
            const nextSetTs = a.next_setting ? new Date(a.next_setting).getTime() : 0;
            const now = Date.now();
            if (!isNight && nextRiseTs && nextSetTs) {
                const todaySunrise = nextRiseTs - 86400000;
                const dayLength = nextSetTs - todaySunrise;
                if (dayLength > 0) pos = (now - todaySunrise) / dayLength;
            } else {
                pos = (nextRiseTs && now < nextRiseTs) ? 0 : 1;
            }
            pos = Math.max(0.06, Math.min(0.94, pos));
        }
        const scale = isNight ? 0.7 : (0.7 + 0.6 * Math.min(1, solar / 10000));
        return { pos, scale, isNight, solar };
    }

    // ── Static CSS ──
    static get styles() {
        return css`
            :host { display: block; }
            ha-card { overflow: hidden; padding: 0; background: transparent !important; }
            svg { width: 100%; display: block; }
            .flow-group { transition: opacity 0.8s cubic-bezier(0.4,0,0.2,1); }
            .clickable { cursor: pointer; pointer-events: bounding-box; }
            .clickable:hover { filter: brightness(1.2); }
            text { font-variant-numeric: tabular-nums; }
            @media (prefers-reduced-motion: reduce) {
                .flow-group { transition: none; }
                animate, animateMotion { display: none; }
            }
        `;
    }

    // ── Render: pure-reactive SVG ──
    render() {
        if (!this._config) return nothing;

        const L = this._getLayout();
        const c = this._compact;
        const F = "'Segoe UI','Roboto',sans-serif";
        const fl = L.font.label, fv = L.font.value, fs = L.font.sub;

        // State reads (#455: flow helpers carry entities-mode semantics;
        // prefix mode is identical to pre-#455)
        const solar = this._flowSolar();
        const { gridImport, gridExport } = this._flowGridPair();
        const ev = this._flowEv();

        // Battery reads with last-known-good hold for Huawei modbus flicker.
        // Per CLAUDE.md the Huawei modbus over WiFi bounces every 10–30 s;
        // each bounce flips ``sensor.sem_battery_soc`` and ``sensor.sem_battery_power``
        // to ``unavailable`` for 25–35 s before recovering. Without the hold
        // the diagram card collapses each flicker into "0% empty battery"
        // because ``_val()`` returns its fallback 0 when the entity is
        // unavailable. Visually that looks like an emergency. The hold caches
        // the most recent valid reading and uses it for up to 60 s of
        // continuous unavailability; past that, the card shows a stale
        // marker so a genuinely-broken sensor is still surfaced.
        // #455: with split charge/discharge entities the hold is bypassed —
        // the flicker class is specific to the combined Huawei sensor.
        const _battSplit = this._entities?.battery?.charge || this._entities?.battery?.discharge;
        let battery, battStale;
        if (_battSplit) {
            battery = this._flowBattery();
            battStale = false;
        } else {
            ({ value: battery, stale: battStale } =
                this._readWithHold('battery_power', 'this._lastBattPower', 60000));
            if (this._entities?.battery?.reverse) battery = -battery;
        }
        const { value: soc, stale: socStale } =
            this._readWithHold('battery_soc', 'this._lastBattSoc', 60000);
        const battSensorStale = battStale || socStale;
        const battCharge = Math.max(0, battery);
        const battDischarge = Math.max(0, -battery);

        const home = this._flowHome(solar, gridImport, gridExport, battCharge, battDischarge, ev);

        // Sun pose (pure)
        const pose = this._computeSunPose();
        const { isNight } = pose;
        const sunOpacity = isNight ? 0.3 : 0.85;
        const sparkOpacity = solar > 50 ? Math.min(1, 0.3 + solar / 5000) : 0;

        // Sun time labels
        const sunAttrs = this._hass?.states['sun.sun']?.attributes;
        const _tz = this._hass?.config?.time_zone || undefined;
        const sunRiseStr = sunAttrs?.next_rising ? semFormatTime(sunAttrs.next_rising, _tz) : '';
        const sunSetStr  = sunAttrs?.next_setting ? semFormatTime(sunAttrs.next_setting, _tz) : '';

        // Battery SOC geometry (mirrors _illustrationBattery scale)
        const battS = L.B.r / 50;
        const battBH = 64 * battS;
        const battInnerH = battBH - 12 * battS;
        const battInnerY = L.B.cy - battBH / 2 + 8 * battS;
        const socFillH = Math.max(0, Math.min(battInnerH, battInnerH * (soc / 100)));
        const socFillY = battInnerY + battInnerH - socFillH;
        const battFillColor = battCharge > 10 ? '#f06292' : 'url(#battFillGrad)';
        const showBattBolt = battCharge > 10;

        // Colors / state texts
        const gridColor = gridExport > gridImport ? '#8353d1' : '#488fc2';
        const gridStateText = (gridExport > 10 && gridExport > gridImport) ? this._t('exporting')
                            : gridImport > 10 ? this._t('importing') : '';
        const gridStateFill = (gridExport > 10 && gridExport > gridImport) ? '#8353d1' : '#488fc2';
        const battColor = battCharge > 10 ? '#f06292' : '#4db6ac';
        const battStateText = battCharge > 10 ? this._t('charging')
                            : battDischarge > 10 ? this._t('discharging') : '';
        const battStateFill = battCharge > 10 ? '#f06292' : '#4db6ac';

        const evConnected = this._hass?.states['binary_sensor.sem_ev_connected']?.state === 'on';
        const evCharging  = this._hass?.states['binary_sensor.sem_ev_charging']?.state === 'on';
        let evStateText = '', evStateFill = '#8DC892';
        if (evCharging || ev > 10) {
            evStateText = this._t('charging');
            evStateFill = '#8DC892';
        } else if (evConnected) {
            evStateText = this._t('connected') || 'Verbunden';
            evStateFill = 'rgba(141,200,146,0.6)';
        }

        // Daily kWh chips
        const todayLbl = this._t('today');
        const solarKwh   = `${todayLbl} ${this._valStr('daily_solar_energy')} kWh`;
        // #568 — the Home glance uses the raw provider full-day forecast
        // (forecast_today_kwh), matching every sibling card (solar / summary /
        // system / schedule). It previously read the performance-corrected
        // value, so the Home number differed from the Solar tab's "Forecast".
        // One decimal to match those cards.
        const forecast   = this._val('forecast_today_kwh');
        const solarFcst  = forecast > 0 ? `☀ ${forecast.toFixed(1)} kWh ${this._t('forecast') || 'Forecast'}` : '';
        const evKwh      = `${todayLbl} ${this._valStr('daily_ev_energy')} kWh`;
        const homeKwh    = `${todayLbl} ${this._val('daily_home_energy').toFixed(1)} kWh`;
        const battKwh    = `+${this._val('daily_battery_charge_energy').toFixed(1)} / -${this._val('daily_battery_discharge_energy').toFixed(1)} kWh`;
        const gridKwh    = `↓${this._val('daily_grid_import_energy').toFixed(1)} / ↑${this._val('daily_grid_export_energy').toFixed(1)} kWh`;

        // Inverter status
        const battTemp = this._val('battery_temperature');
        const invTempStr = battTemp > 0 ? `${battTemp.toFixed(0)}°C` : '';
        const chargingState = this._valStr('charging_state');
        const maxLen = c ? 22 : 30;
        const invStatusStr = chargingState.length > maxLen
            ? chargingState.substring(0, maxLen - 1) + '…'
            : chargingState;

        // Unavailable entity status. #455: in entities mode only mapped
        // keys count — an intentionally omitted node (no EV configured)
        // must not show as a permanent "sensor unavailable" warning.
        const unavailable = [];
        for (const suffix of ['solar_power', 'battery_power', 'grid_import_power', 'grid_export_power', 'ev_power', 'battery_soc']) {
            const eid = this._eid(suffix);
            if (!eid) {
                if (this._mode === 'prefix') unavailable.push(suffix);
                continue;
            }
            const entity = this._hass?.states[eid];
            if (!entity || entity.state === 'unavailable' || entity.state === 'unknown') unavailable.push(suffix);
        }

        // Animated display strings
        const dispSolar = semFormatPower(this._solarDisp ?? 0);
        const battArrow = battCharge > 10 ? '↑ ' : battDischarge > 10 ? '↓ ' : '';
        const dispBatt  = battArrow + semFormatPower(this._battDisp ?? 0);
        const dispHome  = semFormatPower(this._homeDisp ?? 0);
        const dispEv    = semFormatPower(this._evDisp ?? 0);
        const dispGrid  = this._gridDispMode
            ? `${this._gridDispMode} ${semFormatPower(this._gridDisp ?? 0)}`
            : semFormatPower(0);
        const gridSingleFill = this._gridDispMode === '↑' ? '#8353d1' : '#488fc2';

        // PV strings sub-card row
        const pvStrings = semDiscoverPVStrings(this._hass, this._prefix);

        // Flow predicates
        const flowSolarActive = solar > 10;
        const flowBattActive  = Math.abs(battery) > 10;
        const flowBattReverse = battery < 0;
        const flowBattColor   = battCharge > 10 ? '#f06292' : '#4db6ac';
        const flowGridActive  = gridImport > 10 || gridExport > 10;
        const flowGridReverse = gridImport > gridExport;
        const flowGridColor   = gridExport > gridImport ? '#8353d1' : '#488fc2';
        const flowHomeActive  = home > 10;
        const flowEvActive    = ev > 10;

        return html`
            <ha-card>
                <style>${semPVStringsCSS}</style>
                ${pvStrings.length >= 2 ? html`
                    <div class="pv-strings-row">
                        ${pvStrings.map(s => html`
                            <div class="pv-chip"
                                 title="${s.entityId}"
                                 data-entity="${s.entityId}"
                                 @click=${() => this._fireMoreInfo?.(s.entityId)}>
                                <span class="pv-chip-label">${s.name}</span>
                                <span class="pv-chip-value">${(Math.abs(s.watts)/1000).toFixed(2)} kW</span>
                            </div>
                        `)}
                    </div>
                ` : nothing}
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${L.vb}"
                     style="background:transparent;overflow:hidden"
                     role="img" aria-label="Solar energy system power flow diagram">
                    <defs>
                        <radialGradient id="bgGrad" cx="50%" cy="40%" r="65%">
                            <stop offset="0%" stop-color="rgba(150,202,238,0.06)"/>
                            <stop offset="100%" stop-color="rgba(0,0,0,0)"/>
                        </radialGradient>
                        <pattern id="dotGrid" width="40" height="40" patternUnits="userSpaceOnUse">
                            <circle cx="20" cy="20" r="0.6" fill="rgba(128,128,128,0.07)"/>
                        </pattern>

                        ${this._glowFilter('glowSolar',    '#ff9800', 10)}
                        ${this._glowFilter('glowBattery',  '#4db6ac', 8)}
                        ${this._glowFilter('glowGrid',     '#488fc2', 8)}
                        ${this._glowFilter('glowHome',     '#5BC8D8', 12)}
                        ${this._glowFilter('glowEV',       '#8DC892', 8)}
                        ${this._glowFilter('glowInverter', '#96CAEE', 6)}
                        ${this._glowFilter('glowSun',      '#FCD170', 14)}

                        <linearGradient id="panelBlue" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#1565C0" stop-opacity="0.9"/>
                            <stop offset="50%" stop-color="#1976D2" stop-opacity="0.8"/>
                            <stop offset="100%" stop-color="#0D47A1" stop-opacity="0.95"/>
                        </linearGradient>
                        <linearGradient id="panelBlue2" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#1E88E5" stop-opacity="0.85"/>
                            <stop offset="100%" stop-color="#1565C0" stop-opacity="0.9"/>
                        </linearGradient>
                        <linearGradient id="panelReflect" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="rgba(255,255,255,0.18)"/>
                            <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
                        </linearGradient>

                        <linearGradient id="battBody" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stop-color="#1a2e2c"/>
                            <stop offset="100%" stop-color="#1f3835"/>
                        </linearGradient>
                        <linearGradient id="battFillGrad" x1="0%" y1="100%" x2="0%" y2="0%">
                            <stop offset="0%" stop-color="#4db6ac"/>
                            <stop offset="100%" stop-color="#80cbc4"/>
                        </linearGradient>

                        <linearGradient id="roofGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#c62828"/>
                            <stop offset="100%" stop-color="#b71c1c"/>
                        </linearGradient>
                        <linearGradient id="wallGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#37474F"/>
                            <stop offset="100%" stop-color="#263238"/>
                        </linearGradient>
                        <radialGradient id="windowGlow" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="#FFF9C4" stop-opacity="0.9"/>
                            <stop offset="100%" stop-color="#F9A825" stop-opacity="0.3"/>
                        </radialGradient>

                        <linearGradient id="poleGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stop-color="#5c7a9b"/>
                            <stop offset="50%" stop-color="#6d8fad"/>
                            <stop offset="100%" stop-color="#5c7a9b"/>
                        </linearGradient>

                        <linearGradient id="invGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#1a2740"/>
                            <stop offset="100%" stop-color="#0f1820"/>
                        </linearGradient>

                        <linearGradient id="carGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#2e5a3c"/>
                            <stop offset="100%" stop-color="#1b3b27"/>
                        </linearGradient>

                        <radialGradient id="sunGradInner" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="#FFF9C4"/>
                            <stop offset="60%" stop-color="#FCD170"/>
                            <stop offset="100%" stop-color="#F7941E"/>
                        </radialGradient>

                        <path id="path-solar"   d="${L.paths.solar}"/>
                        <path id="path-home"    d="${L.paths.home}"/>
                        <path id="path-battery" d="${L.paths.battery}"/>
                        <path id="path-grid"    d="${L.paths.grid}"/>
                        <path id="path-ev"      d="${L.paths.ev}"/>

                        ${this._sunPtX != null && solar > 50 ? this._sparkWavePath(L) : nothing}
                    </defs>

                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="100%" fill="url(#dotGrid)"/>

                    <!-- Sun arc group -->
                    <g>
                        <path id="sun-arc-path" d="${L.sunArc}" fill="none" stroke="rgba(252,209,112,0.12)"
                              stroke-width="2" stroke-dasharray="4,8"/>
                        <text x="${L.sunRisingX}" y="${L.sunLabelY}"
                              text-anchor="middle" font-family="${F}" font-size="${fs}"
                              fill="#FCD170" opacity="0.45">${sunRiseStr}</text>
                        <text x="${L.sunSettingX}" y="${L.sunLabelY}"
                              text-anchor="middle" font-family="${F}" font-size="${fs}"
                              fill="#FCD170" opacity="0.45">${sunSetStr}</text>

                        <g filter="url(#glowSun)" style="opacity:${sunOpacity}"
                           transform="${this._sunTransform ?? ''}">
                            <circle cx="${L.sunX}" cy="${L.sunY}" r="${L.sunR + 6}"
                                    fill="rgba(252,209,112,0.15)"/>
                            ${this._sunRays(L.sunX, L.sunY, L.sunR)}
                            <circle cx="${L.sunX}" cy="${L.sunY}" r="${L.sunR}"
                                    fill="url(#sunGradInner)"/>
                            <ellipse cx="${L.sunX - L.sunR * 0.25}" cy="${L.sunY - L.sunR * 0.28}"
                                     rx="${L.sunR * 0.35}" ry="${L.sunR * 0.22}"
                                     fill="rgba(255,255,255,0.35)"/>
                        </g>

                        <g style="display:${isNight ? 'block' : 'none'}"
                           transform="${this._moonTransform ?? ''}">
                            <circle cx="${L.sunX}" cy="${L.sunY}" r="${L.sunR}" fill="#1a2540"/>
                            <circle cx="${L.sunX + L.sunR * 0.38}" cy="${L.sunY - L.sunR * 0.22}"
                                    r="${L.sunR * 0.78}" fill="#0d1a30"/>
                            <circle cx="${L.sunX}" cy="${L.sunY}" r="${L.sunR}"
                                    fill="none" stroke="rgba(200,220,255,0.5)" stroke-width="1"/>
                        </g>

                        <g style="display:${isNight ? 'block' : 'none'}" fill="rgba(200,220,255,0.6)">
                            <circle cx="${L.starX[0]}" cy="${L.starY[0]}" r="1.2"/>
                            <circle cx="${L.starX[1]}" cy="${L.starY[1]}" r="0.9"/>
                            <circle cx="${L.starX[2]}" cy="${L.starY[2]}" r="1.4"/>
                            <circle cx="${L.starX[3]}" cy="${L.starY[3]}" r="0.8"/>
                            <circle cx="${L.starX[4]}" cy="${L.starY[4]}" r="1.1"/>
                        </g>

                        <text x="${this._sunPowerX ?? L.sunX}" y="${this._sunPowerY ?? (L.sunY + L.sunR + 14)}"
                              text-anchor="middle" font-family="${F}" font-size="${fs}"
                              fill="#FCD170" opacity="0.7" font-weight="600">${solar > 10 ? semFormatPower(solar) : ''}</text>

                        <g style="opacity:${sparkOpacity}">
                            ${this._sunPtX != null && solar > 50 ? this._renderSunSpark(solar) : nothing}
                        </g>
                    </g>

                    <!-- Static dashed flow tracks -->
                    <path d="${L.paths.solar}"   fill="none" stroke="#ff9800" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${L.paths.home}"    fill="none" stroke="#5BC8D8" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${L.paths.battery}" fill="none" stroke="#4db6ac" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${L.paths.grid}"    fill="none" stroke="#488fc2" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${L.paths.ev}"      fill="none" stroke="#8DC892" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>

                    <!-- Flow animation groups -->
                    <g class="flow-group" style="opacity:${flowSolarActive ? 1 : 0}">
                        ${this._renderFlow(false, '#ff9800', semCalcDuration(solar), 'path-solar', L.paths.solar, 2)}
                    </g>
                    <g class="flow-group" style="opacity:${flowBattActive ? 1 : 0}">
                        ${this._renderFlow(flowBattReverse, flowBattColor, semCalcDuration(battery), 'path-battery', L.paths.battery, 3)}
                    </g>
                    <g class="flow-group" style="opacity:${flowGridActive ? 1 : 0}">
                        ${this._renderFlow(flowGridReverse, flowGridColor, semCalcDuration(gridImport || gridExport), 'path-grid', L.paths.grid, 3)}
                    </g>
                    <g class="flow-group" style="opacity:${flowHomeActive ? 1 : 0}">
                        ${this._renderFlow(false, '#5BC8D8', semCalcDuration(home), 'path-home', L.paths.home, 2)}
                    </g>
                    <g class="flow-group" style="opacity:${flowEvActive ? 1 : 0}">
                        ${this._renderFlow(false, '#8DC892', semCalcDuration(ev), 'path-ev', L.paths.ev, 3)}
                    </g>

                    <!-- Solar panel -->
                    <g filter="url(#glowSolar)" class="clickable" @click=${() => this._showMoreInfo('solar_power')}>
                        ${this._illustrationSolarPanel(L.S.cx, L.S.cy, L.S.r)}
                    </g>
                    <text x="${L.S.cx}" y="${L.S.labelY}" text-anchor="middle"
                          font-family="${F}" font-size="${fl}" font-weight="700"
                          fill="#ff9800" letter-spacing="0.5">${this._t('solar')}</text>
                    <text x="${L.S.cx}" y="${L.S.labelY + fv * 1.1}" class="clickable"
                          @click=${() => this._showMoreInfo('solar_power')}
                          text-anchor="middle" font-family="${F}" font-size="${fv}"
                          font-weight="800" fill="#ff9800">${dispSolar}</text>
                    <text x="${L.S.cx}" y="${L.S.labelY + fv * 1.1 + fs + 3}" class="clickable"
                          @click=${() => this._showMoreInfo('daily_solar_energy')}
                          text-anchor="middle" font-family="${F}" font-size="${fs + 1}"
                          fill="#ff9800" opacity="0.6" font-weight="600">${solarKwh}</text>
                    <text x="${L.S.cx}" y="${L.S.labelY + fv * 1.1 + (fs + 3) * 2}" class="clickable"
                          @click=${() => this._showMoreInfo('forecast_today_kwh')}
                          text-anchor="middle" font-family="${F}" font-size="${fs}"
                          fill="#ff9800" opacity="0.4" font-weight="500">${solarFcst}</text>

                    <!-- Inverter -->
                    <g filter="url(#glowInverter)">
                        ${this._illustrationInverter(L.I.cx, L.I.cy, L.I.r)}
                    </g>
                    <text x="${L.I.cx}" y="${L.I.cy + L.I.r + 14}"
                          text-anchor="middle" font-family="${F}" font-size="${fs}"
                          fill="#96CAEE" opacity="0.6" font-weight="600">${invTempStr}</text>
                    <text x="${L.I.cx}" y="${L.I.cy + L.I.r + 14 + fs + 2}"
                          text-anchor="middle" font-family="${F}" font-size="${fs - 1}"
                          fill="#96CAEE" opacity="0.35">${invStatusStr}</text>

                    <!-- Battery — group opacity fades to 0.35 if both
                         battery_soc and battery_power have been
                         unavailable for >60 s (Huawei modbus hard
                         dropout). Brief flickers (<60 s) are absorbed
                         by '_readWithHold' upstream so the user
                         doesn't see a visual emergency. (NEVER put
                         backticks inside this lit template: they
                         terminate the template literal and the whole
                         card renders blank, #488.) -->
                    <g filter="url(#glowBattery)" class="clickable"
                       opacity="${battSensorStale ? 0.35 : 1}"
                       @click=${() => this._showMoreInfo('battery_soc')}>
                        ${this._illustrationBattery(L.B.cx, L.B.cy, L.B.r, socFillH, socFillY, battFillColor, showBattBolt, soc)}
                    </g>
                    <text x="${L.B.cx}" y="${L.B.labelY}" text-anchor="middle"
                          font-family="${F}" font-size="${fl}" font-weight="700"
                          fill="#4db6ac" letter-spacing="0.5">${this._t('battery')}</text>
                    <text x="${L.B.cx}" y="${L.B.labelY + fv * 1.0}" class="clickable"
                          @click=${() => this._showMoreInfo('battery_power')}
                          text-anchor="middle" font-family="${F}" font-size="${fv}"
                          font-weight="800" fill="${battColor}"
                          opacity="${battSensorStale ? 0.4 : 1}">${battSensorStale ? '— W' : dispBatt}</text>
                    <text x="${L.B.cx}" y="${L.B.labelY + fv * 1.0 + fl}"
                          text-anchor="middle" font-family="${F}" font-size="${fl}"
                          fill="${battStateFill}" opacity="0.6">${battSensorStale ? this._t('sensor_unavailable') : battStateText}</text>
                    <text x="${L.B.cx}" y="${L.B.labelY + fv * 1.0 + fl + fs + 2}" class="clickable"
                          @click=${() => this._showMoreInfo('daily_battery_charge_energy')}
                          text-anchor="middle" font-family="${F}" font-size="${fs + 1}"
                          fill="#4db6ac" opacity="0.6" font-weight="600">${battKwh}</text>

                    <!-- Grid -->
                    <g filter="url(#glowGrid)" class="clickable" @click=${() => this._showMoreInfo('grid_import_power')}>
                        ${this._illustrationGrid(L.G.cx, L.G.cy, L.G.r)}
                    </g>
                    <text x="${L.G.cx}" y="${L.G.labelY}" text-anchor="middle"
                          font-family="${F}" font-size="${fl}" font-weight="700"
                          fill="${gridColor}" letter-spacing="0.5">${this._t('grid')}</text>
                    <text x="${L.G.cx}" y="${L.G.labelY + fv}" class="clickable"
                          @click=${() => this._showMoreInfo('grid_power')}
                          text-anchor="middle" font-family="${F}" font-size="${fv}"
                          font-weight="800" fill="${gridSingleFill}">${dispGrid}</text>
                    <text x="${L.G.cx}" y="${L.G.labelY + fv + fl + 1}"
                          text-anchor="middle" font-family="${F}" font-size="${fl}"
                          fill="${gridStateFill}" opacity="0.6">${gridStateText}</text>
                    <text x="${L.G.cx}" y="${L.G.labelY + fv + fl + fs + 4}" class="clickable"
                          @click=${() => this._showMoreInfo('daily_grid_import_energy')}
                          text-anchor="middle" font-family="${F}" font-size="${fs + 1}"
                          fill="#488fc2" opacity="0.6" font-weight="600">${gridKwh}</text>

                    <!-- House -->
                    <g filter="url(#glowHome)" class="clickable" @click=${() => this._showMoreInfo('home_consumption_power')}>
                        ${this._illustrationHouse(L.H.cx, L.H.cy, L.H.r)}
                    </g>
                    <text x="${L.H.cx}" y="${L.H.labelY}" text-anchor="middle"
                          font-family="${F}" font-size="${fl}" font-weight="700"
                          fill="#5BC8D8" letter-spacing="0.5">${this._t('home')}</text>
                    <text x="${L.H.cx}" y="${L.H.labelY + fv * 1.1}" class="clickable"
                          @click=${() => this._showMoreInfo('home_consumption_power')}
                          text-anchor="middle" font-family="${F}" font-size="${fv}"
                          font-weight="800" fill="#5BC8D8">${dispHome}</text>
                    <text x="${L.H.cx}" y="${L.H.labelY + fv * 1.1 + fs + 3}" class="clickable"
                          @click=${() => this._showMoreInfo('daily_home_energy')}
                          text-anchor="middle" font-family="${F}" font-size="${fs + 1}"
                          fill="#5BC8D8" opacity="0.6" font-weight="600">${homeKwh}</text>

                    <!-- EV -->
                    <g filter="url(#glowEV)" class="clickable" @click=${() => this._showMoreInfo('ev_power')}>
                        ${this._illustrationEV(L.E.cx, L.E.cy, L.E.r)}
                    </g>
                    <text x="${L.E.cx}" y="${L.E.labelY}" text-anchor="middle"
                          font-family="${F}" font-size="${fl}" font-weight="700"
                          fill="#8DC892" letter-spacing="0.5">${this._t('ev_charging')}</text>
                    <text x="${L.E.cx}" y="${L.E.labelY + fv * 1.0}" class="clickable"
                          @click=${() => this._showMoreInfo('ev_power')}
                          text-anchor="middle" font-family="${F}" font-size="${fv}"
                          font-weight="800" fill="#8DC892">${dispEv}</text>
                    <text x="${L.E.cx}" y="${L.E.labelY + fv * 1.0 + fl}"
                          text-anchor="middle" font-family="${F}" font-size="${fl}"
                          fill="${evStateFill}" opacity="0.6">${evStateText}</text>
                    <text x="${L.E.cx}" y="${L.E.labelY + fv * 1.0 + fl + fs + 2}" class="clickable"
                          @click=${() => this._showMoreInfo('daily_ev_energy')}
                          text-anchor="middle" font-family="${F}" font-size="${fs + 1}"
                          fill="#8DC892" opacity="0.6" font-weight="600">${evKwh}</text>

                    <!-- Device strip (desktop only) -->
                    ${!c ? this._renderDeviceStrip(L.H) : nothing}

                    <!-- Entity status indicator -->
                    ${unavailable.length > 0 ? html`
                        <foreignObject x="${c ? 8 : 10}" y="${L.statusY}" width="220" height="22">
                            <div xmlns="http://www.w3.org/1999/xhtml"
                                 style="font-family:'Segoe UI','Roboto',sans-serif;font-size:11px;color:#ef5350;opacity:0.75;white-space:nowrap">⚠ ${unavailable.length} ${this._t('sensor_unavailable')}</div>
                        </foreignObject>
                    ` : nothing}

                    <text x="${L.wmX}" y="${L.wmY}" text-anchor="end"
                          font-family="${F}" font-size="9" font-weight="300"
                          letter-spacing="2.5" fill="rgba(255,255,255,0.06)">SEM</text>
                </svg>
            </ha-card>
        `;
    }

    // ══════════════════════════════════════════════════════════════════
    //  INLINE SVG ILLUSTRATION HELPERS
    // ══════════════════════════════════════════════════════════════════

    /**
     * Solar panel array — 3x2 tilted perspective panel grid on mounting frame
     */
    _illustrationSolarPanel(cx, cy, r) {
        const s = r / 50;
        const W = 86 * s, H = 58 * s;
        const x = cx - W / 2, y = cy - H / 2 - 4 * s;
        const pw = W / 3, ph = H / 2;
        const skew = 6 * s;
        const frameH = 12 * s;
        return svg`
            <circle cx="${cx}" cy="${cy}" r="${r + 4}" fill="none"
                    stroke="#ff9800" stroke-width="1.2" opacity="0.25"/>

            <line x1="${x + skew}" y1="${y + H}" x2="${x + skew - 4*s}" y2="${y + H + frameH}"
                  stroke="#ff9800" stroke-width="${2*s}" stroke-linecap="round" opacity="0.7"/>
            <line x1="${x + W - skew}" y1="${y + H}" x2="${x + W - skew + 4*s}" y2="${y + H + frameH}"
                  stroke="#ff9800" stroke-width="${2*s}" stroke-linecap="round" opacity="0.7"/>
            <line x1="${x + W/2}" y1="${y + H}" x2="${x + W/2}" y2="${y + H + frameH * 0.8}"
                  stroke="#ff9800" stroke-width="${1.5*s}" stroke-linecap="round" opacity="0.5"/>
            <line x1="${x + skew - 6*s}" y1="${y + H + frameH}"
                  x2="${x + W - skew + 6*s}" y2="${y + H + frameH}"
                  stroke="#ff9800" stroke-width="${2.5*s}" stroke-linecap="round" opacity="0.6"/>

            <line x1="${x}" y1="${y + H * 0.52}" x2="${x + W}" y2="${y + H * 0.52}"
                  stroke="#ff9800" stroke-width="${2*s}" opacity="0.5"/>
            <line x1="${x}" y1="${y}" x2="${x + W}" y2="${y}"
                  stroke="#ff9800" stroke-width="${2*s}" opacity="0.5"/>

            <rect x="${x}"        y="${y}"      width="${pw}" height="${ph}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${x + pw}"   y="${y}"      width="${pw}" height="${ph}" fill="url(#panelBlue2)" rx="${1*s}"/>
            <rect x="${x + pw*2}" y="${y}"      width="${pw}" height="${ph}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${x}"        y="${y + ph}" width="${pw}" height="${ph}" fill="url(#panelBlue2)" rx="${1*s}"/>
            <rect x="${x + pw}"   y="${y + ph}" width="${pw}" height="${ph}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${x + pw*2}" y="${y + ph}" width="${pw}" height="${ph}" fill="url(#panelBlue2)" rx="${1*s}"/>

            <line x1="${x + pw}"   y1="${y}" x2="${x + pw}"   y2="${y + H}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            <line x1="${x + pw*2}" y1="${y}" x2="${x + pw*2}" y2="${y + H}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            <line x1="${x}" y1="${y + ph}" x2="${x + W}" y2="${y + ph}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            ${[0,1,2].map(col => svg`
                <line x1="${x + col*pw + pw/3}"   y1="${y}" x2="${x + col*pw + pw/3}"   y2="${y+H}" stroke="rgba(0,0,0,0.2)" stroke-width="${0.7*s}"/>
                <line x1="${x + col*pw + pw*2/3}" y1="${y}" x2="${x + col*pw + pw*2/3}" y2="${y+H}" stroke="rgba(0,0,0,0.2)" stroke-width="${0.7*s}"/>
            `)}
            <line x1="${x}" y1="${y + ph/3}"   x2="${x+W}" y2="${y + ph/3}"   stroke="rgba(0,0,0,0.18)" stroke-width="${0.7*s}"/>
            <line x1="${x}" y1="${y + ph*2/3}" x2="${x+W}" y2="${y + ph*2/3}" stroke="rgba(0,0,0,0.18)" stroke-width="${0.7*s}"/>

            <rect x="${x}" y="${y}" width="${W}" height="${H}"
                  fill="none" stroke="#ff9800" stroke-width="${2*s}" rx="${1.5*s}" opacity="0.8"/>

            <rect x="${x}" y="${y}" width="${W}" height="${H * 0.45}"
                  fill="url(#panelReflect)" rx="${1.5*s}" opacity="0.5"/>

            <circle cx="${cx}" cy="${y + H + frameH + 3*s}" r="${3*s}"
                    fill="#ff9800" opacity="0.6"/>
        `;
    }

    _sunRays(cx, cy, r) {
        const rays = [];
        for (let i = 0; i < 8; i++) {
            const angle = (i * 45) * Math.PI / 180;
            const inner = r + 3;
            const outer = r + r * 0.7;
            const spread = 0.18;
            const a1 = angle - spread, a2 = angle + spread;
            const x1 = cx + Math.cos(a1) * inner;
            const y1 = cy + Math.sin(a1) * inner;
            const x2 = cx + Math.cos(angle) * outer;
            const y2 = cy + Math.sin(angle) * outer;
            const x3 = cx + Math.cos(a2) * inner;
            const y3 = cy + Math.sin(a2) * inner;
            rays.push(svg`<polygon points="${x1},${y1} ${x2},${y2} ${x3},${y3}"
                                    fill="#FCD170" opacity="0.85"/>`);
        }
        return rays;
    }

    _illustrationInverter(cx, cy, r) {
        const s = r / 20;
        const bw = 38 * s, bh = 28 * s;
        const x = cx - bw / 2, y = cy - bh / 2;
        return svg`
            <rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="${4*s}"
                  fill="url(#invGrad)" stroke="#96CAEE" stroke-width="${1.5*s}" opacity="0.9"/>
            ${[0,1,2].map(i => svg`
                <line x1="${x + 4*s + i*5*s}" y1="${y + 3*s}" x2="${x + 4*s + i*5*s}" y2="${y + 7*s}"
                      stroke="#96CAEE" stroke-width="${1*s}" stroke-linecap="round" opacity="0.4"/>
            `)}
            <text x="${cx - 8*s}" y="${cy + 2*s}" font-family="'Segoe UI',sans-serif"
                  font-size="${7*s}" fill="#96CAEE" opacity="0.8" text-anchor="middle">DC</text>
            <path d="M${cx - 1*s},${cy - 4*s} L${cx - 3*s},${cy + 1*s} L${cx},${cy + 1*s}
                     L${cx},${cy + 5*s} L${cx + 2*s},${cy} L${cx - 1*s},${cy}"
                  fill="#FCD170" opacity="0.85"/>
            <text x="${cx + 8*s}" y="${cy + 2*s}" font-family="'Segoe UI',sans-serif"
                  font-size="${7*s}" fill="#96CAEE" opacity="0.8" text-anchor="middle">AC</text>
            <circle cx="${x + bw - 5*s}" cy="${y + 4*s}" r="${2.5*s}"
                    fill="#69f0ae" opacity="0.9">
                <animate attributeName="opacity" values="0.9;0.4;0.9" dur="2.5s" repeatCount="indefinite"/>
            </circle>
            <rect x="${cx - 3*s}" y="${y + bh}" width="${6*s}" height="${3*s}" rx="${1*s}"
                  fill="#96CAEE" opacity="0.4"/>
        `;
    }

    /**
     * Battery — tall storage unit with SOC fill bar.
     * Updated signature: fill geometry + color + bolt visibility + SOC% text
     * come from the caller (reactive), no imperative writes anywhere.
     */
    _illustrationBattery(cx, cy, r, socFillH, socFillY, battFillColor, showBolt, socPct) {
        const s = r / 50;
        const bw = 40 * s, bh = 64 * s;
        const x = cx - bw / 2, y = cy - bh / 2;
        const termH = 8 * s, termW = 16 * s;
        const innerW = bw - 8 * s, innerH = bh - 12 * s;
        const innerX = x + 4 * s, innerY = y + 8 * s;
        return svg`
            <circle cx="${cx}" cy="${cy}" r="${r + 4}" fill="none"
                    stroke="#4db6ac" stroke-width="1.2" opacity="0.25"/>

            <rect x="${cx - termW/2}" y="${y - termH}" width="${termW}" height="${termH}"
                  rx="${3*s}" fill="#2a4a47" stroke="#4db6ac" stroke-width="${1.5*s}" opacity="0.85"/>
            <line x1="${cx - termW/4}" y1="${y - termH/2}"
                  x2="${cx + termW/4}" y2="${y - termH/2}"
                  stroke="#4db6ac" stroke-width="${2*s}" stroke-linecap="round" opacity="0.8"/>
            <line x1="${cx}" y1="${y - termH * 0.75}" x2="${cx}" y2="${y - termH * 0.25}"
                  stroke="#4db6ac" stroke-width="${2*s}" stroke-linecap="round" opacity="0.8"/>

            <rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="${5*s}"
                  fill="url(#battBody)" stroke="#4db6ac" stroke-width="${2*s}" opacity="0.95"/>

            <rect x="${innerX}" y="${innerY}" width="${innerW}" height="${innerH}"
                  rx="${3*s}" fill="rgba(0,0,0,0.4)"/>

            <rect x="${innerX}" y="${socFillY.toFixed(1)}"
                  width="${innerW}" height="${socFillH.toFixed(1)}"
                  rx="${3*s}" fill="${battFillColor}" opacity="0.85"/>

            ${[1,2,3,4].map(i => svg`
                <line x1="${innerX}" y1="${innerY + innerH * i / 5}"
                      x2="${innerX + innerW}" y2="${innerY + innerH * i / 5}"
                      stroke="rgba(0,0,0,0.35)" stroke-width="${1.2*s}"/>
            `)}

            <text x="${cx}" y="${showBolt ? cy + 15*s : cy + 4*s}"
                  text-anchor="middle" font-family="'Segoe UI','Roboto',sans-serif"
                  font-size="${14*s}" font-weight="900" fill="#fff"
                  stroke="rgba(0,0,0,0.6)" stroke-width="${1.5*s}" paint-order="stroke">${socPct.toFixed(0)}%</text>

            ${showBolt ? svg`
                <g>
                    <path d="M${cx - 4*s},${(cy - 9*s) - 8*s} L${cx - 7*s},${(cy - 9*s) + 2*s} L${cx - 1*s},${(cy - 9*s) + 2*s}
                             L${cx - 1*s},${(cy - 9*s) + 10*s} L${cx + 6*s},${(cy - 9*s) - 2*s} L${cx + 1*s},${(cy - 9*s) - 2*s} Z"
                          fill="#FCD170" opacity="0.95"/>
                </g>
            ` : nothing}

            <rect x="${cx - 10*s}" y="${y + bh - 5*s}" width="${20*s}" height="${5*s}"
                  rx="${2*s}" fill="#4db6ac" opacity="0.25"/>
        `;
    }

    _illustrationHouse(cx, cy, r) {
        const s = r / 62;
        const ww = 80 * s, wh = 52 * s;
        const wx = cx - ww / 2, wy = cy - wh / 2 + 8 * s;
        const roofH = 38 * s;
        const rax = cx, ray = wy - roofH;
        const chx = cx + 18 * s, chy = ray + 8 * s;
        const chw = 10 * s, chh = 18 * s;
        const winW = 16 * s, winH = 14 * s;
        const winY = wy + 12 * s;
        const win1X = wx + 10 * s, win2X = wx + ww - 10 * s - winW;
        const doorW = 14 * s, doorH = 24 * s;
        const doorX = cx - doorW / 2, doorY = wy + wh - doorH;
        return svg`
            <circle cx="${cx}" cy="${cy}" r="${r + 4}" fill="none"
                    stroke="#5BC8D8" stroke-width="1.2" opacity="0.25"/>

            <rect x="${chx}" y="${chy - chh}" width="${chw}" height="${chh}"
                  rx="${2*s}" fill="#455A64" stroke="#546E7A" stroke-width="${1.2*s}"/>
            <circle cx="${chx + chw/2}" cy="${chy - chh - 5*s}" r="${3*s}"
                    fill="rgba(150,160,170,0.3)"/>
            <circle cx="${chx + chw/2 + 2*s}" cy="${chy - chh - 10*s}" r="${2.5*s}"
                    fill="rgba(150,160,170,0.2)"/>

            <polygon points="${wx},${wy} ${wx + ww},${wy} ${rax},${ray}"
                     fill="url(#roofGrad)" stroke="#c62828" stroke-width="${1.5*s}"
                     stroke-linejoin="round"/>
            <line x1="${rax - 18*s}" y1="${ray + 10*s}" x2="${rax + 18*s}" y2="${ray + 10*s}"
                  stroke="rgba(255,255,255,0.12)" stroke-width="${1*s}"/>
            <line x1="${wx - 3*s}" y1="${wy}" x2="${wx + ww + 3*s}" y2="${wy}"
                  stroke="#7f1010" stroke-width="${3*s}" opacity="0.5"/>

            <rect x="${wx}" y="${wy}" width="${ww}" height="${wh}"
                  rx="${2*s}" fill="url(#wallGrad)"
                  stroke="#546E7A" stroke-width="${1.5*s}"/>

            <rect x="${win1X - 2*s}" y="${winY - 2*s}" width="${winW + 4*s}" height="${winH + 4*s}"
                  rx="${2*s}" fill="#2d3c45" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <rect x="${win1X}" y="${winY}" width="${winW}" height="${winH}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.85"/>
            <line x1="${win1X + winW/2}" y1="${winY}" x2="${win1X + winW/2}" y2="${winY + winH}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>
            <line x1="${win1X}" y1="${winY + winH/2}" x2="${win1X + winW}" y2="${winY + winH/2}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>

            <rect x="${win2X - 2*s}" y="${winY - 2*s}" width="${winW + 4*s}" height="${winH + 4*s}"
                  rx="${2*s}" fill="#2d3c45" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <rect x="${win2X}" y="${winY}" width="${winW}" height="${winH}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.85"/>
            <line x1="${win2X + winW/2}" y1="${winY}" x2="${win2X + winW/2}" y2="${winY + winH}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>
            <line x1="${win2X}" y1="${winY + winH/2}" x2="${win2X + winW}" y2="${winY + winH/2}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>

            <rect x="${doorX}" y="${doorY}" width="${doorW}" height="${doorH}"
                  rx="${2*s}" fill="#506C7F" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <rect x="${doorX + doorW * 0.15}" y="${doorY + 4*s}"
                  width="${doorW * 0.7}" height="${doorH * 0.35}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.6"/>
            <circle cx="${doorX + doorW * 0.75}" cy="${doorY + doorH * 0.62}" r="${1.5*s}"
                    fill="#FCD170" opacity="0.8"/>

            <line x1="${wx + 2*s}" y1="${wy + 4*s}" x2="${wx + 2*s}" y2="${wy + wh - 2*s}"
                  stroke="rgba(255,255,255,0.06)" stroke-width="${1.5*s}"/>
        `;
    }

    _illustrationGrid(cx, cy, r) {
        const s = r / 50;
        const poleH = 72 * s;
        const poleW = 4 * s;
        const poleY = cy - poleH / 2 + 4 * s;
        const poleX = cx;
        const arm1Y = poleY + poleH * 0.22;
        const arm2Y = poleY + poleH * 0.42;
        const armW1 = 44 * s, armW2 = 32 * s;
        const iR = 3 * s;
        return svg`
            <circle cx="${cx}" cy="${cy}" r="${r + 4}" fill="none"
                    stroke="#488fc2" stroke-width="1.2" opacity="0.25"/>

            <polygon points="${poleX - poleW/2},${poleY + poleH}
                             ${poleX + poleW/2},${poleY + poleH}
                             ${poleX + poleW*0.35},${poleY}
                             ${poleX - poleW*0.35},${poleY}"
                     fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${1*s}"/>

            <rect x="${poleX - 8*s}" y="${poleY + poleH - 4*s}"
                  width="${16*s}" height="${4*s}" rx="${2*s}"
                  fill="#5c7a9b" opacity="0.6"/>

            <rect x="${poleX - armW1/2}" y="${arm1Y - 3*s}" width="${armW1}" height="${5*s}"
                  rx="${2*s}" fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${0.8*s}"/>
            <line x1="${poleX}" y1="${arm1Y + 2*s}"
                  x2="${poleX - armW1 * 0.4}" y2="${arm1Y + 14*s}"
                  stroke="#5c7a9b" stroke-width="${2*s}" opacity="0.5"/>
            <line x1="${poleX}" y1="${arm1Y + 2*s}"
                  x2="${poleX + armW1 * 0.4}" y2="${arm1Y + 14*s}"
                  stroke="#5c7a9b" stroke-width="${2*s}" opacity="0.5"/>

            <rect x="${poleX - armW2/2}" y="${arm2Y - 3*s}" width="${armW2}" height="${5*s}"
                  rx="${2*s}" fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${0.8*s}"/>

            <circle cx="${poleX - armW1/2}" cy="${arm1Y}" r="${iR}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <circle cx="${poleX + armW1/2}" cy="${arm1Y}" r="${iR}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <circle cx="${poleX - armW2/2}" cy="${arm2Y}" r="${iR}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <circle cx="${poleX + armW2/2}" cy="${arm2Y}" r="${iR}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>

            <path d="M${poleX - armW1/2},${arm1Y}
                     Q${poleX - armW1*0.7},${arm1Y + 18*s} ${poleX - armW1*0.95 - 15*s},${arm1Y + 12*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.5*s}" opacity="0.6"/>
            <path d="M${poleX + armW1/2},${arm1Y}
                     Q${poleX + armW1*0.7},${arm1Y + 18*s} ${poleX + armW1*0.95 + 15*s},${arm1Y + 12*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.5*s}" opacity="0.6"/>

            <path d="M${poleX - armW2/2},${arm2Y}
                     Q${poleX - armW2*0.65},${arm2Y + 14*s} ${poleX - armW2*0.9 - 12*s},${arm2Y + 9*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.2*s}" opacity="0.5"/>
            <path d="M${poleX + armW2/2},${arm2Y}
                     Q${poleX + armW2*0.65},${arm2Y + 14*s} ${poleX + armW2*0.9 + 12*s},${arm2Y + 9*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.2*s}" opacity="0.5"/>

            <path d="M${cx - 3*s},${arm2Y + 8*s} L${cx - 5*s},${arm2Y + 14*s}
                     L${cx},${arm2Y + 14*s} L${cx},${arm2Y + 20*s}
                     L${cx + 4*s},${arm2Y + 11*s} L${cx},${arm2Y + 11*s} Z"
                  fill="#FCD170" opacity="0.6"/>
        `;
    }

    _illustrationEV(cx, cy, r) {
        const s = r / 44;
        const bw = 22 * s, bh = 36 * s;
        const chargerX = cx - 28 * s, chargerY = cy - bh / 2;
        const carCX = cx + 18 * s, carCY = cy + 4 * s;
        const carW = 52 * s, carH = 22 * s;
        const carX = carCX - carW / 2, carY = carCY - carH / 2;
        const wheelR = 6 * s;
        return svg`
            <circle cx="${cx}" cy="${cy}" r="${r + 4}" fill="none"
                    stroke="#8DC892" stroke-width="1.2" opacity="0.25"/>

            <rect x="${chargerX}" y="${chargerY}" width="${bw}" height="${bh}"
                  rx="${4*s}" fill="#1a2e22" stroke="#8DC892" stroke-width="${1.8*s}" opacity="0.95"/>
            <rect x="${chargerX + 3*s}" y="${chargerY + 4*s}" width="${bw - 6*s}" height="${10*s}"
                  rx="${2*s}" fill="#0a1a12" stroke="#8DC892" stroke-width="${0.8*s}" opacity="0.8"/>
            <text x="${chargerX + bw/2}" y="${chargerY + 4*s + 8*s}"
                  font-family="'Courier New',monospace" font-size="${5.5*s}"
                  fill="#8DC892" text-anchor="middle" opacity="0.8">AC</text>
            <path d="M${chargerX + bw/2 - 3*s},${chargerY + 18*s}
                     L${chargerX + bw/2 - 5*s},${chargerY + 25*s}
                     L${chargerX + bw/2},${chargerY + 25*s}
                     L${chargerX + bw/2},${chargerY + 32*s}
                     L${chargerX + bw/2 + 4*s},${chargerY + 22*s}
                     L${chargerX + bw/2},${chargerY + 22*s} Z"
                  fill="#FCD170" opacity="0.9"/>
            <circle cx="${chargerX + bw - 5*s}" cy="${chargerY + 5*s}" r="${2.2*s}"
                    fill="#8DC892" opacity="0.9">
                <animate attributeName="opacity" values="0.9;0.3;0.9" dur="1.8s" repeatCount="indefinite"/>
            </circle>
            <path d="M${chargerX + bw},${chargerY + bh * 0.55}
                     C${chargerX + bw + 10*s},${chargerY + bh * 0.55}
                       ${carX - 10*s},${carCY}
                       ${carX},${carCY}"
                  fill="none" stroke="#8DC892" stroke-width="${2.5*s}"
                  stroke-linecap="round" opacity="0.7"/>
            <circle cx="${carX}" cy="${carCY}" r="${3*s}"
                    fill="#8DC892" opacity="0.85"/>

            <rect x="${carX + 5*s}" y="${carCY}" width="${carW - 10*s}" height="${carH/2}"
                  rx="${3*s}" fill="url(#carGrad)" stroke="#8DC892" stroke-width="${1.5*s}"/>
            <path d="M${carX + 12*s},${carCY}
                     L${carX + 10*s},${carCY - carH * 0.7}
                     L${carX + 20*s},${carCY - carH * 0.85}
                     L${carX + carW - 18*s},${carCY - carH * 0.85}
                     L${carX + carW - 10*s},${carCY - carH * 0.7}
                     L${carX + carW - 8*s},${carCY} Z"
                  fill="url(#carGrad)" stroke="#8DC892" stroke-width="${1.5*s}"/>
            <path d="M${carX + 13*s},${carCY - 2*s}
                     L${carX + 11*s},${carCY - carH * 0.62}
                     L${carX + 22*s},${carCY - carH * 0.78}
                     L${carX + 24*s},${carCY - 2*s} Z"
                  fill="rgba(100,200,200,0.22)" stroke="rgba(100,200,200,0.4)" stroke-width="${0.8*s}"/>
            <path d="M${carX + carW - 14*s},${carCY - 2*s}
                     L${carX + carW - 22*s},${carCY - 2*s}
                     L${carX + carW - 20*s},${carCY - carH * 0.78}
                     L${carX + carW - 12*s},${carCY - carH * 0.62} Z"
                  fill="rgba(100,200,200,0.22)" stroke="rgba(100,200,200,0.4)" stroke-width="${0.8*s}"/>
            <circle cx="${carX + 14*s}" cy="${carCY + carH/2 - 1*s}" r="${wheelR}"
                    fill="#1a2525" stroke="#8DC892" stroke-width="${2*s}"/>
            <circle cx="${carX + 14*s}" cy="${carCY + carH/2 - 1*s}" r="${wheelR * 0.4}"
                    fill="#8DC892" opacity="0.5"/>
            <circle cx="${carX + carW - 14*s}" cy="${carCY + carH/2 - 1*s}" r="${wheelR}"
                    fill="#1a2525" stroke="#8DC892" stroke-width="${2*s}"/>
            <circle cx="${carX + carW - 14*s}" cy="${carCY + carH/2 - 1*s}" r="${wheelR * 0.4}"
                    fill="#8DC892" opacity="0.5"/>
            <ellipse cx="${carX + carW - 7*s}" cy="${carCY + carH/2 - 6*s}"
                     rx="${4*s}" ry="${2.5*s}"
                     fill="#FFF9C4" opacity="0.6"/>
        `;
    }

    // ══════════════════════════════════════════════════════════════════
    //  DYNAMIC FRAGMENT HELPERS (all pure functions, no DOM mutation)
    // ══════════════════════════════════════════════════════════════════

    /**
     * K-Flow inspired multi-layer spark effect for a single flow group.
     * Returns an svg fragment — caller wraps in a <g> with opacity binding.
     * Particle delays are deterministic (i/count*duration) so re-renders
     * don't restart SMIL animations.
     */
    _renderFlow(reverse, color, durationSec, pathId, pathD, count) {
        const dur = durationSec.toFixed(1);
        const cycle = 28;
        const toOffset = reverse ? String(cycle) : String(-cycle);
        const reverseAttrs = reverse ? { kp: '1;0', kt: '0;1' } : null;

        const particles = [];
        for (let i = 0; i < count; i++) {
            const delay = (i / count) * durationSec;
            const begin = `-${delay.toFixed(2)}s`;
            particles.push(svg`
                <circle r="5" fill="${color}" opacity="0.12">
                    <animateMotion dur="${dur}s" repeatCount="indefinite" calcMode="paced"
                                   keyPoints=${reverseAttrs ? reverseAttrs.kp : nothing}
                                   keyTimes=${reverseAttrs ? reverseAttrs.kt : nothing}
                                   begin="${begin}">
                        <mpath href="#${pathId}"/>
                    </animateMotion>
                </circle>
                <circle r="2.5" fill="${color}" opacity="0.95">
                    <animateMotion dur="${dur}s" repeatCount="indefinite" calcMode="paced"
                                   keyPoints=${reverseAttrs ? reverseAttrs.kp : nothing}
                                   keyTimes=${reverseAttrs ? reverseAttrs.kt : nothing}
                                   begin="${begin}">
                        <mpath href="#${pathId}"/>
                    </animateMotion>
                </circle>
                <circle r="1" fill="rgba(255,255,255,0.9)" opacity="0.85">
                    <animateMotion dur="${dur}s" repeatCount="indefinite" calcMode="paced"
                                   keyPoints=${reverseAttrs ? reverseAttrs.kp : nothing}
                                   keyTimes=${reverseAttrs ? reverseAttrs.kt : nothing}
                                   begin="${begin}">
                        <mpath href="#${pathId}"/>
                    </animateMotion>
                </circle>
            `);
        }

        return svg`
            <path d="${pathD}" fill="none" stroke="${color}" stroke-width="5"
                  stroke-dasharray="8,${cycle - 8}" opacity="0.2" stroke-linecap="round">
                <animate attributeName="stroke-dashoffset" from="0" to="${toOffset}"
                         dur="${dur}s" repeatCount="indefinite"/>
            </path>
            <path d="${pathD}" fill="none" stroke="rgba(255,255,255,0.5)" stroke-width="1.2"
                  stroke-dasharray="6,${cycle - 6}" opacity="0.45" stroke-linecap="round">
                <animate attributeName="stroke-dashoffset" from="0" to="${toOffset}"
                         dur="${dur}s" repeatCount="indefinite"/>
            </path>
            <path d="${pathD}" fill="none" stroke="${color}" stroke-width="2.5"
                  stroke-dasharray="8,${cycle - 8}" opacity="0.65" stroke-linecap="round">
                <animate attributeName="stroke-dashoffset" from="0" to="${toOffset}"
                         dur="${dur}s" repeatCount="indefinite"/>
            </path>
            ${particles}
        `;
    }

    /**
     * Spark wave <path> in <defs> — referenced by the spark particles' mpath.
     */
    _sparkWavePath(L) {
        const sx = this._sunPtX, sy = this._sunPtY;
        const tx = L.S.cx, ty = L.S.cy - L.S.r;
        const totalDx = tx - sx, totalDy = ty - sy;
        const dist = Math.sqrt(totalDx * totalDx + totalDy * totalDy);
        const waves = Math.max(2, Math.round(dist / 30));
        const solar = this._val('solar_power');
        const amp = 6 + Math.min(8, solar / 1000);
        const angle = Math.atan2(totalDy, totalDx);
        const perpX = -Math.sin(angle), perpY = Math.cos(angle);
        const steps = waves * 8;
        let d = `M${sx.toFixed(1)},${sy.toFixed(1)}`;
        for (let i = 1; i <= steps; i++) {
            const frac = i / steps;
            const cx2 = sx + totalDx * frac;
            const cy2 = sy + totalDy * frac;
            const wave = Math.sin(frac * waves * Math.PI * 2) * amp;
            d += ` L${(cx2 + perpX * wave).toFixed(1)},${(cy2 + perpY * wave).toFixed(1)}`;
        }
        return svg`<path id="spark-wave" d="${d}" fill="none"
                         stroke="rgba(255,200,60,0.12)" stroke-width="2.5" stroke-linecap="round"
                         filter="url(#glowSun)"/>`;
    }

    /**
     * Sun-to-solar spark particles. Random properties are memoized in
     * _sunSparkProps so re-renders don't restart SMIL animations.
     */
    _renderSunSpark(solar) {
        const baseDur = 12 - 7 * Math.min(1, solar / 10000);
        const count = 3 + Math.floor(Math.min(3, solar / 3000));
        const sig = `${baseDur.toFixed(0)}:${count}`;
        if (this._sunSparkSig !== sig) {
            this._sunSparkSig = sig;
            this._sunSparkProps = [];
            for (let i = 0; i < count; i++) {
                this._sunSparkProps.push({
                    kind: i % 2 === 0 ? 'gold' : 'white',
                    r: 1.5 + Math.random() * 2,
                    opacity: 0.4 + Math.random() * 0.5,
                    dur: baseDur * (0.7 + Math.random() * 0.6),
                    delay: Math.random() * baseDur,
                });
            }
        }
        return this._sunSparkProps.map(p => p.kind === 'gold' ? svg`
            <circle r="${p.r.toFixed(1)}" fill="rgba(255,220,60,${p.opacity.toFixed(2)})" filter="url(#glowSun)">
                <animateMotion dur="${p.dur.toFixed(1)}s" repeatCount="indefinite" calcMode="paced"
                               begin="-${p.delay.toFixed(1)}s">
                    <mpath href="#spark-wave"/>
                </animateMotion>
            </circle>
        ` : svg`
            <circle r="${(p.r * 0.6).toFixed(1)}" fill="rgba(255,255,230,${p.opacity.toFixed(2)})">
                <animateMotion dur="${p.dur.toFixed(1)}s" repeatCount="indefinite" calcMode="paced"
                               begin="-${p.delay.toFixed(1)}s">
                    <mpath href="#spark-wave"/>
                </animateMotion>
            </circle>
        `);
    }

    /**
     * Top-3 controllable devices strip (desktop only).
     * Returns an svg fragment positioned bottom-right of the diagram.
     */
    _renderDeviceStrip(H) {
        const devicesEid = this._eid('controllable_devices_count');
        const devicesEntity = devicesEid ? this._hass?.states[devicesEid] : undefined;
        if (!devicesEntity?.attributes?.devices) return nothing;

        const devices = Object.entries(devicesEntity.attributes.devices)
            .filter(([, info]) => info.device_type !== 'ev_charger')
            .map(([id, info]) => {
                const powerEntity = info.power_entity ? this._hass.states[info.power_entity] : null;
                const power = powerEntity ? parseFloat(powerEntity.state) || 0 : (info.current_power || 0);
                return { id, ...info, power };
            })
            .sort((a, b) => b.power - a.power)
            .slice(0, 3);

        if (!devices.length) return nothing;

        const F = "'Segoe UI','Roboto',sans-serif";
        const colors = SEM_DEVICE_COLORS;
        const baseX = 540, baseY = 310;
        const spacing = 50;

        return devices.map((dev, idx) => {
            let name = (dev.name || dev.id).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            if (name.length > 22) name = name.substring(0, 21) + '…';
            const color = colors[idx % colors.length];
            const isOn = dev.is_on || dev.power > 5;
            const cy = baseY + idx * spacing;
            const cx = baseX;
            const pathD = `M${H.cx + H.r},${H.cy + 10 + idx * 8} C${H.cx + H.r + 40},${H.cy + 30 + idx * 15} ${cx - 30},${cy - 10} ${cx - 16},${cy}`;
            const flowDot = dev.power > 5 ? svg`
                <path id="dev-path-${idx}" d="${pathD}" fill="none" stroke="none"/>
                <circle r="1.5" fill="${color}" opacity="0.8">
                    <animateMotion dur="${semCalcDuration(dev.power).toFixed(1)}s" repeatCount="indefinite" calcMode="paced">
                        <mpath href="#dev-path-${idx}"/>
                    </animateMotion>
                </circle>
            ` : nothing;
            const r = 14;
            return svg`
                <path d="${pathD}" fill="none" stroke="${color}" stroke-width="1"
                      stroke-dasharray="3,5" opacity="${isOn ? 0.3 : 0.1}"/>
                ${flowDot}
                <circle cx="${cx}" cy="${cy}" r="${r}" fill="rgba(128,128,128,${isOn ? 0.06 : 0.02})"
                        stroke="${color}" stroke-width="0.8" opacity="${isOn ? 0.7 : 0.3}"/>
                <g transform="translate(${cx},${cy}) scale(0.7)" stroke="${color}" fill="none"
                   opacity="${isOn ? 0.6 : 0.25}" stroke-width="1.3" stroke-linecap="round">
                    ${this._deviceIcon(dev.device_type, dev.name || dev.id)}
                </g>
                <text x="${cx + r + 6}" y="${cy - 2}" font-family="${F}" font-size="10"
                      font-weight="500" fill="${color}" opacity="0.7">${name}</text>
                <text x="${cx + r + 6}" y="${cy + 11}" font-family="${F}" font-size="10"
                      font-weight="700" fill="${color}" opacity="${isOn ? 0.9 : 0.4}">${semFormatPower(dev.power)}</text>
            `;
        });
    }

    _glowFilter(id, color, blur) {
        return svg`<filter id="${id}" x="-35%" y="-35%" width="170%" height="170%">
            <feGaussianBlur stdDeviation="${blur}" result="blur"/>
            <feFlood flood-color="${color}" flood-opacity="0.28"/>
            <feComposite in2="blur" operator="in"/>
            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>`;
    }

    _showMoreInfo(suffix) {
        const entityId = this._eid(suffix);
        if (!entityId) return;  // #455: unmapped key in entities mode — no-op
        this.dispatchEvent(new CustomEvent('hass-more-info', {
            bubbles: true, composed: true,
            detail: { entityId },
        }));
    }

    // ── Layout ──
    _getLayout() {
        if (this._compact) {
            // viewBox 0 0 400 680 — vertical: Solar→Inv→Batt/Grid→House+EV
            return {
                vb: '0 0 400 680',
                S:  { cx: 200, cy: 100, r: 44, labelY: 154 },
                I:  { cx: 200, cy: 232, r: 20 },
                B:  { cx: 100, cy: 360, r: 44, labelY: 414 },
                G:  { cx: 300, cy: 360, r: 44, labelY: 414 },
                H:  { cx: 200, cy: 540, r: 48, labelY: 598 },
                E:  { cx: 84,  cy: 555, r: 34, labelY: 598 },
                paths: {
                    solar:   'M200,144 L200,212',
                    battery: 'M188,242 C155,278 120,315 100,316',
                    grid:    'M212,242 C245,278 280,315 300,316',
                    home:    'M200,252 C200,390 200,460 200,492',
                    ev:      'M200,252 C200,400 140,490 84,521',
                },
                sunArc:     'M30,68 Q200,6 370,68',
                sunX: 200, sunY: 20, sunR: 12,
                sunRisingX: 40, sunSettingX: 360, sunLabelY: 76,
                starX: [60, 120, 280, 330, 180],
                starY: [20, 12, 18, 24, 8],
                font: { label: 11, value: 15, sub: 10 },
                statusY: 660,
                wmX: 390, wmY: 676,
            };
        }
        // viewBox 0 0 700 510 — desktop left-to-right flow
        return {
            vb: '0 0 700 510',
            S:  { cx: 85,  cy: 140, r: 48, labelY: 200 },
            I:  { cx: 220, cy: 200, r: 20 },
            E:  { cx: 150, cy: 390, r: 42, labelY: 442 },
            B:  { cx: 340, cy: 390, r: 48, labelY: 448 },
            H:  { cx: 400, cy: 230, r: 52, labelY: 292 },
            G:  { cx: 570, cy: 140, r: 46, labelY: 198 },
            paths: {
                solar:   'M118,148 C158,165 192,188 208,200',
                home:    'M242,198 C300,200 350,210 360,218',
                battery: 'M228,215 C260,280 320,340 338,342',
                grid:    'M232,188 C320,130 450,110 524,130',
                ev:      'M210,215 C180,275 162,330 150,348',
            },
            sunArc:     'M20,52 Q330,2 640,52',
            sunX: 330, sunY: 12, sunR: 12,
            sunRisingX: 28, sunSettingX: 632, sunLabelY: 60,
            starX: [100, 200, 450, 550, 330],
            starY: [20, 12, 15, 28, 8],
            font: { label: 11, value: 16, sub: 10 },
            statusY: 495,
            wmX: 690, wmY: 506,
        };
    }

    _deviceIcon(type, name) {
        const n = (name || '').toLowerCase();
        const t = (type || '').toLowerCase();
        if (t === 'ev_charger' || n.includes('keba') || n.includes('charger') || n.includes('wallbox'))
            return svg`<rect x="-5" y="-9" width="10" height="14" rx="2"/>
                       <path d="M-1.5,-3.5 L0,1.5 L1.5,-3.5"/>
                       <line x1="0" y1="5" x2="0" y2="9"/>`;
        if (n.includes('heiz') || n.includes('heat') || n.includes('warm') || n.includes('boiler'))
            return svg`<path d="M-3,-9 C-3,-3 3,-3 3,-9"/>
                       <path d="M-3,-2 C-3,4 3,4 3,-2"/>
                       <path d="M-3,5 C-3,9 3,9 3,5"/>`;
        if (n.includes('wash') || n.includes('spül') || n.includes('geschirr') || n.includes('wasch'))
            return svg`<circle r="9"/><circle r="4.5"/><circle r="1.3" fill="currentColor" opacity="0.3" stroke="none"/>`;
        if (n.includes('pool') || n.includes('pump'))
            return svg`<circle r="7"/><path d="M-5,0 L5,0 M0,-5 L0,5" opacity="0.5"/>`;
        if (n.includes('klima') || n.includes('ac') || n.includes('cool') || n.includes('air'))
            return svg`<rect x="-9" y="-5" width="18" height="10" rx="2"/>
                       <path d="M-5,5 C-5,9 -2,9 -2,5" fill="none"/>
                       <path d="M2,5 C2,9 5,9 5,5" fill="none"/>`;
        if (n.includes('light') || n.includes('licht') || n.includes('lamp'))
            return svg`<path d="M-4,-9 C-7,-2 -2,3 -1.5,5 L1.5,5 C2,3 7,-2 4,-9 C2,-12 -2,-12 -4,-9Z"/>
                       <line x1="-1.5" y1="6" x2="1.5" y2="6"/>`;
        return svg`<path d="M-2.5,-9 L-2.5,0 L-5,0 L0,9 L0,0 L2.5,0 L-2.5,-9Z"/>`;
    }

    getCardSize() { return 7; }

    static getStubConfig() {
        return { entity_prefix: 'sensor.sem_' };
    }
}

semDefineCard('sem-system-diagram-card', SEMSystemDiagramCard, {
    type: 'sem-system-diagram-card',
    name: 'SEM System Diagram',
    description: 'Power flow visualization with inline SVG illustrations for each energy component',
});
