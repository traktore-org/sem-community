/**
 * SEM Schedule Card — 24-hour timeline with tariff, night, surplus & EV rows
 *
 * Config:
 *   type: custom:sem-schedule-card
 *   entity_prefix: sensor.sem_   # default
 */

class SEMScheduleCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._rendered = false;
    }

    setConfig(config) {
        this.config = config;
        this._prefix = config.entity_prefix || 'sensor.sem_';
    }

    /* ── Color palette (fallback if sem-shared.js not loaded) ── */
    get _colors() {
        return (typeof window !== 'undefined' && window.SEM_COLORS) || {
            solar: '#ff9800',
            gridImport: '#488fc2',
            gridExport: '#8353d1',
            batteryIn: '#f06292',
            batteryOut: '#4db6ac',
            battery: '#4db6ac',
            home: '#5BC8D8',
            ev: '#8DC892',
        };
    }

    set hass(hass) {
        this._hass = hass;
        const key = [
            'tariff_price_level', 'night_start_time', 'night_end_time',
            'best_surplus_window', 'predicted_surplus_window',
            'ev_power', 'charging_state',
        ].map(s => {
            const e = hass?.states[`${this._prefix}${s}`];
            return (e?.state || '') + JSON.stringify(e?.attributes?.tariff_schedule_today || '')
                + JSON.stringify(e?.attributes?.schedule_surplus_hours || '')
                + JSON.stringify(e?.attributes?.schedule_ev_hours || '');
        }).join('|');
        if (key === this._lastKey) return;
        this._lastKey = key;
        this._update();
    }

    /* ── Helpers ── */

    _stateObj(suffix) {
        return this._hass?.states[`${this._prefix}${suffix}`] || null;
    }

    /** Convert "HH:MM" string to fraction of day (0-1). Returns null on failure. */
    _parseTime(str) {
        if (!str || typeof str !== 'string') return null;
        const m = str.match(/^(\d{1,2}):(\d{2})$/);
        if (!m) return null;
        const hours = parseInt(m[1], 10);
        const mins = parseInt(m[2], 10);
        if (hours > 24 || mins > 59) return null;
        return (hours + mins / 60) / 24;
    }

    /** Build tariff schedule as array of {start, end, type} where start/end are 0-1 fractions. */
    _getTariffSchedule() {
        // Try to find tariff_schedule_today attribute on tariff sensor
        const tariffEntity = this._stateObj('tariff_price_level');
        const schedule = tariffEntity?.attributes?.tariff_schedule_today;

        if (Array.isArray(schedule) && schedule.length > 0) {
            // Expected format: [{start: "HH:MM", end: "HH:MM", tariff: "HT"|"NT"}, ...]
            return schedule.map(s => ({
                start: this._parseTime(s.start) ?? 0,
                end: this._parseTime(s.end) ?? 1,
                type: (s.tariff || s.type || 'HT').toUpperCase(),
            }));
        }

        // Default weekday schedule: NT 00:00-07:00, HT 07:00-20:00, NT 20:00-24:00
        const day = new Date().getDay();
        const isWeekend = day === 0 || day === 6;
        if (isWeekend) {
            return [{ start: 0, end: 1, type: 'NT' }];
        }
        return [
            { start: 0, end: 7 / 24, type: 'NT' },
            { start: 7 / 24, end: 20 / 24, type: 'HT' },
            { start: 20 / 24, end: 1, type: 'NT' },
        ];
    }

    /** Return {start, end} fractions for night window, or null. */
    _getNightWindow() {
        const startStr = this._stateObj('night_start_time')?.state;
        const endStr = this._stateObj('night_end_time')?.state;
        const start = this._parseTime(startStr);
        const end = this._parseTime(endStr);
        if (start == null || end == null) return null;
        return { start, end };
    }

    /** Return predicted surplus window as {start, end} fractions, or null. */
    _getPredictedSurplusWindow() {
        // Try predicted_surplus_window first, then best_surplus_window
        for (const key of ['predicted_surplus_window', 'best_surplus_window']) {
            const raw = this._stateObj(key)?.state;
            if (!raw || raw === 'unknown' || raw === 'unavailable') continue;
            // Skip "tomorrow..." — we only show today
            if (raw.toLowerCase().startsWith('tomorrow')) continue;
            // Parse "HH:MM–HH:MM" or "HH:MM-HH:MM" (both dash types)
            const parts = raw.split(/[-–]/);
            if (parts.length !== 2) continue;
            const start = this._parseTime(parts[0].trim());
            const end = this._parseTime(parts[1].trim());
            if (start != null && end != null) return { start, end };
        }
        return null;
    }

    /** Return array of {start, end} blocks from hourly boolean array. */
    _hoursToBlocks(hours) {
        if (!hours || !Array.isArray(hours)) return [];
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
        if (blockStart !== -1) {
            blocks.push({ start: blockStart / 24, end: 1 });
        }
        return blocks;
    }

    /** Get actual surplus hours from coordinator data. */
    _getActualSurplusBlocks() {
        // Read from any SEM sensor's attributes (coordinator adds to all)
        const data = this._hass?.states[`${this._prefix}surplus_total_w`];
        const hours = data?.attributes?.schedule_surplus_hours;
        return this._hoursToBlocks(hours);
    }

    /** Get actual EV charging hours from coordinator data. */
    _getActualEvBlocks() {
        const data = this._hass?.states[`${this._prefix}surplus_total_w`];
        const hours = data?.attributes?.schedule_ev_hours;
        return this._hoursToBlocks(hours);
    }

    /** Return true if EV is currently charging. */
    _isEvCharging() {
        const evPower = parseFloat(this._stateObj('ev_power')?.state);
        if (!isNaN(evPower) && evPower > 10) return true;
        const chState = this._stateObj('charging_state')?.state;
        return chState && chState.toLowerCase() === 'charging';
    }

    /* ── SVG dimensions ── */

    // Layout constants
    static get MARGIN_LEFT() { return 36; }
    static get MARGIN_RIGHT() { return 8; }
    static get SVG_WIDTH() { return 600; }
    static get BAR_WIDTH() { return 600 - 36 - 8; } // 556
    static get ROW_HEIGHT() { return 18; }
    static get ROW_GAP() { return 4; }
    static get LABEL_Y() { return 12; }
    static get FIRST_ROW_Y() { return 20; }

    /** Convert day-fraction (0-1) to SVG x coordinate. */
    _toX(frac) {
        return SEMScheduleCard.MARGIN_LEFT + frac * SEMScheduleCard.BAR_WIDTH;
    }

    _t(key) {
        const lang = this._hass?.language;
        return (typeof semLocalize === 'function') ? semLocalize(key, lang) : key;
    }

    _update() {
        if (!this._hass) return;

        if (!this._rendered) {
            this._renderSkeleton();
            this._rendered = true;
        }

        const svg = this.shadowRoot.querySelector('.timeline-svg');
        if (!svg) return;

        const ML = SEMScheduleCard.MARGIN_LEFT;
        const BW = SEMScheduleCard.BAR_WIDTH;
        const RH = SEMScheduleCard.ROW_HEIGHT;
        const RG = SEMScheduleCard.ROW_GAP;
        const FRY = SEMScheduleCard.FIRST_ROW_Y;
        const W = SEMScheduleCard.SVG_WIDTH;

        const colors = this._colors;

        let svgContent = '';

        const T = this._theme || {};
        const textSecCol = T.textSec || '#888';
        const textTertCol = T.textTertiary || '#777';
        const rowBg = T.surface || 'rgba(255,255,255,0.03)';

        // ── Hour labels ──
        for (let h = 0; h <= 24; h += 2) {
            const x = this._toX(h / 24);
            svgContent += `<text x="${x}" y="${SEMScheduleCard.LABEL_Y}"
                text-anchor="middle" fill="${textSecCol}" font-size="9"
                font-family="'Segoe UI','Roboto',sans-serif"
                font-variant-numeric="tabular-nums">${h.toString().padStart(2, '0')}</text>`;
        }

        // Row labels (left side)
        const rowLabels = [this._t('tariff'), this._t('night'), this._t('surplus'), this._t('ev')];
        rowLabels.forEach((label, i) => {
            const y = FRY + i * (RH + RG) + RH / 2 + 3.5;
            svgContent += `<text x="${ML - 4}" y="${y}" text-anchor="end"
                fill="${textTertCol}" font-size="9" font-family="'Segoe UI','Roboto',sans-serif">${label}</text>`;
        });

        // ── Row backgrounds (subtle) ──
        for (let i = 0; i < 4; i++) {
            const y = FRY + i * (RH + RG);
            svgContent += `<rect x="${ML}" y="${y}" width="${BW}" height="${RH}"
                rx="3" fill="${rowBg}"/>`;
        }

        // ── Row 0: Tariff ──
        const tariffY = FRY;
        const tariffSchedule = this._getTariffSchedule();
        tariffSchedule.forEach(block => {
            const x = this._toX(block.start);
            const w = this._toX(block.end) - x;
            const fill = block.type === 'HT' ? colors.solar : '#66bb6a';
            const opacity = block.type === 'HT' ? 0.7 : 0.55;
            svgContent += `<rect x="${x}" y="${tariffY}" width="${w}" height="${RH}"
                rx="3" fill="${fill}" opacity="${opacity}"/>`;
            // Label inside block if wide enough
            if (w > 30) {
                const tariffLabel = this._t(block.type.toLowerCase());
                svgContent += `<text x="${x + w / 2}" y="${tariffY + RH / 2 + 3.5}"
                    text-anchor="middle" fill="rgba(255,255,255,0.85)" font-size="8"
                    font-weight="600" font-family="'Segoe UI','Roboto',sans-serif">${tariffLabel}</text>`;
            }
        });

        // ── Row 1: Night Window ──
        const nightY = FRY + (RH + RG);
        const night = this._getNightWindow();
        if (night) {
            if (night.start > night.end) {
                // Wraps midnight: draw two segments
                const x1 = this._toX(night.start);
                const w1 = this._toX(1) - x1;
                const x2 = this._toX(0);
                const w2 = this._toX(night.end) - x2;
                svgContent += `<rect x="${x1}" y="${nightY}" width="${w1}" height="${RH}"
                    rx="3" fill="#42a5f5" opacity="0.55"/>`;
                svgContent += `<rect x="${x2}" y="${nightY}" width="${w2}" height="${RH}"
                    rx="3" fill="#42a5f5" opacity="0.55"/>`;
            } else {
                const x = this._toX(night.start);
                const w = this._toX(night.end) - x;
                svgContent += `<rect x="${x}" y="${nightY}" width="${w}" height="${RH}"
                    rx="3" fill="#42a5f5" opacity="0.55"/>`;
            }
        }

        // ── Row 2: Surplus — predicted (faded) + actual (solid) ──
        const surplusY = FRY + 2 * (RH + RG);
        // Layer 1: predicted surplus window (faded background)
        const predicted = this._getPredictedSurplusWindow();
        if (predicted) {
            const x = this._toX(predicted.start);
            const w = this._toX(predicted.end) - x;
            svgContent += `<rect x="${x}" y="${surplusY}" width="${Math.max(w, 0)}" height="${RH}"
                rx="3" fill="#fdd835" opacity="0.18"/>`;
        }
        // Layer 2: actual surplus hours (solid overlay)
        for (const block of this._getActualSurplusBlocks()) {
            const x = this._toX(block.start);
            const w = this._toX(block.end) - x;
            svgContent += `<rect x="${x}" y="${surplusY}" width="${Math.max(w, 0)}" height="${RH}"
                rx="3" fill="#fdd835" opacity="0.6"/>`;
        }

        // ── Row 3: EV — actual charging hours (solid) + live indicator ──
        const evY = FRY + 3 * (RH + RG);
        // Layer 1: actual EV charging hours today
        for (const block of this._getActualEvBlocks()) {
            const x = this._toX(block.start);
            const w = this._toX(block.end) - x;
            svgContent += `<rect x="${x}" y="${evY}" width="${Math.max(w, 0)}" height="${RH}"
                rx="3" fill="${colors.ev}" opacity="0.55"/>`;
        }
        // Layer 2: live charging indicator (brighter block at current time)
        if (this._isEvCharging()) {
            const now = new Date();
            const nowFrac = (now.getHours() + now.getMinutes() / 60) / 24;
            const halfBlock = 0.5 / 24;
            const start = Math.max(0, nowFrac - halfBlock);
            const end = Math.min(1, nowFrac + halfBlock);
            const x = this._toX(start);
            const w = this._toX(end) - x;
            svgContent += `<rect x="${x}" y="${evY}" width="${w}" height="${RH}"
                rx="3" fill="${colors.ev}" opacity="0.85"/>`;
        }

        // ── Current time indicator (red vertical line) ──
        const now = new Date();
        const nowFrac = (now.getHours() + now.getMinutes() / 60) / 24;
        const nowX = this._toX(nowFrac);
        const lineTop = FRY - 2;
        const lineBottom = FRY + 4 * (RH + RG) - RG;
        svgContent += `<line x1="${nowX}" y1="${lineTop}" x2="${nowX}" y2="${lineBottom}"
            stroke="#ef5350" stroke-width="1.5" stroke-linecap="round" opacity="0.9"/>`;
        // Small triangle marker at top
        svgContent += `<polygon points="${nowX - 3},${lineTop} ${nowX + 3},${lineTop} ${nowX},${lineTop + 4}"
            fill="#ef5350" opacity="0.9"/>`;

        svg.innerHTML = svgContent;
    }

    _renderSkeleton() {
        const W = SEMScheduleCard.SVG_WIDTH;
        const RH = SEMScheduleCard.ROW_HEIGHT;
        const RG = SEMScheduleCard.ROW_GAP;
        const FRY = SEMScheduleCard.FIRST_ROW_Y;
        const totalHeight = FRY + 4 * (RH + RG) + 4;

        const T = (typeof semTheme === 'function') ? semTheme() : {};
        this._theme = T;
        const textCol = T.text    || '#e0e0e0';
        const dotCol  = T.dotColor || 'rgba(128,128,128,0.04)';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .wrap {
                    padding: 12px 14px 8px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 30%, rgba(72,143,194,0.04) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${dotCol} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: ${textCol};
                }
                .timeline-svg {
                    width: 100%;
                    height: auto;
                }
            </style>
            <ha-card>
                <div class="wrap">
                    <svg class="timeline-svg" viewBox="0 0 ${W} ${totalHeight}"
                        preserveAspectRatio="xMidYMid meet" role="img"
                        aria-label="24-hour schedule timeline"></svg>
                </div>
            </ha-card>
        `;
    }

    getCardSize() { return 2; }

    static getStubConfig() { return {}; }
}

customElements.define('sem-schedule-card', SEMScheduleCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'sem-schedule-card',
    name: 'SEM Schedule',
    description: '24-hour timeline showing tariff, night window, surplus window, and EV charging periods',
});
