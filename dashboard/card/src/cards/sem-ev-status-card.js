/**
 * SEM EV Status Card — LitElement migration
 *
 * Animated charging visualization with glow ring, lightning bolt,
 * and key EV metrics. When multiple chargers are configured,
 * renders per-charger sections with intelligence and settings.
 *
 * Config:
 *   type: custom:sem-ev-status-card
 *   entity_prefix: sensor.sem_   # default
 */

import { SEMLitBase, html, css, svg, nothing } from '../base/sem-lit-base.js';
import { semTheme, semFormatPower, semGetCurrency, semDefineCard } from '../base/sem-shared.js';
import { resolveChargerSoc } from '../util/charger-soc.js';

const DEFAULT_PREFIX = 'sensor.sem_';
const CHARGER_COLORS = ['#8DC892', '#64B5F6'];

class SEMEVStatusCard extends SEMLitBase {
    static get properties() {
        return {
            ...super.properties,
            _showHelp: { state: true },
        };
    }

    constructor() {
        super();
        this._chargers = [];
        this._lastStateCount = 0;
        this._showHelp = false;
        // #541: this card's plan strip ("next 12h from now") computes its time
        // axis from a per-render `now`. It re-renders on EV state changes, but
        // snap it fresh on app resume / tab focus so the axis can't lag after a
        // long background.
        this._boundVisibility = () => { if (!document.hidden) this.requestUpdate(); };
    }

    connectedCallback() {
        super.connectedCallback();
        document.addEventListener('visibilitychange', this._boundVisibility);
    }

    disconnectedCallback() {
        super.disconnectedCallback();
        document.removeEventListener('visibilitychange', this._boundVisibility);
    }

    _toggleHelp() {
        this._showHelp = !this._showHelp;
    }

    /**
     * Override hass setter: dynamic charger discovery + per-charger key comparison.
     */
    set hass(hass) {
        const old = this._hass;
        this._hass = hass;

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

        // Re-discover chargers when entity count changes
        const stateCount = Object.keys(hass.states).length;
        if (stateCount !== this._lastStateCount) {
            this._lastStateCount = stateCount;
            const chargers = [];
            for (const eid of Object.keys(hass.states)) {
                // #356 — per-charger flow sensors (sensor.sem_charger_<id>_flow_*_power)
                // are NOT chargers. The discovery regex below greedily matched them
                // as separate ids, spawning "Solar → EV", "Grid → EV", "Battery → EV"
                // ghost sections per real charger. Filter them out at the source.
                if (eid.includes('_flow_')) continue;
                const match = eid.match(/^sensor\.sem_charger_(.+)_power$/);
                if (match) chargers.push(match[1]);
            }
            this._chargers = chargers;
        }

        const prefix = this._config?.entity_prefix || DEFAULT_PREFIX;

        // Build reactivity key
        let key = [
            'ev_connected', 'ev_charging', 'ev_power', 'calculated_current',
            'session_energy', 'session_solar_share', 'session_cost',
            'daily_ev_energy', 'energy_ev_solar_percentage', 'charging_state',
        ].map(s => {
            const pfx = (s === 'ev_connected' || s === 'ev_charging')
                ? 'binary_sensor.sem_' : prefix;
            return hass.states[`${pfx}${s}`]?.state || '';
        }).join(',');

        // Per-charger reactivity
        if (this._chargers.length >= 1) {
            key += '|' + this._chargers.map(id => [
                `charger_${id}_power`, `charger_${id}_session_energy`,
                `charger_${id}_session_energy_external`,
                `charger_${id}_daily_energy`, `charger_${id}_session_solar_share`,
                `charger_${id}_estimated_soc`, `charger_${id}_vehicle_soc`,
                `charger_${id}_commanded_current`,
                // (#440) charger_*_nights_until_charge / _charge_needed removed
            ].map(s => hass.states[`${prefix}${s}`]?.state || '').join(':')).join('|');

            key += '|' + this._chargers.map(id =>
                hass.states[`switch.sem_charger_${id}_night_charging`]?.state || ''
            ).join(':');

            // Deadline (#246) + tariff (#247) entities
            key += '|' + this._chargers.map(id => [
                hass.states[`time.sem_charger_${id}_target_time`]?.state || '',
                hass.states[`switch.sem_charger_${id}_tariff_optimized`]?.state || '',
            ].join(':')).join('|');
            const _cs = hass.states[`${prefix}charging_state`]?.attributes || {};
            key += '|' + [_cs.ev_tariff_waiting, _cs.ev_deadline_reachable,
                _cs.ev_next_cheap_window].join(':');

            key += '|' + this._chargers.map(id =>
                hass.states[`number.sem_charger_${id}_daily_ev_target`]?.state || ''
            ).join(':');

            // Charge Target range (#245): type, SOC floor, both Max ceilings, capacity
            key += '|' + this._chargers.map(id => [
                hass.states[`select.sem_charger_${id}_ev_target_type`]?.state || '',
                hass.states[`number.sem_charger_${id}_target_soc`]?.state || '',
                hass.states[`number.sem_charger_${id}_daily_ev_target_max`]?.state || '',
                hass.states[`number.sem_charger_${id}_target_soc_max`]?.state || '',
                hass.states[`number.sem_charger_${id}_ev_battery_capacity_kwh`]?.state || '',
                hass.states[`number.sem_charger_${id}_ev_kwh_per_100km`]?.state || '',
            ].join(':')).join('|');
            key += '|' + (hass.states[`${prefix}ev_remaining_range`]?.state || '');
        }

        key += '|' + this._localizeReady + '|' + this._lang;

        if (key === this._lastKey && !localeChanged) return;
        this._lastKey = key;
        this._scheduleUpdate();
    }

    get hass() {
        return this._hass;
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;
    }

    _binaryState(suffix) {
        const e = this._hass?.states[`binary_sensor.sem_${suffix}`];
        return e?.state === 'on';
    }

    _val(suffix, fallback = 0) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _valStr(suffix) {
        const e = this._hass?.states[`${this._prefix}${suffix}`];
        return e?.state || '';
    }

    _entityVal(entityId, fallback = 0) {
        const frozen = this._frozenEntities[entityId];
        if (frozen) return frozen.value;
        const e = this._hass?.states[entityId];
        if (!e || e.state === 'unavailable' || e.state === 'unknown') return fallback;
        return parseFloat(e.state) ?? fallback;
    }

    _fmt(val, decimals = 1) {
        if (val == null || isNaN(val)) return '\u2014';
        return val.toFixed(decimals);
    }

    _chargerName(id) {
        const entity = this._hass?.states[`${this._prefix}charger_${id}_power`];
        let name = id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        if (entity?.attributes?.friendly_name) {
            name = entity.attributes.friendly_name
                .replace(/^SEM\s+/i, '')
                .replace(/\s+Power$/i, '');
        }
        return name;
    }

    _renderSocGauge(soc, isEstimate = false) {
        // An ESTIMATED SOC (no vehicle SOC sensor - dead-reckoned from
        // delivered kWh, taper-anchored) is marked with ~ so nobody mistakes
        // it for the car's own reading (repeated confusion source).
        const socVal = soc != null ? Math.max(0, Math.min(100, soc)) : 0;
        const socColor = socVal > 60 ? '#8DC892' : socVal > 30 ? '#ff9800' : '#f06292';
        const socFill = Math.max(2, (socVal / 100) * 52);

        return html`
            <svg viewBox="0 0 44 76" width="44" height="76">
                <rect x="14" y="0" width="16" height="5" rx="2" fill="rgba(255,255,255,0.15)"/>
                <rect x="6" y="4" width="32" height="60" rx="4"
                    fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="2"/>
                <rect x="9" y="${7 + (52 - socFill)}" width="26" height="${socFill}" rx="2"
                    fill="${socColor}" opacity="0.7"/>
                <text x="22" y="40" text-anchor="middle"
                    fill="white" font-size="14" font-weight="700"
                    font-family="'Segoe UI','Roboto',sans-serif"
                    opacity="0.95">
                    ${soc != null ? (isEstimate ? '~' : '') + Math.round(soc) + '%' : '\u2014'}
                </text>
            </svg>
        `;
    }

    /**
     * 12h EV plan strip (#282): a thin horizontal timeline rendered from the
     * plan rows on sem_charging_state. Walks the plan rows and paints a
     * contiguous bar segment per EV state (idle / wait / charging / done)
     * plus expensive-window tinting overlay. Self-renders nothing when
     * there's no plan to show (no charger configured, Min already met, etc.).
     *
     * #464: each charger section passes its id so the strip renders THIS
     * charger's plan (``per_charger_plans[id]``) — two chargers with
     * different targets/deadlines used to show an identical strip because
     * only the fleet-level (primary charger) plan existed. Fleet plan kept
     * as the fallback for coordinators that predate the attribute.
     */
    _renderPlanStrip(chargerId) {
        const cs = this._hass?.states['sensor.sem_charging_state'];
        const perPlan = chargerId
            ? cs?.attributes?.per_charger_plans?.[chargerId] : null;
        const usingPerPlan = Array.isArray(perPlan) && perPlan.length > 0;
        const plan = usingPerPlan ? perPlan : (cs?.attributes?.today_plan || []);
        if (!Array.isArray(plan) || plan.length < 2) return nothing;
        // Only show when there's at least one EV-specific row — otherwise the
        // info value is too thin to justify the row.
        const evKinds = new Set(['ev_charge_start','ev_min_reached','ev_deadline']);
        if (!plan.some(r => evKinds.has(r.kind))) return nothing;

        const now = Date.now();
        const horizon = 12 * 3600 * 1000;  // 12h window
        const end = now + horizon;
        const w = 100;  // viewBox units (percent-like)
        const xOf = (ts) => Math.max(0, Math.min(w, ((ts - now) / horizon) * w));

        // Build EV state segments by walking the plan. State machine:
        //   start         → idle
        //   night_open    → wait (if tariff_waiting) else charging
        //   ev_charge_start → charging
        //   ev_min_reached  → done
        //   ev_deadline     → end of horizon coverage
        const evRows = plan.filter(r => ['now','night_open','ev_charge_start',
            'ev_min_reached','ev_deadline'].includes(r.kind));
        evRows.sort((a,b) => new Date(a.when) - new Date(b.when));
        // Waiting-for-cheap is a per-charger fact: a per-charger plan
        // marks it on the ev_charge_start row itself (the composer sets
        // detail=plan_ev_charge_tariff only on the wait path). The fleet
        // attribute is primary-charger-scoped — only trust it when we're
        // rendering the fleet fallback plan.
        const tariffWait = usingPerPlan
            ? plan.some(r => r.kind === 'ev_charge_start'
                          && r.detail === 'plan_ev_charge_tariff')
            : !!cs?.attributes?.ev_tariff_waiting;
        const segments = [];
        let cursor = now;
        let state = 'idle';
        for (const r of evRows) {
            const t = new Date(r.when).getTime();
            // Clamp each transition to the 12h horizon. Without the clamp a
            // plan whose first EV event is beyond the window (morning view,
            // night charge scheduled for e.g. 21:35 when now+12h is 19:56)
            // advanced cursor PAST end, so the idle-fill below was skipped
            // and the strip rendered EMPTY instead of a full "nothing
            // scheduled in the next 12h" idle bar. Clamping keeps cursor
            // inside the window so the fill always covers the visible time.
            const segEnd = Math.min(t, end);
            if (segEnd > cursor) segments.push({s: cursor, e: segEnd, state});
            cursor = Math.max(cursor, segEnd);
            if (r.kind === 'night_open') state = tariffWait ? 'wait' : 'charging';
            else if (r.kind === 'ev_charge_start') state = 'charging';
            else if (r.kind === 'ev_min_reached') state = 'done';
            else if (r.kind === 'ev_deadline') state = 'done';
        }
        if (cursor < end) segments.push({s: cursor, e: end, state});

        // Tinting overlay: expensive blocks darken the strip + cheap blocks lighten
        const overlays = [];
        for (const r of plan) {
            const t = new Date(r.when).getTime();
            if (r.kind === 'expensive_start' && t < end) {
                // detail string holds end HH:MM — find end time by walking
                const endHHMM = r.values?.end;
                if (endHHMM) {
                    const [hh, mm] = endHHMM.split(':').map(Number);
                    const endDt = new Date(t); endDt.setHours(hh, mm, 0, 0);
                    if (endDt.getTime() < t) endDt.setDate(endDt.getDate()+1);
                    overlays.push({s: t, e: Math.min(endDt.getTime(), end),
                                   kind: 'expensive'});
                }
            } else if (r.kind === 'cheap_start' && t < end) {
                const endHHMM = r.values?.end;
                if (endHHMM) {
                    const [hh, mm] = endHHMM.split(':').map(Number);
                    const endDt = new Date(t); endDt.setHours(hh, mm, 0, 0);
                    if (endDt.getTime() < t) endDt.setDate(endDt.getDate()+1);
                    overlays.push({s: t, e: Math.min(endDt.getTime(), end),
                                   kind: 'cheap'});
                }
            }
        }

        const stateColor = (s) => ({
            idle:     '#566072',
            wait:     '#8353d1',
            charging: '#8DC892',
            done:     '#4db6ac',
        })[s] || '#566072';
        // Tariff overlay colours are deliberately distinct from the segment
        // palette — cheap is a deeper leaf-green so it can't be mistaken for
        // the 'charging' sea-green it used to share (#464 legend feedback).
        const overlayColor = (k) => k === 'cheap' ? '#43a047' : '#f06292';

        // Hourly ticks for time labels (every 3h)
        const _tz = this._hass?.config?.time_zone || undefined;
        const ticks = [];
        for (let h = 0; h <= 12; h += 3) {
            const t = now + h * 3600 * 1000;
            const label = new Date(t).toLocaleTimeString([],
                { hour: '2-digit', minute: '2-digit', timeZone: _tz });
            ticks.push({x: xOf(t), label});
        }

        return html`
            <div class="plan-strip" title="${this._t('today_plan_title')} (12h)">
                <div class="strip-title">
                    <ha-icon icon="mdi:chart-timeline" style="--mdc-icon-size:13px;color:#5BC8D8"></ha-icon>
                    <span>${this._t('plan_strip_title')}</span>
                </div>
                <svg viewBox="0 0 ${w} 16" preserveAspectRatio="none" class="strip-svg">
                    ${segments.map(s => svg`
                        <rect x="${xOf(s.s)}" y="5" width="${xOf(s.e)-xOf(s.s)}"
                              height="10" fill="${stateColor(s.state)}" />
                    `)}
                    ${overlays.map(o => svg`
                        <rect x="${xOf(o.s)}" y="0" width="${xOf(o.e)-xOf(o.s)}"
                              height="3" fill="${overlayColor(o.kind)}"
                              opacity="0.75" />
                    `)}
                </svg>
                <div class="strip-axis">
                    ${ticks.map(t => html`
                        <span class="tick" style="left: ${t.x}%">${t.label}</span>
                    `)}
                </div>
                <div class="strip-legend">
                    <span><i style="background:${stateColor('idle')}"></i>${this._t('plan_strip_idle')}</span>
                    <span><i style="background:${stateColor('wait')}"></i>${this._t('plan_strip_wait')}</span>
                    <span><i style="background:${stateColor('charging')}"></i>${this._t('plan_strip_charging')}</span>
                    <span><i style="background:${stateColor('done')}"></i>${this._t('plan_strip_done')}</span>
                    <span><i class="line" style="background:${overlayColor('cheap')}"></i>${this._t('plan_strip_cheap')}</span>
                    <span><i class="line" style="background:${overlayColor('expensive')}"></i>${this._t('plan_strip_expensive')}</span>
                </div>
                ${this._showHelp ? html`
                    <div class="setting-help strip-help">${this._t('plan_strip_help')}</div>
                ` : nothing}
            </div>
        `;
    }

    /**
     * Dual-handle charge-target range slider (#245).
     * Min handle = guaranteed (night/grid) floor; Max handle = solar ceiling.
     * Right edge (Max == scale max) = "full" (charge freely from sun).
     */
    _renderRangeSlider(minEntityId, maxEntityId, isSoc) {
        const minEnt = this._hass?.states[minEntityId];
        const maxEnt = this._hass?.states[maxEntityId];
        const unit = isSoc ? '%' : ' kWh';
        const fmt = (v) => isSoc ? String(Math.round(v)) : this._fmt(v, v % 1 === 0 ? 0 : 1);

        // Fall back to a single editable value if the Max entity isn't available.
        if (!minEnt || !maxEnt) {
            const v = this._entityVal(minEntityId, isSoc ? 80 : 10);
            return html`<div class="ct-row">
                <span class="ct-label">${this._t('charge_to')}</span>
                <span class="ct-ctl"><span class="ct-val clickable"
                    @click=${() => this.dispatchEvent(new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId: minEntityId } }))}
                >${fmt(v)}${unit}</span></span></div>`;
        }

        const scaleMin = Math.min(parseFloat(minEnt.attributes.min ?? 0), parseFloat(maxEnt.attributes.min ?? 0));
        const scaleMax = Math.max(parseFloat(minEnt.attributes.max ?? 100), parseFloat(maxEnt.attributes.max ?? 100));
        const span = (scaleMax - scaleMin) || 1;
        let minVal = this._entityVal(minEntityId, isSoc ? 80 : 10);
        let maxVal = this._entityVal(maxEntityId, 100);
        if (maxVal < minVal) maxVal = minVal;
        const minPct = ((minVal - scaleMin) / span) * 100;
        const maxPct = ((maxVal - scaleMin) / span) * 100;
        const atFull = maxVal >= scaleMax - 1e-6;
        // #355: split affordance for handles that VISUALLY overlap.
        // The threshold is the larger of one step OR 2% of the slider
        // span — kWh mode has step=0.5 over a 0-200 span (0.25% per
        // step) so users routinely land both handles within 0.25% of
        // each other yet visually identical. SOC % mode has step=5
        // over a 50-100 span (10% per step) so one step IS visible
        // separation. Using percent-of-scale instead of raw value
        // makes the tolerance unit-agnostic and the post-tap result
        // always visually separated.
        const stepNudge = parseFloat(
            this._hass?.states[minEntityId]?.attributes?.step,
        ) || (scaleMax > 50 ? 1 : 5);
        const minVisualGap = Math.max(stepNudge, (scaleMax - scaleMin) * 0.02);
        const stacked = (maxVal - minVal) < minVisualGap - 1e-6;

        return html`
            <div class="range-wrap">
                <div class="range-labels">
                    <span>${this._t('at_least')} <b style="color:#8DC892">${fmt(minVal)}${unit}</b></span>
                    <span>${this._t('up_to')} <b style="color:#ff9800">${atFull ? this._t('full') : fmt(maxVal) + unit}</b></span>
                </div>
                <div class="range-track">
                    <div class="range-fill" style="left:${minPct}%;width:${Math.max(0, maxPct - minPct)}%"></div>
                    <div class="range-handle range-handle-min" style="left:${minPct}%"
                        @pointerdown=${(e) => this._rangeHandleStart(e, 'min', minEntityId, maxEntityId, scaleMin, scaleMax)}></div>
                    <div class="range-handle range-handle-max" style="left:${maxPct}%"
                        @pointerdown=${(e) => this._rangeHandleStart(e, 'max', minEntityId, maxEntityId, scaleMin, scaleMax)}></div>
                    ${stacked ? html`
                        <span class="range-split"
                              style="left:${minPct}%"
                              title="${this._t('separate_handles')}"
                              @click=${(ev) => {
                                  ev.stopPropagation();
                                  // Drop Min so the post-action visual
                                  // gap is at least ``minVisualGap`` —
                                  // matches the same threshold used by
                                  // ``stacked`` so the icon reliably
                                  // disappears after one tap. If Min
                                  // can't drop (already at the floor),
                                  // push Max up by the same amount.
                                  const target = maxVal - minVisualGap;
                                  if (target >= scaleMin) {
                                      this._setNumber(minEntityId, target);
                                  } else {
                                      this._setNumber(
                                          maxEntityId,
                                          Math.min(scaleMax, minVal + minVisualGap),
                                      );
                                  }
                              }}>
                            <ha-icon icon="mdi:arrow-split-vertical"
                                     style="--mdc-icon-size:14px"></ha-icon>
                        </span>
                    ` : nothing}
                </div>
            </div>`;
    }

    _rangeHandleStart(e, which, minEntityId, maxEntityId, scaleMin, scaleMax) {
        e.stopPropagation();
        e.preventDefault();
        const track = e.currentTarget.closest('.range-track');
        if (!track) return;
        const entId = which === 'min' ? minEntityId : maxEntityId;
        const otherId = which === 'min' ? maxEntityId : minEntityId;
        const ent = this._hass?.states[entId];
        const step = parseFloat(ent?.attributes?.step) || (scaleMax > 50 ? 1 : 0.5);
        const span = (scaleMax - scaleMin) || 1;
        const compute = (clientX) => {
            const rect = track.getBoundingClientRect();
            let frac = (clientX - rect.left) / (rect.width || 1);
            frac = Math.max(0, Math.min(1, frac));
            let v = Math.round((scaleMin + frac * span) / step) * step;
            const other = this._entityVal(otherId, which === 'min' ? scaleMax : scaleMin);
            if (which === 'min') v = Math.min(v, other);
            else v = Math.max(v, other);
            return Math.max(scaleMin, Math.min(scaleMax, v));
        };
        const onMove = (ev) => { this._freezeEntity(entId, compute(ev.clientX)); this.requestUpdate(); };
        const onUp = (ev) => {
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
            window.removeEventListener('pointercancel', onUp);
            this._setNumber(entId, compute(ev.clientX));
        };
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
        window.addEventListener('pointercancel', onUp);  // mobile scroll-interrupt cleanup
    }

    _renderChargerSection(id, idx) {
        const color = CHARGER_COLORS[idx % CHARGER_COLORS.length];
        const power = this._val(`charger_${id}_power`, 0);
        // #449: prefer the CHARGER's own session counter (KEBA / Wallbox /
        // go-eCharger / Easee / … session_energy sensor) over SEM's
        // internal integration. The charger's counter survives reloads +
        // midnight rollovers (plug-in to plug-out); SEM's resets on
        // coordinator restart. SEM's internal value is still load-bearing
        // for solar-share + cost calcs — kept queryable as the
        // ``session_energy`` sensor — but the user-facing "Session" tile
        // now matches what the charger itself reports.
        const sessionExt = this._val(`charger_${id}_session_energy_external`, 0);
        const sessionInt = this._val(`charger_${id}_session_energy`, 0);
        const session = sessionExt > 0 ? sessionExt : sessionInt;
        const dailyEnergy = this._val(`charger_${id}_daily_energy`, 0);
        // Solar Share sits under "Today: X kWh", so it must read the DAILY solar
        // attribution, not the per-cycle session — otherwise a plugged-in idle
        // car shows "Today 10.9 kWh · Solar Share 2%" where the 2% is just the
        // standby session (the day's charge was ~100% solar). Matches the
        // single-charger status-row path (energy_ev_solar_percentage = the
        // time-integrated daily flow attribution). (No per-charger daily-share
        // sensor exists yet — on a multi-charger fleet this shows the fleet's
        // daily share on each tile; a per-charger daily sensor is a follow-up.)
        const solar = this._val('energy_ev_solar_percentage', 0);
        // Prefer real vehicle SOC over estimated (#193). The per-charger
        // ``sensor.sem_charger_<id>_vehicle_soc`` (#383) is this charger's own
        // car. The global ``sem_vehicle_soc`` is a fleet value and is only a
        // safe fallback on a single-charger install — see resolveChargerSoc
        // and #683. Real SOC shows plain; the estimate is marked ~/est.
        const { soc, isEstimate: socIsEstimate } = resolveChargerSoc(
            this._val(`charger_${id}_vehicle_soc`, null),
            this._val('vehicle_soc', null),
            this._val(`charger_${id}_estimated_soc`, null),
            this._chargers.length,
        );
        // #708 — stale-sensor info line (approved Option A): the gauge keeps
        // showing exactly what the car reports; the session energy-accounted
        // estimate appears as a separate line with the reading's age, and a
        // "target reached (estimated)" line explains an estimate-based stop.
        //
        // The reading and its instant come from the server. They used to be
        // read off the live vehicle_soc mirror, which coupled this line to
        // the very failure it exists to explain: when the sensor goes
        // unavailable the mirror nulls, so the gauge promoted the estimate
        // and the line that said WHY vanished in the same frame. Worse, an
        // unavailable entity rewrites its own last_changed, so the age read
        // "0 min ago" for a sensor that had been dead for half an hour.
        // The instant (not a pre-computed age) is what's published, so the
        // clock still ticks here and the attribute stays recorder-quiet.
        const estAttrs708 = this._stateAttrs(`sensor.sem_charger_${id}_estimated_soc`);
        const eaSoc708 = estAttrs708.energy_accounted_soc;
        const estStop708 = estAttrs708.estimate_stop_active === true;
        const vSoc708 = this._val(`charger_${id}_vehicle_soc`, null);
        const lastSoc708 = estAttrs708.vehicle_soc_last ?? vSoc708;
        let socAge708 = null;
        const lastAt708 = Date.parse(estAttrs708.vehicle_soc_last_at ?? '');
        if (!Number.isNaN(lastAt708)) {
            socAge708 = Math.round((Date.now() - lastAt708) / 60000);
        }
        const fmt708 = (key) => (this._t(key) || '')
            .replace(/\{soc\}/g, lastSoc708 != null ? Math.round(lastSoc708) : '—')
            .replace(/\{age\}/g, socAge708 != null ? socAge708 : '—')
            .replace(/\{est\}/g, eaSoc708 != null ? Math.round(eaSoc708) : '—');
        // Show while the estimate meaningfully leads the last reading and
        // that reading is actually stale (>= 5 min) — display users see no
        // change. The lead requirement is waived when the sensor is OFFLINE:
        // there the provenance IS the message, because the gauge has already
        // switched to the estimate and nothing else says so.
        const socOffline708 = vSoc708 == null;
        const showSocInfo708 = lastSoc708 != null && eaSoc708 != null
            && socAge708 != null && socAge708 >= 5
            && ((eaSoc708 - lastSoc708) >= 1 || socOffline708);
        // (#440) nights / chargeNeeded / needsCharge / chargeIcon / chargeColor /
        // chargeText removed — the underlying skip decision is gone.
        const name = this._chargerName(id);

        // Per-charger connected status (#193)
        const perChargerConnected = this._hass?.states[`binary_sensor.sem_charger_${id}_connected`];
        const isConnected = perChargerConnected?.state === 'on';
        const isCharging = power > 50;
        const statusText = isCharging ? this._t('charging') : isConnected ? this._t('connected') : this._t('idle');
        // What SEM actually commanded to the charger (the set current), shown
        // next to the status so you can see SEM's transmitted A vs the car's
        // real draw — e.g. "CHARGING (8 A)".
        const commandedAmps = this._val(`charger_${id}_commanded_current`, 0);

        // ONE current knob (#536): "Min Amps" (ev_min_current). SEM starts
        // here and auto-raises the offer until a fussy car latches, then
        // settles back — no separate Start/Vehicle-min knobs.
        const minAmps = this._entityVal(`number.sem_charger_${id}_minimum_current`, 6);
        const capacityKwh = this._entityVal(`number.sem_charger_${id}_ev_battery_capacity_kwh`, 40);
        const consumption = this._entityVal(`number.sem_charger_${id}_ev_kwh_per_100km`, 18);

        // Charge mode selector (#277 Phase B.2). Replaces the legacy
        // four-toggle stack (ev_charging_mode select + night_charging +
        // smart_night_charging + tariff_optimized switches) with one
        // named per-charger select. Options + label come from the HA
        // select entity itself — solar_plus_cheap is conditionally
        // hidden by the entity's ``options`` property when no dynamic
        // tariff is configured (Q1 resolution).
        const chargeModeEntityId = `select.sem_charger_${id}_charge_mode`;
        const chargeModeAttrs = this._stateAttrs(chargeModeEntityId);
        const chargeMode = this._stateStr(chargeModeEntityId) || 'min_plus_solar';
        const chargeModeOptions = chargeModeAttrs.options || [
            'solar_only', 'solar_plus_battery', 'solar_plus_cheap',
            'min_plus_solar', 'always_max', 'off',
        ];
        // (#885 matrix, decision 3) One rule, two severities. A mode that
        // CANNOT function without its prerequisite is DISABLED with the
        // reason (solar_plus_cheap without a dynamic tariff has no cheap
        // windows to use — the #277 Q1 ghost-option protection, kept, but
        // visible instead of hidden). A mode that functions PARTIALLY gets
        // an INFO below instead (solar_plus_battery works on live surplus
        // from day one; the forecast bypass and dynamic floor wake when
        // the #800 learner graduates).
        const tariffAvailable = chargeModeAttrs.tariff_available !== false;
        const modesNeedingTariff = chargeModeAttrs.modes_needing_tariff || [];
        const modeDisabled = (o) =>
            !tariffAvailable && modesNeedingTariff.includes(o);
        const spendableAttrs =
            this._stateAttrs('sensor.sem_battery_spendable_kwh');
        const learnerLearning = spendableAttrs.phase === 'learning';
        const learnerInfo = (this._t('charge_mode_battery_learning_info') || '')
            .replace(/\{n\}/g, spendableAttrs.nights_sealed ?? '?')
            .replace(/\{total\}/g, spendableAttrs.nights_required ?? '?');
        const chargeModeLabels = {
            solar_only:       this._t('charge_mode_solar_only'),
            solar_plus_battery: this._t('charge_mode_solar_plus_battery'),
            solar_plus_cheap: this._t('charge_mode_solar_plus_cheap'),
            min_plus_solar:   this._t('charge_mode_min_plus_solar'),
            always_max:       this._t('charge_mode_always_max'),
            off:              this._t('charge_mode_off'),
        };
        // Mode hints (#charge-mode-detail) — three structured rows
        // (Surplus / Overnight / House battery) per mode. The battery
        // row substitutes {buffer} and {priority} with the user's
        // actual SOC zone values, read from the global battery
        // settings entities. Buffer/priority default fallback matches
        // the config defaults (70 / 30) when entities are missing.
        const bufferSoc = Math.round(
            this._entityVal('number.sem_battery_buffer_soc', 70));
        const prioritySoc = Math.round(
            this._entityVal('number.sem_battery_priority_soc', 30));
        const _hint = (key) => (this._t(key) || '')
            .replace(/\{buffer\}/g, bufferSoc)
            .replace(/\{priority\}/g, prioritySoc);
        const hintSurplus = _hint(`charge_mode_hint_${chargeMode}_surplus`);
        const hintOvernight = _hint(`charge_mode_hint_${chargeMode}_overnight`);
        const hintBattery = _hint(`charge_mode_hint_${chargeMode}_battery`);

        // Charge Target range (#245): Min (floor/night) + Max (solar ceiling) handles
        const targetTypeId = `select.sem_charger_${id}_ev_target_type`;
        const targetType = this._stateStr(targetTypeId) || 'kwh';
        const ttOptions = this._stateAttrs(targetTypeId).options || ['kwh'];
        const isSoc = targetType === 'soc';
        const minEntityId = isSoc
            ? `number.sem_charger_${id}_target_soc`
            : `number.sem_charger_${id}_daily_ev_target`;
        const maxEntityId = isSoc
            ? `number.sem_charger_${id}_target_soc_max`
            : `number.sem_charger_${id}_daily_ev_target_max`;

        // Deadline (#246) — the tariff/grid toggles moved into the
        // Charge mode selector above, but the deadline knob remains.
        const targetTimeId = `time.sem_charger_${id}_target_time`;
        const targetTimeRaw = this._stateStr(targetTimeId);  // "HH:MM:SS"
        const targetTimeLabel = targetTimeRaw ? targetTimeRaw.slice(0, 5) : '—';
        // Deadline / cheap-window status live on the charging_state sensor (primary).
        const csAttrs = this._stateAttrs(`${this._prefix}charging_state`);
        const deadlineUnreachable = csAttrs.ev_deadline_reachable === false;
        const ncRaw = csAttrs.ev_next_cheap_window;
        let nextCheapLabel = '';
        if (ncRaw) {
            try {
                const d = new Date(ncRaw);
                if (!isNaN(d)) nextCheapLabel = d.toLocaleTimeString([],
                    { hour: '2-digit', minute: '2-digit', timeZone: this._hass?.config?.time_zone || undefined });
            } catch (e) { /* ignore */ }
        }
        // Next cheap window only relevant when the mode actually uses
        // tariff windows. Phase B.2 hides it for the other modes so
        // users don't see a confusing "next cheap at HH:MM" line on a
        // mode that ignores tariff entirely.
        const showCheapHint = chargeMode === 'solar_plus_cheap'
            && nextCheapLabel;

        // (#804) Phase row — exists only for a charger whose phase-switch
        // capability is configured (the phase_mode select is only created
        // then). Status prefers the MEASURED phases (W/A estimate), falls
        // back to the sequencer's belief; a running switch replaces the
        // status with its sequence state.
        const phaseModeEntityId = `select.sem_charger_${id}_phase_mode`;
        const phaseModeExists = !!this._hass?.states?.[phaseModeEntityId];
        const phaseAttrs = ((csAttrs.per_charger_phases || {})[id]) || {};
        const phaseMode = this._stateStr(phaseModeEntityId) || 'auto';
        const phaseOptions = this._stateAttrs(phaseModeEntityId).options
            || ['auto', '1', '3'];
        const phaseLabels = {
            auto: this._t('phase_mode_auto'),
            '1': this._t('phase_mode_1'),
            '3': this._t('phase_mode_3'),
        };
        let phaseStatus = '';
        if (phaseAttrs.switch_state === 'stopping') {
            phaseStatus = this._t('phase_status_stopping');
        } else if (phaseAttrs.switch_state === 'settling') {
            phaseStatus = this._t('phase_status_settling');
        } else if (phaseAttrs.active_phases) {
            phaseStatus = (this._t('phase_status_measured') || '{n}-phase measured')
                .replace('{n}', phaseAttrs.active_phases);
        } else if (phaseAttrs.believed_phases) {
            phaseStatus = (this._t('phase_status_believed') || '{n}-phase')
                .replace('{n}', phaseAttrs.believed_phases);
        } else {
            phaseStatus = this._t('phase_status_unknown');
        }

        // Range the charge will ADD to reach the Min (guaranteed) target, in km —
        // updates live as the Min handle moves. Solar may add more, up to Max. (#245)
        const minTarget = this._entityVal(minEntityId, isSoc ? 80 : 10);
        const gapKwh = isSoc
            ? Math.max(0, (minTarget - soc) / 100 * capacityKwh)
            : Math.max(0, minTarget - dailyEnergy);
        const chargeKm = consumption > 0 ? Math.round(gapKwh / consumption * 100) : null;

        const unitControl = ttOptions.length > 1
            ? html`<select class="ct-unit" .value=${targetType}
                    @click=${(e) => e.stopPropagation()}
                    @change=${(e) => this._selectOption(targetTypeId, e.target.value)}>
                    ${ttOptions.map(o => html`<option value=${o} ?selected=${o === targetType}>${o === 'soc' ? '%' : 'kWh'}</option>`)}
                </select>`
            : html`<span class="ct-unit-static">${isSoc ? '%' : 'kWh'}</span>`;

        return html`
            <div class="charger-section">
                <div class="charger-header">
                    <div class="charger-dot" style="background:${color}"></div>
                    <span class="charger-name">${name}</span>
                    <span class="charger-status" style="color:${isCharging ? color : ''}">${statusText}${commandedAmps > 0 ? html` <span class="charger-set">(${Math.round(commandedAmps)}&nbsp;A)</span>` : nothing}</span>
                </div>

                <div class="charger-body">
                    <div class="charger-soc" title="${socIsEstimate ? this._t('soc_estimated_hint') : ''}">
                        ${this._renderSocGauge(soc, socIsEstimate)}
                        <span class="soc-label">${socIsEstimate ? this._t('soc_estimated_label') : 'SOC'}</span>
                    </div>

                    <div class="charger-metrics">
                        <div class="cm-row">
                            <span class="cm-label">${this._t('power')}</span>
                            <span class="cm-value" style="color:${isCharging ? color : ''}">${semFormatPower(power)}</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t('today')}</span>
                            <span class="cm-value">${this._fmt(dailyEnergy, 1)} kWh</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t('session')}</span>
                            <span class="cm-value">${this._fmt(session, 1)} kWh</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t('solar_share')}</span>
                            <span class="cm-value" style="color:#ff9800">${this._fmt(solar, 0)}%</span>
                        </div>
                        <!-- (#440) "Charge Tonight" and "Nights Until Charge"
                             rows removed. The underlying skip-decision wiring
                             was removed alongside; charge mode is the sole
                             authority on whether to charge at night. -->
                    </div>
                </div>

                ${estStop708 ? html`
                <div class="soc-info-708 soc-info-708-stop">
                    <ha-icon icon="mdi:check-circle-outline" style="--mdc-icon-size:14px;color:#8DC892"></ha-icon>
                    <span>${fmt708('soc_target_reached_est')}<br>
                        <small>${fmt708('soc_confirms_next_update')}</small></span>
                </div>` : showSocInfo708 ? html`
                <div class="soc-info-708">
                    <ha-icon icon="mdi:information-outline" style="--mdc-icon-size:14px;color:#5BC8D8"></ha-icon>
                    <span>${fmt708('soc_info_line')}</span>
                </div>` : nothing}

                <div class="charge-target-group">
                    <div class="ct-title">
                        <ha-icon icon="mdi:target" style="--mdc-icon-size:14px;color:#8DC892"></ha-icon>
                        ${this._t('charge_target')}
                        ${chargeKm != null && chargeKm > 0 ? html`<span class="ct-range">· +${chargeKm} km</span>` : nothing}
                        <span class="ct-spacer"></span>
                        ${unitControl}
                    </div>
                    ${this._renderRangeSlider(minEntityId, maxEntityId, isSoc)}
                    <!-- #277 Phase B.2: one named Charge mode selector
                         replaces the legacy ev_grid_charging + nested
                         ev_tariff_mode toggles. Options come from the HA
                         entity itself (solar_plus_cheap is hidden when no
                         dynamic tariff is configured, per Q1). The hint
                         line under it explains what the selected mode
                         actually does — cuts the toggle-soup mystery the
                         #247 review flagged. -->
                    <div class="ct-row">
                        <span class="ct-label">${this._t('charge_mode')}</span>
                        <span class="ct-ctl">
                            <select class="ct-mode-select"
                                    .value=${chargeMode}
                                    @click=${(e) => e.stopPropagation()}
                                    @change=${(e) => this._selectOption(chargeModeEntityId, e.target.value)}>
                                ${chargeModeOptions.map(o => html`
                                    <option value=${o} ?selected=${o === chargeMode}
                                            ?disabled=${modeDisabled(o)}>
                                        ${chargeModeLabels[o] || o}${modeDisabled(o) ? ` — ${this._t('charge_mode_needs_tariff')}` : ''}
                                    </option>`)}
                            </select>
                        </span>
                    </div>
                    ${chargeMode === 'solar_plus_battery' && learnerLearning ? html`
                    <div class="ct-subhint">
                        <div class="ct-hint-row">
                            <ha-icon icon="mdi:school-outline" style="--mdc-icon-size:13px;color:#5BC8D8"></ha-icon>
                            <span class="ct-hint-text">${learnerInfo}</span>
                        </div>
                    </div>
                    ` : nothing}
                    ${this._showHelp ? html`
                    <div class="ct-subhint">
                        <div class="ct-hint-row">
                            <span class="ct-hint-label">${this._t('hint_label_surplus')}:</span>
                            <span class="ct-hint-text">${hintSurplus}</span>
                        </div>
                        <div class="ct-hint-row">
                            <span class="ct-hint-label">${this._t('hint_label_overnight')}:</span>
                            <span class="ct-hint-text">${hintOvernight}</span>
                        </div>
                        <div class="ct-hint-row">
                            <span class="ct-hint-label">${this._t('hint_label_battery')}:</span>
                            <span class="ct-hint-text">${hintBattery}</span>
                        </div>
                        ${showCheapHint ? html`
                            <div class="ct-hint-row ct-hint-extra">
                                <span class="ct-hint-label">${this._t('ev_next_cheap')}:</span>
                                <span class="ct-hint-text"><b style="color:#8DC892">${nextCheapLabel}</b></span>
                            </div>
                        ` : nothing}
                    </div>
                    ` : (showCheapHint ? html`
                        <div class="ct-cheap-hint">
                            <span class="ct-hint-label">${this._t('ev_next_cheap')}:</span>
                            <b style="color:#8DC892">${nextCheapLabel}</b>
                        </div>
                    ` : nothing)}
                    ${phaseModeExists ? html`
                    <div class="ct-row">
                        <span class="ct-label">${this._t('phase_mode')}</span>
                        <span class="ct-ctl">
                            <select class="ct-mode-select"
                                    .value=${phaseMode}
                                    @click=${(e) => e.stopPropagation()}
                                    @change=${(e) => this._selectOption(phaseModeEntityId, e.target.value)}>
                                ${phaseOptions.map(o => html`
                                    <option value=${o} ?selected=${o === phaseMode}>
                                        ${phaseLabels[o] || o}
                                    </option>`)}
                            </select>
                        </span>
                    </div>
                    <div class="ct-subhint">
                        <div class="ct-hint-row">
                            <span class="ct-hint-text">
                                <ha-icon icon="mdi:sine-wave" style="--mdc-icon-size:12px;color:#8DC892"></ha-icon>
                                ${phaseStatus}
                            </span>
                        </div>
                    </div>
                    ` : nothing}
                    <div class="ct-row clickable"
                        @click=${() => this.dispatchEvent(new CustomEvent('hass-more-info',
                            { bubbles: true, composed: true, detail: { entityId: targetTimeId } }))}>
                        <span class="ct-label">${this._t('ev_charge_by')}</span>
                        <span class="ct-ctl ct-time">
                            <ha-icon icon="mdi:clock-end" style="--mdc-icon-size:13px;color:#5BC8D8"></ha-icon>
                            ${targetTimeLabel}
                        </span>
                    </div>
                    ${deadlineUnreachable ? html`
                        <div class="ct-warn">
                            <ha-icon icon="mdi:clock-alert" style="--mdc-icon-size:14px;color:#f06292"></ha-icon>
                            <span>${this._t('ev_deadline_unreachable_short')}</span>
                        </div>
                    ` : nothing}
                    ${this._renderPlanStrip(id)}
                </div>

                <div class="charger-settings ${this._showHelp ? 'help-mode' : ''}">
                    ${''/* ONE current knob: Min Amps. SEM auto-finds a fussy
                       car's start current and settles back here (#536). */}
                    <div class="setting-cell">
                        <div
                            class="setting-item clickable"
                            @click=${() => {
                                const event = new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId: `number.sem_charger_${id}_minimum_current` } });
                                this.dispatchEvent(event);
                            }}
                        >
                            <ha-icon icon="mdi:speedometer-slow" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                            <span class="setting-value">${this._fmt(minAmps, 0)}A</span>
                        </div>
                        ${this._showHelp ? html`<div class="setting-help">${this._t('tile_help_min_amps')}</div>` : nothing}
                    </div>
                    <div class="setting-cell">
                        <div
                            class="setting-item clickable"
                            @click=${() => {
                                const event = new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId: `number.sem_charger_${id}_ev_battery_capacity_kwh` } });
                                this.dispatchEvent(event);
                            }}
                        >
                            <ha-icon icon="mdi:car-battery" style="--mdc-icon-size:16px;color:#8DC892"></ha-icon>
                            <span class="setting-value">${this._fmt(capacityKwh, 0)} kWh</span>
                        </div>
                        ${this._showHelp ? html`<div class="setting-help">${this._t('tile_help_capacity')}</div>` : nothing}
                    </div>
                    <div class="setting-cell">
                        <div
                            class="setting-item clickable"
                            @click=${() => {
                                const event = new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId: `number.sem_charger_${id}_ev_kwh_per_100km` } });
                                this.dispatchEvent(event);
                            }}
                        >
                            <ha-icon icon="mdi:map-marker-distance" style="--mdc-icon-size:16px;color:#5BC8D8"></ha-icon>
                            <span class="setting-value">${this._fmt(consumption, 0)} kWh/100km</span>
                        </div>
                        ${this._showHelp ? html`<div class="setting-help">${this._t('tile_help_consumption')}</div>` : nothing}
                    </div>
                    <ha-icon
                        class="ev-help-toggle ${this._showHelp ? 'on' : ''}"
                        icon="${this._showHelp ? 'mdi:help-circle' : 'mdi:help-circle-outline'}"
                        title="${this._t('zone_help_toggle')}"
                        @click=${() => this._toggleHelp()}
                        style="--mdc-icon-size:16px"
                    ></ha-icon>
                </div>
            </div>
        `;
    }

    render() {
        if (!this._config || !this._hass) return nothing;

        const connected = this._binaryState('ev_connected');
        // Header power + charging derived from the SAME per-charger power the
        // tiles use (summed across the fleet) so the header can never contradict
        // the per-charger card. They previously read SEPARATE sensors — the
        // header `ev_power`/`ev_charging`, the tiles `charger_<id>_power` — which
        // lag independently and produced opposite snapshots (header CHARGING/4kW
        // while the card said Connected/0W, and vice-versa).
        const power = (this._chargers && this._chargers.length)
            ? this._chargers.reduce((s, id) => s + this._val(`charger_${id}_power`, 0), 0)
            : this._val('ev_power', 0);
        const charging = power > 50;
        const current = this._val('calculated_current', 0);
        const sessionEnergy = this._val('session_energy', 0);
        // Solar Share sits next to 'Today: X kWh' in the status row, so it
        // must read the DAILY metric, not the per-cycle session. Previously
        // pointed at session_solar_share — that produced labels like
        // 'Today 8.7 kWh · Solar Share 25%' where the 25% was just the
        // current session, not today's. Switched to energy_ev_solar_percentage
        // (time-integrated daily attribution from the flow accumulator).
        const solarShare = this._val('energy_ev_solar_percentage', 0);
        const sessionCost = this._val('session_cost', 0);
        const dailyEnergy = this._val('daily_ev_energy', 0);
        const strategy = this._valStr('charging_state');
        const curr = semGetCurrency(this._hass);

        // (Dead ``modeLabels`` / ``modeEntity`` lookup of the legacy
        // ``ev_charging_mode`` select removed in #277 Phase B.2 — the
        // per-charger Charge mode selector lives inside
        // ``_renderChargerSection`` now and consumes its own entity.)

        const wrapClass = charging ? 'wrap state-charging'
            : connected ? 'wrap state-connected'
            : 'wrap state-disconnected';

        const statusText = charging ? this._t('charging')
            : connected ? this._t('connected')
            : this._t('disconnected');

        const statusClass = charging ? 'status-value charging'
            : connected ? 'status-value connected'
            : 'status-value disconnected';

        const ringOpacity = charging ? '0.6' : connected ? '0.25' : '0.08';
        const boltOpacity = charging ? '1' : '0';

        return html`
            <svg class="glow-svg">
                <defs>
                    <filter id="ev-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="3" result="blur"/>
                        <feFlood flood-color="#8DC892" flood-opacity="0.3" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="ev-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="${wrapClass}">
                    <div class="hero">
                        <div class="ev-icon-area">
                            <svg viewBox="0 0 100 100">
                                <circle class="glow-ring" cx="50" cy="50" r="42" style="opacity:${ringOpacity}"/>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="ring-fill" cx="50" cy="50" r="39"/>
                                <g class="charger-icon" transform="translate(50,46)">
                                    <rect x="-10" y="-16" width="20" height="26" rx="3"/>
                                    <rect x="-6.5" y="-11" width="13" height="10" rx="2"/>
                                    <path d="M-1.5,-1 L0,4 L1.5,-1"/>
                                    <line x1="0" y1="10" x2="0" y2="15"/>
                                    <circle class="indicator-dot" cx="0" cy="18" r="2" stroke="none"/>
                                </g>
                                <g class="lightning-bolt" transform="translate(50,42)" style="opacity:${boltOpacity}">
                                    <path d="M-2,-8 L-4,1 L-0.5,0 L-1,8 L4,-1 L0.5,0 L2,-8Z" stroke="none"/>
                                </g>
                            </svg>
                        </div>

                        ${this._chargers.length >= 1 ? html`
                            <!-- #356: when at least one per-charger section
                                 will render below, the hero only shows a
                                 single status/power line. The per-charger
                                 section repeats today/session/solar-share/
                                 power for each charger, so duplicating them
                                 here as well produced the "4 tiles per
                                 charger" appearance the user reported. -->
                            <div class="metrics-col compact">
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('status')}</span>
                                    <span class="${statusClass}">${statusText}</span>
                                </div>
                                ${charging ? html`
                                    <div class="metric-row power-row">
                                        <span class="metric-label">${this._t('power')}</span>
                                        <span class="metric-value power-value">${semFormatPower(power)}</span>
                                    </div>
                                ` : nothing}
                            </div>
                        ` : html`
                            <div class="metrics-col">
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('status')}</span>
                                    <span class="${statusClass}">${statusText}</span>
                                </div>
                                ${charging ? html`
                                    <div class="metric-row power-row">
                                        <span class="metric-label">${this._t('power')}</span>
                                        <span class="metric-value power-value">${semFormatPower(power)}</span>
                                    </div>
                                ` : nothing}
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('today')}</span>
                                    <span class="metric-value">${this._fmt(dailyEnergy, 1)} kWh</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">${this._t('solar_share')}</span>
                                    <span class="metric-value solar-share-value">${this._fmt(solarShare, 0)}%</span>
                                </div>
                            </div>
                        `}
                    </div>

                    <!-- Session cost chip stays on for 0- and 1-charger
                         installs (M3 reviewer note): the global
                         sem_session_cost sensor IS the single charger's
                         cost. Only hide for multi-charger setups where
                         the global is a fleet aggregate and per-charger
                         attribution lives in each section's metrics. -->
                    ${this._chargers.length > 1 ? nothing : html`
                        <div class="bottom-bar">
                            <div class="chip">
                                <span class="chip-label">${this._t('session_cost')}</span>
                                <span class="cost-chip-value">${this._fmt(sessionCost, 2)} ${curr}</span>
                            </div>
                        </div>
                    `}

                    ${this._chargers.length >= 1 ? html`
                        <div class="charger-sections">
                            ${this._chargers.map((id, idx) => this._renderChargerSection(id, idx))}
                        </div>
                    ` : nothing}
                </div>
            </ha-card>
        `;
    }

    static get styles() {
        return css`
            :host { display: block; }
            .glow-svg { position: absolute; width: 0; height: 0; }

            .wrap {
                padding: 16px 20px;
                position: relative;
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(141,200,146,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
                min-height: 108px;
                overflow: hidden;
            }

            /* Hero layout */
            .hero {
                display: flex;
                align-items: center;
                gap: 20px;
            }

            /* Icon area */
            .ev-icon-area {
                position: relative;
                width: 90px; height: 90px;
                flex-shrink: 0;
            }
            .ev-icon-area svg { width: 100%; height: 100%; }

            /* Glow ring */
            .glow-ring {
                fill: none;
                stroke: #8DC892;
                stroke-width: 6;
                filter: url(#ev-glow-soft);
                transition: opacity 0.6s ease;
            }
            .state-charging .glow-ring {
                animation: pulse-ring 2s ease-in-out infinite;
            }
            @keyframes pulse-ring {
                0%, 100% { stroke-width: 6; opacity: 0.5; }
                50% { stroke-width: 10; opacity: 0.7; }
            }

            .ring-bg {
                fill: none;
                stroke: rgba(141,200,146,0.12);
                stroke-width: 3;
            }
            .ring-fill {
                fill: rgba(141,200,146,0.07);
            }

            .charger-icon {
                stroke: #8DC892;
                fill: none;
                stroke-width: 1.8;
                stroke-linecap: round;
                stroke-linejoin: round;
                opacity: 0.7;
                transition: opacity 0.4s ease;
            }
            .state-disconnected .charger-icon { stroke: #666; opacity: 0.35; }
            .state-disconnected .ring-bg { stroke: rgba(100,100,100,0.12); }
            .state-disconnected .ring-fill { fill: rgba(100,100,100,0.05); }
            .state-disconnected .glow-ring { stroke: #666; }

            .lightning-bolt {
                fill: #8DC892;
                transition: opacity 0.4s ease;
                filter: url(#ev-glow);
            }
            .state-charging .lightning-bolt {
                animation: bolt-pulse 1.5s ease-in-out infinite;
            }
            @keyframes bolt-pulse {
                0%, 100% { opacity: 0.9; }
                50% { opacity: 0.5; }
            }

            .indicator-dot {
                fill: #666;
                opacity: 0.3;
                transition: fill 0.4s ease, opacity 0.4s ease;
            }
            .state-connected .indicator-dot { fill: #8DC892; opacity: 0.5; }
            .state-charging .indicator-dot {
                fill: #8DC892; opacity: 1;
                animation: dot-blink 1s ease-in-out infinite;
            }
            @keyframes dot-blink {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.3; }
            }

            /* Metrics column */
            .metrics-col {
                flex: 1; min-width: 0;
                display: flex;
                flex-direction: column;
                gap: 2px;
            }
            .metric-row {
                display: flex;
                justify-content: space-between;
                align-items: baseline;
                gap: 8px;            /* #523/#524 follow-up: keep label + value
                                        apart when the column shrink-wraps in
                                        the centered hero ("StatusDisconnected") */
                padding: 2px 0;
            }
            .metric-label {
                font-size: 11px;
                color: var(--secondary-text-color, #999);
                font-weight: 500;
            }
            .metric-value {
                font-size: 12px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                color: var(--primary-text-color, #e0e0e0);
            }

            .status-value { font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; }
            .status-value.charging { color: #8DC892; text-shadow: 0 0 8px rgba(141,200,146,0.4); }
            .status-value.connected { color: #8DC892; }
            .status-value.disconnected { color: var(--secondary-text-color, #999); }

            .power-row .metric-value {
                font-size: 16px;
                font-weight: 700;
                color: #8DC892;
                text-shadow: 0 0 6px rgba(141,200,146,0.3);
            }

            .solar-share-value { color: #ff9800 !important; }

            .strategy-value {
                font-size: 11px;
                color: #8DC892; opacity: 0.7;
                font-weight: 500;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            }

            /* Bottom bar */
            .bottom-bar {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-top: 10px;
                flex-wrap: wrap;
            }
            .chip {
                display: inline-flex; align-items: center; gap: 4px;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 12px;
                padding: 3px 10px;
                font-size: 11px; font-weight: 500;
                color: var(--primary-text-color, #e0e0e0);
                font-variant-numeric: tabular-nums;
            }
            .chip-label { color: var(--secondary-text-color, #888); }
            .cost-chip-value { color: #f06292; }

            /* Per-charger sections */
            .charger-sections {
                margin-top: 16px;
                display: flex;
                flex-direction: column;
                gap: 12px;
            }
            .charger-section {
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 12px;
                padding: 12px 14px;
            }
            .charger-header {
                display: flex; align-items: center; gap: 8px;
                margin-bottom: 10px;
            }
            .charger-dot {
                width: 8px; height: 8px;
                border-radius: 50%;
                flex-shrink: 0;
            }
            .charger-name {
                flex: 1; font-weight: 600; font-size: 0.95em;
                color: var(--primary-text-color, #e0e0e0);
            }
            .charger-status {
                font-size: 0.8em; font-weight: 500;
                text-transform: uppercase; letter-spacing: 0.05em;
                color: var(--secondary-text-color, #999);
            }
            .charger-set {
                font-weight: 400; opacity: 0.85;
                font-variant-numeric: tabular-nums;
            }
            .charger-body {
                display: flex; align-items: center; gap: 12px;
            }
            .charger-soc {
                flex-shrink: 0; width: 44px; text-align: center;
            }
            .soc-label {
                display: block;
                font-size: 10px; color: var(--secondary-text-color, #999);
                margin-top: 2px;
                text-transform: uppercase; letter-spacing: 0.05em;
            }
            .charger-metrics {
                flex: 1;
                display: flex; flex-direction: column; gap: 2px;
            }
            /* #708 — stale-sensor estimate info line */
            .soc-info-708 {
                display: flex; align-items: flex-start; gap: 6px;
                margin: 4px 0 2px; padding: 4px 8px;
                font-size: 11px; line-height: 1.35;
                color: var(--secondary-text-color, #999);
                background: rgba(91, 200, 216, 0.08);
                border-radius: 6px;
            }
            .soc-info-708-stop {
                background: rgba(141, 200, 146, 0.10);
                color: var(--primary-text-color, #c9d4c9);
            }
            .soc-info-708 small {
                font-size: 10px; opacity: 0.75;
            }
            .cm-row {
                display: flex; justify-content: space-between; align-items: baseline;
                padding: 2px 0;
            }
            .cm-label { font-size: 11px; color: var(--secondary-text-color, #999); font-weight: 500; }
            .cm-value {
                font-size: 12px; font-weight: 600;
                color: var(--primary-text-color, #e0e0e0);
                font-variant-numeric: tabular-nums;
            }
            .charger-settings {
                display: flex; align-items: center; gap: 6px;
                margin-top: 8px; padding-top: 8px;
                border-top: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                flex-wrap: wrap;
            }
            /* Help mode: switch to a vertical list so each tile gets a
               one-line description below it. Compact when off. */
            .charger-settings.help-mode {
                flex-direction: column; align-items: stretch; gap: 4px;
            }
            .setting-cell { display: flex; align-items: center; gap: 6px; }
            .charger-settings.help-mode .setting-cell {
                flex-direction: column; align-items: flex-start; gap: 2px;
            }
            .setting-help {
                font-size: 11px;
                line-height: 1.3;
                color: var(--secondary-text-color, #888);
                opacity: 0.85;
                font-style: italic;
                padding-left: 22px;
            }
            .ev-help-toggle {
                cursor: pointer;
                color: var(--secondary-text-color, #999);
                opacity: 0.6;
                margin-left: auto;
                flex-shrink: 0;
                transition: opacity 0.15s, color 0.15s;
            }
            .ev-help-toggle:hover { opacity: 1; }
            .ev-help-toggle.on { color: #8DC892; opacity: 1; }
            .charger-settings.help-mode .ev-help-toggle { align-self: flex-end; }
            .setting-item {
                display: flex; align-items: center; gap: 3px;
                font-size: 11px; color: var(--secondary-text-color, #999);
            }
            .setting-item.clickable { cursor: pointer; }
            .setting-label { font-size: 11px; color: var(--secondary-text-color, #999); }
            .setting-value { font-size: 12px; font-weight: 600; color: var(--primary-text-color, #e0e0e0); }
            .setting-toggle {
                font-size: 11px; font-weight: 700;
                padding: 1px 6px;
                border-radius: 6px;
                cursor: pointer;
                user-select: none;
                transition: background 0.2s, color 0.2s;
            }
            .setting-toggle.on  { background: rgba(121,134,203,0.25); color: #7986CB; }
            .setting-toggle.off { background: rgba(100,100,100,0.15); color: #666; }
            .setting-toggle:hover { opacity: 0.8; }

            /* Charge Target group (#235) */
            .charge-target-group {
                margin-top: 8px;
                padding: 10px 12px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 10px;
                background: rgba(255,255,255,0.025);
            }
            .ct-title {
                font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
                color: var(--secondary-text-color, #999);
                display: flex; align-items: center; gap: 5px;
                margin-bottom: 4px;
            }
            .ct-range { color: #5BC8D8; font-weight: 600; text-transform: none; letter-spacing: 0; }
            .ct-spacer { margin-left: auto; }
            /* Dual-handle charge-target range slider (#245) */
            .range-wrap { padding: 6px 8px 10px; }
            .range-labels {
                display: flex; justify-content: space-between;
                font-size: 12px; color: var(--primary-text-color, #e0e0e0);
                margin-bottom: 10px;
            }
            .range-labels b { font-variant-numeric: tabular-nums; }
            .range-track {
                position: relative; height: 6px; border-radius: 3px;
                background: rgba(255,255,255,0.14); margin: 6px 9px;
                touch-action: none;
            }
            .range-fill {
                position: absolute; top: 0; height: 100%; border-radius: 3px;
                background: linear-gradient(90deg, #8DC892, #ff9800);
            }
            .range-handle {
                position: absolute; top: 50%; width: 18px; height: 18px;
                border-radius: 50%; transform: translate(-50%, -50%);
                background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.5);
                cursor: grab; touch-action: none;
            }
            .range-handle:active { cursor: grabbing; }
            .range-handle-min { border: 3px solid #8DC892; }
            .range-handle-max { border: 3px solid #ff9800; }
            .ct-row {
                display: flex; align-items: center; min-height: 32px;
            }
            .ct-row + .ct-row { border-top: 1px solid rgba(255,255,255,0.06); }
            .ct-row.clickable { cursor: pointer; }
            /* Tariff is nested under "Overnight grid charging" — it refines WHEN
               grid charging happens, not WHETHER (#247 UX). */
            .ct-subrow { padding-left: 14px; border-left: 2px solid rgba(141,200,146,0.35); margin-left: 2px; }
            .ct-subrow .ct-label { color: var(--secondary-text-color, #b5b5b5); }
            .ct-subhint {
                padding: 4px 0 4px 16px; margin-left: 2px;
                border-left: 2px solid rgba(141,200,146,0.18);
                font-size: 11px; line-height: 1.35; color: var(--secondary-text-color, #999);
                display: flex; flex-direction: column; gap: 2px;
            }
            .ct-hint-row { display: flex; gap: 6px; align-items: baseline; }
            .ct-hint-label {
                color: var(--secondary-text-color, #b5b5b5);
                font-weight: 600; flex-shrink: 0;
                min-width: 64px; text-align: right;
            }
            .ct-hint-text { color: var(--secondary-text-color, #999); }
            .ct-hint-extra { padding-top: 2px; border-top: 1px dashed rgba(255,255,255,0.05); }
            /* Cheap-window timing kept visible when help is off — too
               useful to hide behind the (?). One small line. */
            .ct-cheap-hint {
                padding: 3px 0 0 16px; margin-left: 2px;
                border-left: 2px solid rgba(141,200,146,0.18);
                font-size: 11px; color: var(--secondary-text-color, #999);
                display: flex; gap: 6px; align-items: baseline;
            }
            .ct-cheap-hint .ct-hint-label {
                min-width: auto; text-align: left;
            }
            .ct-label { font-size: 12px; color: var(--primary-text-color, #e0e0e0); }
            .ct-ctl { margin-left: auto; display: flex; align-items: center; gap: 7px; }
            .ct-time {
                font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                color: var(--primary-text-color, #e0e0e0);
            }
            .ct-warn {
                display: flex; align-items: center; gap: 6px;
                font-size: 12px; color: #f06292; padding: 5px 0 2px;
            }
            /* 12h EV plan strip (#282, readability pass #464) */
            .plan-strip {
                margin: 8px 0 2px; padding: 4px 0 2px;
                border-top: 1px dashed rgba(255,255,255,0.06);
            }
            .strip-title {
                display: flex; align-items: center; gap: 5px;
                font-size: 11px; font-weight: 600;
                color: var(--secondary-text-color, #aaa);
                letter-spacing: 0.3px; margin-bottom: 4px;
            }
            .strip-svg {
                width: 100%; height: 16px; display: block;
                border-radius: 3px; overflow: hidden;
            }
            .strip-axis {
                position: relative; height: 12px; margin-top: 2px;
                font-size: 10px; color: var(--secondary-text-color, #888);
            }
            .strip-axis .tick {
                position: absolute; transform: translateX(-50%);
                font-variant-numeric: tabular-nums; white-space: nowrap;
            }
            .strip-legend {
                display: flex; gap: 6px 11px; flex-wrap: wrap;
                font-size: 10.5px; color: var(--primary-text-color, #ddd);
                margin-top: 5px;
            }
            .strip-legend span {
                display: inline-flex; align-items: center; gap: 5px;
            }
            .strip-legend i {
                width: 11px; height: 11px; border-radius: 2px;
                display: inline-block; flex: none;
            }
            /* Tariff overlays render as a thin top line on the strip — mirror
               that shape in the legend so they read as the top line, not a
               full segment (#464). */
            .strip-legend i.line {
                height: 4px; border-radius: 1px;
            }
            .strip-help { margin-top: 6px; }
            /* #355 — split affordance shown only when the two range
               handles share a value. Sits on top of the stacked
               handles; tapping it drops Min by one step so the
               handles become individually grabbable again. */
            .range-split {
                position: absolute; top: 50%;
                transform: translate(-50%, -50%);
                width: 22px; height: 22px; border-radius: 50%;
                display: flex; align-items: center; justify-content: center;
                background: rgba(0,0,0,0.55);
                color: #fff;
                cursor: pointer;
                box-shadow: 0 1px 3px rgba(0,0,0,0.5);
                pointer-events: auto;
                z-index: 2;
            }
            .range-split:hover { background: rgba(0,0,0,0.75); }
            .ct-val {
                background: rgba(141,200,146,0.14); color: #8DC892;
                border: 1px solid rgba(141,200,146,0.35);
                border-radius: 8px; padding: 3px 11px; font-weight: 600;
                font-variant-numeric: tabular-nums; min-width: 42px; text-align: center;
            }
            .ct-val.clickable { cursor: pointer; }
            .ct-unit {
                appearance: none; -webkit-appearance: none;
                background-color: var(--secondary-background-color, rgba(255,255,255,0.07));
                /* explicit caret — appearance:none drops the native arrow, which made
                   this look like a static label rather than a kWh/% toggle (#245) */
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat: no-repeat;
                background-position: right 3px center;
                background-size: 14px;
                color: var(--primary-text-color, #e0e0e0);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 8px; padding: 4px 20px 4px 8px;
                font-size: 12px; font-weight: 600; cursor: pointer;
            }
            .ct-unit-static {
                font-size: 12px; font-weight: 600;
                color: var(--secondary-text-color, #999); padding: 4px 2px;
            }
            /* #277 Phase B.2 — Charge mode selector. Wider than ct-unit
               (multi-word labels) and aligned right inside the row's
               .ct-ctl cell. Same caret + chrome as ct-unit so the two
               selectors visually rhyme. */
            .ct-mode-select {
                appearance: none; -webkit-appearance: none;
                background-color: var(--secondary-background-color, rgba(255,255,255,0.07));
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat: no-repeat;
                background-position: right 6px center;
                background-size: 14px;
                color: var(--primary-text-color, #e0e0e0);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 8px;
                padding: 4px 24px 4px 10px;
                font-size: 12px; font-weight: 600;
                cursor: pointer;
                max-width: 200px;
            }
            .ct-sw {
                width: 38px; height: 22px; border-radius: 12px;
                position: relative; cursor: pointer; flex-shrink: 0;
                transition: background 0.18s;
            }
            .ct-sw.on { background: #8DC892; }
            .ct-sw.off { background: rgba(255,255,255,0.16); }
            .ct-knob {
                position: absolute; top: 2px; left: 2px;
                width: 18px; height: 18px; border-radius: 50%;
                background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.4);
                transition: left 0.18s;
            }
            .ct-sw.on .ct-knob { left: 18px; }

            @media (max-width: 400px) {
                /* Match the Battery tab exactly: stack the hero, keep the base
                   align-items:center so the metrics sit as a content-width block with
                   label-left / value-right rows (not stretched edge-to-edge). */
                .hero { flex-direction: column; gap: 12px; }
                .ev-icon-area { width: 80px; height: 80px; }
            }
        `;
    }

    getCardSize() { return this._chargers.length >= 1 ? 3 + this._chargers.length * 2 : 3; }

    static getStubConfig() { return {}; }
}

semDefineCard('sem-ev-status-card', SEMEVStatusCard, {
    type: 'sem-ev-status-card',
    name: 'SEM EV Status',
    description: 'Lumina-styled EV charging hero card with per-charger intelligence and settings',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-ev-status-card',
});
