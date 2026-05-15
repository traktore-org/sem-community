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
            'tariff_price_level', 'night_start_time', 'night_end_time',
            'best_surplus_window', 'predicted_surplus_window',
            'ev_power', 'charging_state',
        ].map(s => {
            const e = hass?.states[`${this._prefix}${s}`];
            return (e?.state || '')
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
        const entity = this._stateObj('tariff_price_level');
        const schedule = entity?.attributes?.tariff_schedule_today;
        if (Array.isArray(schedule) && schedule.length > 0) {
            return schedule.map(s => ({
                start: parseTime(s.start) ?? 0,
                end:   parseTime(s.end)   ?? 1,
                type:  (s.tariff || s.type || 'HT').toUpperCase(),
            }));
        }
        // Default weekday schedule
        const day = new Date().getDay();
        const isWeekend = day === 0 || day === 6;
        if (isWeekend) return [{ start: 0, end: 1, type: 'NT' }];
        return [
            { start: 0,        end: 7 / 24,  type: 'NT' },
            { start: 7 / 24,   end: 20 / 24, type: 'HT' },
            { start: 20 / 24,  end: 1,        type: 'NT' },
        ];
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

    _isEvCharging() {
        const evPower = parseFloat(this._stateObj('ev_power')?.state);
        if (!isNaN(evPower) && evPower > 10) return true;
        const chState = this._stateObj('charging_state')?.state;
        return chState && chState.toLowerCase() === 'charging';
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

        // Row 0: Tariff
        const tariffY = FRY;
        for (const block of this._getTariffSchedule()) {
            const x = toX(block.start);
            const w = toX(block.end) - x;
            const fill    = block.type === 'HT' ? colors.solar : '#66bb6a';
            const opacity = block.type === 'HT' ? 0.7 : 0.55;
            svg += `<rect x="${x}" y="${tariffY}" width="${w}" height="${RH}"
                rx="3" fill="${fill}" opacity="${opacity}"/>`;
            if (w > 30) {
                const label = this._t(block.type.toLowerCase());
                svg += `<text x="${x + w / 2}" y="${tariffY + RH / 2 + 3.5}" text-anchor="middle"
                    fill="rgba(255,255,255,0.85)" font-size="8" font-weight="600"
                    font-family="'Segoe UI','Roboto',sans-serif">${label}</text>`;
            }
        }

        // Row 1: Night Window
        const nightY = FRY + (RH + RG);
        const night = this._getNightWindow();
        if (night) {
            if (night.start > night.end) {
                // Wraps midnight: two segments
                const x1 = toX(night.start);
                svg += `<rect x="${x1}" y="${nightY}" width="${toX(1) - x1}"
                    height="${RH}" rx="3" fill="#42a5f5" opacity="0.55"/>`;
                svg += `<rect x="${toX(0)}" y="${nightY}"
                    width="${toX(night.end) - toX(0)}" height="${RH}"
                    rx="3" fill="#42a5f5" opacity="0.55"/>`;
            } else {
                const x = toX(night.start);
                const w = toX(night.end) - x;
                svg += `<rect x="${x}" y="${nightY}" width="${w}" height="${RH}"
                    rx="3" fill="#42a5f5" opacity="0.55"/>`;
            }
        }

        // Row 2: Surplus — predicted (faded) + actual (solid)
        const surplusY = FRY + 2 * (RH + RG);
        const predicted = this._getPredictedSurplusWindow();
        if (predicted) {
            const x = toX(predicted.start);
            const w = Math.max(0, toX(predicted.end) - x);
            svg += `<rect x="${x}" y="${surplusY}" width="${w}" height="${RH}"
                rx="3" fill="#fdd835" opacity="0.18"/>`;
        }
        for (const block of this._getSurplusBlocks()) {
            const x = toX(block.start);
            const w = Math.max(0, toX(block.end) - x);
            svg += `<rect x="${x}" y="${surplusY}" width="${w}" height="${RH}"
                rx="3" fill="#fdd835" opacity="0.6"/>`;
        }

        // Row 3: EV charging hours
        const evY = FRY + 3 * (RH + RG);
        for (const block of this._getEvBlocks()) {
            const x = toX(block.start);
            const w = Math.max(0, toX(block.end) - x);
            svg += `<rect x="${x}" y="${evY}" width="${w}" height="${RH}"
                rx="3" fill="${colors.ev}" opacity="0.55"/>`;
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
                rx="3" fill="${colors.ev}" opacity="0.85"/>`;
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
