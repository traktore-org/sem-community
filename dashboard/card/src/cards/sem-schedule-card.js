/**
 * SEM Schedule Card — LitElement migration
 *
 * 24-hour SVG timeline showing tariff, night window, surplus window, and EV charging
 * periods. Visual design identical to the original sem-schedule-card.js; only the
 * DOM management strategy changes (Lit reactive render vs innerHTML patching).
 *
 * Config:
 *   type: custom:sem-schedule-card
 *   entity_prefix: sensor.sem_   # default
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semTheme, semDefineCard, SEM_COLORS } from '../base/sem-shared.js';

const DEFAULT_PREFIX = 'sensor.sem_';

/* ── Layout constants ── */
const ML  = 36;   // margin-left
const MR  = 8;    // margin-right
const W   = 600;  // SVG width
const BW  = W - ML - MR; // 556 — bar width
const RH  = 18;   // row height
const RG  = 4;    // row gap
const LBL = 12;   // label y
const FRY = 20;   // first row y

/** Convert day-fraction (0-1) to SVG x coordinate. */
function toX(frac) { return ML + frac * BW; }

/** Parse "HH:MM" to 0-1 day fraction. Returns null on failure. */
function parseTime(str) {
    if (!str || typeof str !== 'string') return null;
    const m = str.match(/^(\d{1,2}):(\d{2})$/);
    if (!m) return null;
    const h = parseInt(m[1], 10);
    const min = parseInt(m[2], 10);
    if (h > 24 || min > 59) return null;
    return (h + min / 60) / 24;
}

/** Convert hourly boolean array to {start, end} fraction blocks. */
function hoursToBlocks(hours) {
    if (!Array.isArray(hours)) return [];
    const blocks = [];
    let blockStart = -1;
    for (let h = 0; h < 24; h++) {
        if (hours[h] && blockStart === -1) {
            blockStart = h;
        } else if (!hours[h] && blockStart !== -1) {
            blocks.push({ start: blockStart / 24, end: h / 24 });
            blockStart = -1;
        }
    }
    if (blockStart !== -1) blocks.push({ start: blockStart / 24, end: 1 });
    return blocks;
}

class SEMScheduleCard extends SEMLitBase {
    static get watchedEntities() {
        // Use defaults — any change in the prefix namespace fires a re-render
        return [
            `${DEFAULT_PREFIX}tariff_current_import_rate`,
            `${DEFAULT_PREFIX}tariff_price_level`,
            `${DEFAULT_PREFIX}night_start_time`,
            `${DEFAULT_PREFIX}night_end_time`,
            `${DEFAULT_PREFIX}best_surplus_window`,
            `${DEFAULT_PREFIX}predicted_surplus_window`,
            `${DEFAULT_PREFIX}ev_power`,
            `${DEFAULT_PREFIX}charging_state`,
            `${DEFAULT_PREFIX}surplus_total_w`,
        ];
    }

    setConfig(config) {
        super.setConfig(config);
        this._prefix = config.entity_prefix || DEFAULT_PREFIX;
    }

    // Override hass setter: key includes attribute values, not just entity states
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


        // Skip while frozen (optimistic update in progress)
        if (this._isFrozen() && !localeChanged) return;

        const keyParts = [
            'tariff_current_import_rate', 'tariff_price_level',
            'night_start_time', 'night_end_time',
            'best_surplus_window', 'predicted_surplus_window',
            'ev_power', 'charging_state',
        ].map(s => {
            const e = hass?.states[`${this._prefix}${s}`];
            return (e?.state || '')
                + JSON.stringify(e?.attributes?.schedule_today || '')
                + JSON.stringify(e?.attributes?.tariff_schedule_today || '')
                + JSON.stringify(e?.attributes?.schedule_surplus_hours || '')
                + JSON.stringify(e?.attributes?.schedule_ev_hours || '');
        });
        const key = keyParts.join('|') + '|' + lang;

        if (key === this._lastSchedKey && !localeChanged) return;
        this._lastSchedKey = key;
        this._scheduleUpdate();
    }

    get hass() { return this._hass; }

    /* ── Data helpers ── */

    _stateObj(suffix) {
        return this._hass?.states[`${this._prefix}${suffix}`] || null;
    }

    _getTariffSchedule() {
        // schedule_today lives on tariff_current_import_rate (rich attributes,
        // see sensor.py:tariff_current_import_rate branch). Previously this
        // card read it from tariff_price_level — where it doesn't exist — and
        // silently fell through to the default weekday HT/NT shape, so dynamic
        // tariffs never showed their actual schedule (#282 follow-up).
        const entity = this._stateObj('tariff_current_import_rate')
                    || this._stateObj('tariff_price_level');  // legacy fallback
        const schedule = entity?.attributes?.schedule_today
                      || entity?.attributes?.tariff_schedule_today;  // legacy key
        if (Array.isArray(schedule) && schedule.length > 0) {
            // Read the richer `level` field from #282 when present (cheap /
            // normal / expensive) — falls back to the legacy binary HT/NT so
            // older providers and static-tariff schedules still render correctly.
            return schedule.map(s => ({
                start: parseTime(s.start) ?? 0,
                end:   parseTime(s.end)   ?? 1,
                level: s.level || (
                    (s.tariff || s.type || 'HT').toUpperCase() === 'NT' ? 'cheap' : 'normal'
                ),
                type:  (s.tariff || s.type || 'HT').toUpperCase(),
                avgPrice: s.avg_price,
            }));
        }
        // v1.7.2-beta.3 (2026-06-07): the previous fallback baked a
        // CH-shape HT/NT schedule into the chart whenever
        // ``schedule_today`` wasn't published — including on weekends
        // where it returned ``cheap`` for ALL 24 hours. For a user on
        // a dynamic Tibber NL tariff with the schedule attribute
        // momentarily missing, the bottom-of-dashboard tariff
        // timeline lied about "Goedkoop all day" even when the
        // current price level sensor correctly said "Normaal".
        // Reported by RienduPre on Discussion #432 (2026-06-06,
        // Saturday — the all-cheap branch).
        //
        // New behaviour: if SEM hasn't published a schedule, mirror
        // the CURRENT ``tariff_price_level`` across the whole day so
        // at least the colour matches reality. This is still a
        // best-effort fallback — the underlying gap (provider not
        // populating ``schedule_today``) is a separate issue —
        // but it stops actively misleading the user.
        const currentLevel = this._stateObj('tariff_price_level')?.state;
        const knownLevels = new Set([
            'cheap', 'very_cheap', 'normal', 'expensive', 'very_expensive',
        ]);
        if (currentLevel && knownLevels.has(currentLevel)) {
            return [{
                start: 0, end: 1,
                level: currentLevel,
                type: currentLevel === 'cheap' || currentLevel === 'very_cheap' ? 'NT' : 'HT',
            }];
        }
        // Last resort — neither schedule_today nor a current price
        // level reported. Default to ``normal`` so the colour is
        // neutral (vs the old "cheap on weekends" misleading shape).
        return [{ start: 0, end: 1, level: 'normal', type: 'HT' }];
    }

    _getNightWindow() {
        const start = parseTime(this._stateObj('night_start_time')?.state);
        const end   = parseTime(this._stateObj('night_end_time')?.state);
        if (start == null || end == null) return null;
        return { start, end };
    }

    _getPredictedSurplusWindow() {
        for (const key of ['predicted_surplus_window', 'best_surplus_window']) {
            const raw = this._stateObj(key)?.state;
            if (!raw || raw === 'unknown' || raw === 'unavailable') continue;
            if (raw.toLowerCase().startsWith('tomorrow')) continue;
            const parts = raw.split(/[-–]/);
            if (parts.length !== 2) continue;
            const start = parseTime(parts[0].trim());
            const end   = parseTime(parts[1].trim());
            if (start != null && end != null) return { start, end };
        }
        return null;
    }

    _getSurplusBlocks() {
        const data = this._hass?.states[`${this._prefix}surplus_total_w`];
        return hoursToBlocks(data?.attributes?.schedule_surplus_hours);
    }

    _getEvBlocks() {
        const data = this._hass?.states[`${this._prefix}surplus_total_w`];
        return hoursToBlocks(data?.attributes?.schedule_ev_hours);
    }

    /**
     * Forward-looking EV charge plan (#282 follow-up). Reads today_plan from
     * charging_state attributes and projects ev_charge_start → ev_min_reached
     * onto the 24h timeline. Crosses midnight gracefully by clamping to today.
     * Returns ``{plan: [{start, end, kwh}], deadlineFrac, minReachedFrac}``.
     */
    _getEvPlanWindow() {
        const cs = this._stateObj('charging_state');
        const plan = cs?.attributes?.today_plan;
        if (!Array.isArray(plan)) return null;
        const today = new Date(); today.setHours(0, 0, 0, 0);
        const tomorrow = today.getTime() + 24 * 3600 * 1000;
        const tFrac = (when) => {
            const t = new Date(when).getTime();
            if (t < today.getTime() || t >= tomorrow) return null;
            return ((t - today.getTime()) / (24 * 3600 * 1000));
        };
        let chargeStart, minReached, deadline, kwhVal;
        for (const r of plan) {
            if (r.kind === 'ev_charge_start') chargeStart = tFrac(r.when);
            else if (r.kind === 'ev_min_reached') {
                minReached = tFrac(r.when);
                kwhVal = r.values?.kwh;
            } else if (r.kind === 'ev_deadline') deadline = tFrac(r.when);
        }
        // Plan block: from charge_start until min_reached (preferred) or deadline.
        const start = chargeStart;
        const end = minReached ?? deadline;
        if (start == null && end == null && deadline == null) return null;
        return {
            plan: (start != null && end != null && end > start)
                ? [{ start, end, kwh: kwhVal }] : [],
            deadlineFrac: deadline,
            minReachedFrac: minReached,
        };
    }

    /**
     * Solar forecast intensity curve (#282 follow-up). With no per-hour curve
     * exposed by the integration, synthesise a gaussian-shaped expected-power
     * curve around peak_time scaled by forecast_today_kwh. Returns an array
     * of 24 hourly intensity values in [0..1]. Useful even at low resolution
     * because it visualises "when solar will peak today" — far more
     * informative than the single best_surplus_window string.
     */
    _getSolarIntensity() {
        const peakRaw = this._stateObj('forecast_peak_time_today')?.state
                     || this._stateObj('peak_time_today')?.state;
        const todayKwh = parseFloat(
            this._stateObj('forecast_today_kwh')?.state
            || this._stateObj('forecast_today')?.state
        );
        if (!peakRaw || isNaN(todayKwh) || todayKwh < 0.5) return null;
        const peak = parseTime(peakRaw.slice(0, 5));
        if (peak == null) return null;
        // Spread ~3h half-width on a clear day, scales with forecast magnitude
        // so dim days draw a flatter, weaker curve.
        const sigma = 0.13;  // ~3.1h half-width
        const arr = new Array(24).fill(0);
        let total = 0;
        for (let h = 0; h < 24; h++) {
            const x = (h / 24) - peak;
            const y = Math.exp(-(x * x) / (2 * sigma * sigma));
            arr[h] = y;
            total += y;
        }
        // Normalise so peak intensity stays around 1 even for weak days.
        const max = Math.max(...arr);
        return arr.map(v => v / max);
    }

    _isEvCharging() {
        const evPower = parseFloat(this._stateObj('ev_power')?.state);
        if (!isNaN(evPower) && evPower > 10) return true;
        const chState = this._stateObj('charging_state')?.state;
        return chState && chState.toLowerCase() === 'charging';
    }

    /** Current "now" snapshot per row for the inline badges (D). */
    _getNowBadges() {
        // Tariff: current level from the price sensor
        const priceLevel = this._stateObj('tariff_price_level')?.state;
        const priceKey = ['cheap', 'normal', 'expensive', 'very_cheap', 'very_expensive']
            .includes(priceLevel) ? priceLevel : null;
        // Night: in window?
        const inNight = this._stateObj('night_charging_status')?.state === 'active';
        // Surplus: current solar power
        const solarW = parseFloat(this._stateObj('solar_power')?.state);
        const solarLabel = !isNaN(solarW) && solarW > 50
            ? `${(solarW / 1000).toFixed(1)} kW` : null;
        // EV: charging now? planned tonight? or nothing
        const charging = this._isEvCharging();
        const evPlan = this._getEvPlanWindow();
        return {
            tariff: priceKey,
            night: inNight ? 'now' : null,
            surplus: solarLabel,
            ev: charging ? 'charging' : (evPlan?.plan?.length ? 'planned' : null),
        };
    }

    /* ── SVG content builder ── */
    _buildSvgContent(T) {
        const colors = SEM_COLORS;
        const textSecCol  = T.textSec     || '#888';
        const textTertCol = T.textTertiary || '#777';
        const rowBg       = T.surface     || 'rgba(255,255,255,0.03)';

        let svg = '';

        // Hour labels
        for (let h = 0; h <= 24; h += 2) {
            const x = toX(h / 24);
            svg += `<text x="${x}" y="${LBL}" text-anchor="middle" fill="${textSecCol}"
                font-size="9" font-family="'Segoe UI','Roboto',sans-serif"
                font-variant-numeric="tabular-nums">${h.toString().padStart(2, '0')}</text>`;
        }

        // Row labels (left side) — translated at render time
        const rowLabels = [this._t('tariff'), this._t('night'), this._t('surplus'), this._t('ev')];
        rowLabels.forEach((label, i) => {
            const y = FRY + i * (RH + RG) + RH / 2 + 3.5;
            svg += `<text x="${ML - 4}" y="${y}" text-anchor="end" fill="${textTertCol}"
                font-size="9" font-family="'Segoe UI','Roboto',sans-serif">${label}</text>`;
        });

        // Row backgrounds
        for (let i = 0; i < 4; i++) {
            const y = FRY + i * (RH + RG);
            svg += `<rect x="${ML}" y="${y}" width="${BW}" height="${RH}" rx="3" fill="${rowBg}"/>`;
        }

        // Row 0: Tariff — 3-level colouring (#282): cheap green, normal orange,
        // expensive pink. Falls back gracefully to legacy NT/HT when `level` is
        // absent (static tariffs / older block shapes — see _getTariffSchedule).
        // Expensive is intentionally brighter than normal (#282/F) so the visual
        // separation between HT-normal and HT-expensive is unambiguous.
        const TARIFF_LEVEL_COLOURS = {
            cheap:     { fill: '#66bb6a', opacity: 0.62 },
            normal:    { fill: colors.solar, opacity: 0.55 },
            expensive: { fill: '#e91e63', opacity: 0.90 },
        };
        const TARIFF_LEVEL_LABEL_KEY = {
            cheap:     'cheap',
            normal:    'normal',
            expensive: 'expensive',
        };
        const tariffY = FRY;
        for (const block of this._getTariffSchedule()) {
            const x = toX(block.start);
            const w = toX(block.end) - x;
            const c = TARIFF_LEVEL_COLOURS[block.level] || TARIFF_LEVEL_COLOURS.normal;
            // Native browser tooltip with the avg price when we have it —
            // useful debug, cheap UX win since no JS event wiring needed.
            const tip = block.avgPrice != null
                ? `${block.level} · avg ${block.avgPrice.toFixed(2)}`
                : block.level;
            svg += `<rect x="${x}" y="${tariffY}" width="${w}" height="${RH}"
                rx="3" fill="${c.fill}" opacity="${c.opacity}">
                <title>${tip}</title></rect>`;
            if (w > 30) {
                // Prefer the dynamic level label (Cheap/Normal/Expensive) when
                // the block was classified by level; fall back to NT/HT for
                // legacy schedules.
                const labelKey = block.level && TARIFF_LEVEL_LABEL_KEY[block.level]
                    ? TARIFF_LEVEL_LABEL_KEY[block.level]
                    : block.type.toLowerCase();
                svg += `<text x="${x + w / 2}" y="${tariffY + RH / 2 + 3.5}" text-anchor="middle"
                    fill="rgba(255,255,255,0.92)" font-size="8" font-weight="600"
                    font-family="'Segoe UI','Roboto',sans-serif">${this._t(labelKey)}</text>`;
            }
        }

        // Row 1: Night Window (+ tooltip — #282/C)
        const nightY = FRY + (RH + RG);
        const night = this._getNightWindow();
        if (night) {
            const fmt = (frac) => {
                const m = Math.round(frac * 24 * 60);
                return `${String(Math.floor(m / 60)).padStart(2,'0')}:${String(m % 60).padStart(2,'0')}`;
            };
            const tip = `${this._t('night')} ${fmt(night.start)}–${fmt(night.end)}`;
            if (night.start > night.end) {
                // Wraps midnight: two segments
                const x1 = toX(night.start);
                svg += `<rect x="${x1}" y="${nightY}" width="${toX(1) - x1}"
                    height="${RH}" rx="3" fill="#42a5f5" opacity="0.55"><title>${tip}</title></rect>`;
                svg += `<rect x="${toX(0)}" y="${nightY}"
                    width="${toX(night.end) - toX(0)}" height="${RH}"
                    rx="3" fill="#42a5f5" opacity="0.55"><title>${tip}</title></rect>`;
            } else {
                const x = toX(night.start);
                const w = toX(night.end) - x;
                svg += `<rect x="${x}" y="${nightY}" width="${w}" height="${RH}"
                    rx="3" fill="#42a5f5" opacity="0.55"><title>${tip}</title></rect>`;
            }
        }

        // Row 2: Surplus — forecast intensity (faded yellow gradient, #282/B)
        // + predicted window (legacy single block) + actual blocks (history).
        const surplusY = FRY + 2 * (RH + RG);
        const intensity = this._getSolarIntensity();
        const todayKwh = parseFloat(
            this._stateObj('forecast_today_kwh')?.state || NaN);
        if (intensity) {
            const intTip = isNaN(todayKwh) ? this._t('surplus')
                : `${this._t('surplus')} · forecast ${todayKwh.toFixed(1)} kWh`;
            // Render 24 thin slats with opacity proportional to expected output.
            // Caps min opacity at 0 to keep dark hours dark; rounds slat widths
            // to whole pixels of viewBox so antialiasing doesn't dim the row.
            for (let h = 0; h < 24; h++) {
                const v = intensity[h];
                if (v < 0.08) continue;
                const x = toX(h / 24);
                const w = toX(1 / 24);
                svg += `<rect x="${x}" y="${surplusY}" width="${w}" height="${RH}"
                    fill="#fdd835" opacity="${(v * 0.55).toFixed(2)}"><title>${intTip}</title></rect>`;
            }
        }
        const predicted = this._getPredictedSurplusWindow();
        if (predicted) {
            const x = toX(predicted.start);
            const w = Math.max(0, toX(predicted.end) - x);
            svg += `<rect x="${x}" y="${surplusY}" width="${w}" height="${RH}"
                rx="3" fill="none" stroke="#fdd835" stroke-width="1"
                stroke-opacity="0.5" stroke-dasharray="2,2"/>`;
        }
        for (const block of this._getSurplusBlocks()) {
            const x = toX(block.start);
            const w = Math.max(0, toX(block.end) - x);
            svg += `<rect x="${x}" y="${surplusY}" width="${w}" height="${RH}"
                rx="3" fill="#fdd835" opacity="0.62"/>`;
        }

        // Row 3: EV — planned window (faded, #282/A) + actual past hours +
        // deadline marker (vertical line) + currently-charging emphasis.
        const evY = FRY + 3 * (RH + RG);
        const evPlan = this._getEvPlanWindow();
        if (evPlan?.plan?.length) {
            for (const b of evPlan.plan) {
                const x = toX(b.start);
                const w = Math.max(0, toX(b.end) - x);
                const tip = b.kwh
                    ? `${this._t('plan_ev_charge_start')} → ${this._t('plan_ev_min_reached').replace('{kwh}', b.kwh)}`
                    : this._t('plan_ev_charge_start');
                svg += `<rect x="${x}" y="${evY}" width="${w}" height="${RH}"
                    rx="3" fill="${colors.ev}" opacity="0.30"
                    stroke="${colors.ev}" stroke-width="0.6" stroke-opacity="0.6"
                    stroke-dasharray="3,2"><title>${tip}</title></rect>`;
            }
        }
        for (const block of this._getEvBlocks()) {
            const x = toX(block.start);
            const w = Math.max(0, toX(block.end) - x);
            svg += `<rect x="${x}" y="${evY}" width="${w}" height="${RH}"
                rx="3" fill="${colors.ev}" opacity="0.55"/>`;
        }
        // Deadline marker on the EV row
        if (evPlan?.deadlineFrac != null) {
            const dx = toX(evPlan.deadlineFrac);
            svg += `<line x1="${dx}" y1="${evY - 2}" x2="${dx}" y2="${evY + RH + 2}"
                stroke="#f06292" stroke-width="1.2" stroke-dasharray="2,1" opacity="0.85">
                <title>${this._t('plan_ev_deadline')}</title></line>`;
        }
        if (this._isEvCharging()) {
            const now = new Date();
            const nowFrac = (now.getHours() + now.getMinutes() / 60) / 24;
            const halfBlock = 0.5 / 24;
            const start = Math.max(0, nowFrac - halfBlock);
            const end   = Math.min(1, nowFrac + halfBlock);
            const x = toX(start);
            const w = toX(end) - x;
            svg += `<rect x="${x}" y="${evY}" width="${w}" height="${RH}"
                rx="3" fill="${colors.ev}" opacity="0.95"/>`;
        }

        // Current time indicator
        const now = new Date();
        const nowX = toX((now.getHours() + now.getMinutes() / 60) / 24);
        const lineTop = FRY - 2;
        const lineBottom = FRY + 4 * (RH + RG) - RG;
        svg += `<line x1="${nowX}" y1="${lineTop}" x2="${nowX}" y2="${lineBottom}"
            stroke="#ef5350" stroke-width="1.5" stroke-linecap="round" opacity="0.9"/>`;
        svg += `<polygon points="${nowX - 3},${lineTop} ${nowX + 3},${lineTop} ${nowX},${lineTop + 4}"
            fill="#ef5350" opacity="0.9"/>`;

        return svg;
    }

    /* ── Render ── */
    render() {
        if (!this._hass || !this._config) return nothing;

        const T = this._theme();
        const totalHeight = FRY + 4 * (RH + RG) + 4;
        const dotCol = T.dotColor || 'rgba(128,128,128,0.04)';
        const svgContent = this._buildSvgContent(T);

        // Now-state badges (#282/D): rendered as HTML next to the SVG so
        // they get clean typography + accessible markup. One per row.
        const badges = this._getNowBadges();
        const badgePalette = {
            cheap: '#66bb6a', very_cheap: '#66bb6a',
            normal: '#ff9800',
            expensive: '#e91e63', very_expensive: '#e91e63',
            now: '#42a5f5', charging: '#8DC892', planned: '#8DC892',
        };
        const badgeRow = (key, valueKey) => {
            if (!valueKey) return nothing;
            const colour = badgePalette[valueKey] || '#888';
            // Numeric labels (e.g. "5.4 kW") render literally; semantic keys
            // get translated. Heuristic: contains a digit ⇒ literal.
            const text = /\d/.test(valueKey) ? valueKey : this._t(valueKey);
            return html`<span class="now-badge"
                style="color:${colour};border-color:${colour}55;background:${colour}22">${text}</span>`;
        };

        return html`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 12px 14px 8px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(150,202,238,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${T.text || '#e0e0e0'});
                }
                .timeline-svg { width: 100%; height: auto; }
                .now-row {
                    display: flex; align-items: center; gap: 10px;
                    font-size: 11px; color: var(--secondary-text-color, #999);
                    margin-top: 4px; flex-wrap: wrap;
                }
                .now-row .now-label {
                    font-weight: 600; opacity: 0.7; margin-right: 4px;
                }
                .now-row .row-pair {
                    display: inline-flex; align-items: center; gap: 4px;
                }
                .now-row .row-pair > span:first-child { opacity: 0.7; }
                .now-badge {
                    display: inline-block; padding: 1px 7px;
                    border-radius: 999px; border: 1px solid;
                    font-size: 10.5px; font-weight: 600;
                    text-transform: capitalize;
                }
                .legend {
                    display: flex; gap: 14px; flex-wrap: wrap;
                    margin-top: 6px; padding-top: 6px;
                    border-top: 1px dashed rgba(255,255,255,0.06);
                    font-size: 10px; color: var(--secondary-text-color, #888);
                }
                .legend .item {
                    display: inline-flex; align-items: center; gap: 4px;
                }
                .legend i {
                    width: 10px; height: 10px; border-radius: 2px;
                    display: inline-block;
                }
            </style>
            <ha-card>
                <div class="wrap">
                    <svg class="timeline-svg"
                        viewBox="0 0 ${W} ${totalHeight}"
                        preserveAspectRatio="xMidYMid meet"
                        role="img"
                        aria-label="24-hour schedule timeline"
                        .innerHTML=${svgContent}>
                    </svg>
                    <div class="now-row" role="status">
                        <span class="now-label">${this._t('plan_now')}:</span>
                        <span class="row-pair"><span>${this._t('tariff')}</span>${badgeRow('tariff', badges.tariff)}</span>
                        <span class="row-pair"><span>${this._t('night')}</span>${badgeRow('night', badges.night)}</span>
                        <span class="row-pair"><span>${this._t('surplus')}</span>${badgeRow('surplus', badges.surplus)}</span>
                        <span class="row-pair"><span>${this._t('ev')}</span>${badgeRow('ev', badges.ev)}</span>
                    </div>
                    <div class="legend">
                        <span class="item"><i style="background:#66bb6a"></i>${this._t('cheap')}</span>
                        <span class="item"><i style="background:${SEM_COLORS.solar}"></i>${this._t('normal')}</span>
                        <span class="item"><i style="background:#e91e63"></i>${this._t('expensive')}</span>
                        <span class="item"><i style="background:#42a5f5"></i>${this._t('night')}</span>
                        <span class="item"><i style="background:#fdd835"></i>${this._t('surplus')}</span>
                        <span class="item"><i style="background:${SEM_COLORS.ev}"></i>${this._t('ev')}</span>
                    </div>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 2; }

    static getStubConfig() { return {}; }
}

semDefineCard('sem-schedule-card', SEMScheduleCard, {
    type: 'sem-schedule-card',
    name: 'SEM Schedule',
    description: '24-hour timeline showing tariff, night window, surplus window, and EV charging periods',
});
