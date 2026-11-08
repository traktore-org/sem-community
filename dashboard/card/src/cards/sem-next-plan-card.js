/**
 * SEM Next · Plan (#1321)
 *
 * The chosen day as one strip: hourly price bars with the cheap and the
 * expensive band, the sun forecast as a curve, and the plan's blocks on
 * three lanes (car, battery, loads), all from sensor.sem_energy_plan. Tap
 * a block for its reason. Below: one row per device with the one-night
 * overrides, the expected numbers, and today's decisions from the log.
 * "Show timeline per device" opens the lane-per-device drawing.
 *
 * Config:
 *   type: custom:sem-next-plan-card
 */

import { SEMNextBase, html, css, svg, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { semDefineCard } from '../base/sem-shared.js';
import { planLead, kwhOf } from '../util/next-lead.js';
import { laneModel, LANE_COLORS } from '../util/next-timeline.js';
import { stripModel, smoothPath, minutesToPlanEnd, LANE_COUNT } from '../util/next-strip.js';
import {
    WHY_KINDS, changeLabel, deviceName, earlierKey, filterRecords, isToday, plainReason, rowTime, whyChips,
} from '../util/why-rows.js';

export const WS_DECISION_LOG = 'solar_energy_management/decision_log';
/** The decisions list reads the log again this often while the screen is open. */
export const LOG_REFRESH_MS = 60000;
const DOMAIN = 'solar_energy_management';
const IDS = ['sensor.sem_energy_plan', 'sensor.sem_forecast_tomorrow_kwh', 'sensor.sem_forecast_today_kwh',
             'sensor.sem_tariff_price_level', 'sensor.sem_controllable_devices_count', 'switch.sem_energy_plan_actuation',
             'sensor.sem_charging_state', 'number.sem_expensive_price_threshold', 'select.sem_battery_mode',
             'sensor.sem_battery_dynamic_floor_pct', 'sensor.sem_forecast_trust_d2'];
// the per-device lanes fold
const W = 720, L = 54, ROW = 30, TOP = 24, BOTTOM = 20;
const SHOWN_ROWS = 6;
const KIND_COLOR = { ev: C.ev, battery_in: C.battery_in, battery_out: C.battery_out, load: C.home };
const KIND_ICON = { ev: 'mdi:car-electric', battery_in: 'mdi:battery-charging', battery_out: 'mdi:home-battery', load: 'mdi:power-plug' };

class SEMNextPlanCard extends SEMNextBase {
    static get properties() {
        return {
            _picked: { state: true }, _confirm: { state: true }, _day: { state: true }, _lanes: { state: true },
            _w: { state: true }, _records: { state: true }, _chip: { state: true }, _fold: { state: true },
            _logError: { state: true },
        };
    }
    // A 24 h axis in 380 px is unreadable: the per-device lanes keep their
    // width and scroll sideways inside their own box instead of shrinking.
    static get styles() {
        return [nextCss, css`
            .tl { overflow-x: auto; -webkit-overflow-scrolling: touch; margin-top: 8px; }
            .tl svg { display: block; min-width: 640px; }
            .tm { width: 42px; flex: 0 0 auto; }
            .reason .t { min-width: 0; }
        `];
    }

    constructor() {
        super();
        this._picked = null;       // block key in the strip
        this._pickedText = null;   // the lanes fold's picked block
        this._confirm = null;      // charger id awaiting "Charge now" confirmation
        this._savedMode = {};      // charger id → mode before "Charge now"
        this._day = 'today';
        this._lanes = false;
        this._w = 720;
        this._hostW = 0;
        this._ro = null;
        this._m = null;
        this._records = null;      // null = not loaded yet
        this._chip = '';           // '' = all devices
        this._fold = false;
        this._logError = false;
        this._loading = false;
        this._logTimer = null;
        this._local = {};          // device id → {action, until}, until the next plan
        this._localStamp = '';
    }

    connectedCallback() {
        super.connectedCallback();
        if (typeof ResizeObserver !== 'undefined' && !this._ro) {
            this._ro = new ResizeObserver((entries) => {
                const w = Math.floor(entries[0]?.contentRect?.width || 0);
                if (w > 0 && w !== this._hostW) {
                    this._hostW = w;
                    // the app frame pads 8 px, the card 16 px, each side
                    this._w = Math.max(240, Math.min(w, 1180) - 48);
                }
            });
            this._ro.observe(this);
        }
        this._stopLog();
        this._loadLog();
        this._logTimer = setInterval(() => this._loadLog(), LOG_REFRESH_MS);
    }

    disconnectedCallback() {
        if (this._ro) { this._ro.disconnect(); this._ro = null; }
        this._stopLog();
        super.disconnectedCallback();
    }

    set hass(hass) {
        super.hass = hass;
        if (hass && this._records === null) this._loadLog();
    }
    get hass() { return this._hass; }

    _watchIds() {
        const per = this._chargers.flatMap((cid) => [`select.sem_charger_${cid}_charge_mode`, `time.sem_charger_${cid}_target_time`]);
        return [...super._watchIds(), ...IDS, ...per];
    }

    // ── the decision log ──
    _stopLog() {
        if (this._logTimer) { clearInterval(this._logTimer); this._logTimer = null; }
    }

    async _loadLog() {
        if (this._loading || !this._hass?.callWS) return;
        this._loading = true;
        try {
            const res = await this._hass.callWS({ type: WS_DECISION_LOG });
            this._records = Array.isArray(res?.records) ? res.records : [];
            this._logError = false;
        } catch (_err) {
            if (this._records === null) this._records = [];
            this._logError = true;
        } finally {
            this._loading = false;
        }
    }

    // ── models ──
    _plan() { return this._attrs('sensor.sem_energy_plan'); }

    _devices() { return this._attrs('sensor.sem_controllable_devices_count').devices || {}; }

    _loads() {
        return Object.entries(this._devices()).map(([id, info]) => ({ id, name: info?.name || id }));
    }

    _model() {
        return laneModel({
            now: new Date(), plan: this._plan(),
            chargers: this._chargers.map((cid) => ({ id: cid, name: this._chargerName(cid) })),
            loads: this._loads(),
            nightStart: this._str('sensor.sem_night_start_time'), nightEnd: this._str('sensor.sem_night_end_time'),
            forecastTomorrowKwh: this._num('sensor.sem_forecast_tomorrow_kwh'),
            forecastTodayKwh: this._num('sensor.sem_forecast_today_kwh'),
        });
    }

    /** The earliest charger Charge-by time, 'HH:MM', or ''. */
    _departure() {
        const times = this._chargers.map((cid) => (this._str(`time.sem_charger_${cid}_target_time`) || '').slice(0, 5)).filter((t) => /^\d{2}:\d{2}$/.test(t)).sort();
        return times[0] || '';
    }

    _strip(plan) {
        const tomorrow = this._day === 'tomorrow';
        return stripModel({
            plan, day: this._day, now: new Date(),
            nightStart: this._str('sensor.sem_night_start_time'), nightEnd: this._str('sensor.sem_night_end_time'),
            forecastKwh: this._num(tomorrow ? 'sensor.sem_forecast_tomorrow_kwh' : 'sensor.sem_forecast_today_kwh'),
            expensiveThreshold: this._num('number.sem_expensive_price_threshold'),
            departure: this._departure(),
        });
    }

    _selected(sm) {
        return sm.blocks.find((b) => b.key === this._picked) || sm.blocks.find((b) => b.run) || sm.blocks[0] || null;
    }

    _blockName(b) {
        if (b.kind === 'battery_in') return this._t('next_battery_charging');
        if (b.kind === 'battery_out') return this._t('next_battery_to_house');
        if (b.kind === 'ev') {
            const cid = b.id.slice(3);
            return this._chargers.includes(cid) ? this._chargerName(cid) : (b.label || this._t('next_src_car'));
        }
        const id = b.id.replace(/^load:/, '');
        return this._devices()[id]?.name || b.label || this._t('next_lane_load');
    }

    _blockSpan(b) {
        return `${this._hhmm(new Date(b.start))} – ${this._hhmm(new Date(b.end))}`;
    }

    _blockTitle(b) {
        const kwh = b.kwh > 0.05 ? ` · ${this._kwh(b.kwh)}` : '';
        return `${this._blockName(b)} · ${this._blockSpan(b)}${kwh}`;
    }

    /** The not_scheduled entry's machine why, as a sentence. */
    _whyText(n) {
        const code = n?.why || n?.reason || '';
        const key = 'energy_plan_why_' + code;
        const said = this._t(key);
        return said && said !== key ? said : (n?.note || String(code));
    }

    _blockReason(b, plan) {
        if (b.provisional) return this._t('next_provisional_reason');
        const kw = this._fmt(b.powerW / 1000, 1);
        if (b.kind === 'battery_in') return plan.why ? String(plan.why) : this._tf('next_reason_battery_charge', { kw });
        if (b.kind === 'battery_out') return this._t('next_reason_battery_house');
        const demands = Array.isArray(plan.demands) ? plan.demands : [];
        const d = demands.find((x) => x.id === b.id);
        if (d?.note) return String(d.note);
        if (d?.status) return this._t('next_status_' + d.status);
        return this._tf(b.kind === 'ev' ? 'next_reason_ev_block' : 'next_reason_load_block', { kw, status: '', note: '' }).replace(/\s+/g, ' ').trim();
    }

    // ── the strip ──
    _stripSvg(sm) {
        const w = this._w || 720;
        const H = 172, L0 = 8, R0 = 8, top = 14, bh = 66, by = top + bh, lanesY = by + 16, laneH = 11, axisY = H - 6;
        const lanesH = LANE_COUNT * (laneH + 4);
        const x = (f) => L0 + f * (w - L0 - R0);
        const parts = [];
        for (const b of sm.bands.cheap) {
            parts.push(svg`<rect x="${x(b.x0)}" y="${top - 4}" width="${x(b.x1) - x(b.x0)}" height="${bh + 8}" fill="${C.good}" opacity=".10" rx="4"></rect>`);
        }
        for (const b of sm.bands.expensive) {
            parts.push(svg`<rect x="${x(b.x0)}" y="${top - 4}" width="${x(b.x1) - x(b.x0)}" height="${bh + 8}" fill="${C.bad}" opacity=".08" rx="4"></rect>`);
        }
        if (sm.sun) {
            const pts = sm.sun.points.map(([f, v]) => [x(f), by - v * bh * 0.95]);
            parts.push(svg`<path d="${smoothPath(pts)} L${x(sm.sun.x1)} ${by} L${x(sm.sun.x0)} ${by} Z" fill="${C.solar}" opacity=".14"></path>`);
        }
        if (sm.price) {
            const { min, max } = sm.price;
            for (const b of sm.bars) {
                const h = max > min ? 6 + ((b.price - min) / (max - min)) * (bh - 10) : bh * 0.5;
                parts.push(svg`<rect x="${x(b.x0) + 1}" y="${by - h}" width="${Math.max(1, x(b.x1) - x(b.x0) - 2)}" height="${h}" rx="2" fill="${C.fg3}" opacity="${b.past ? .25 : .5}">
                    <title>${String(b.h).padStart(2, '0')}:00 · ${this._fmt(b.price, 2)} ${this._currency()}/kWh</title></rect>`);
            }
            parts.push(svg`<text x="${x(0)}" y="${top - 2}" font-size="10" fill="${C.fg3}">${this._tf('next_price_range', { max: this._fmt(max, 2), min: this._fmt(min, 2), cur: this._currency() })}</text>`);
        }
        if (sm.sun) {
            parts.push(svg`<text x="${x(1)}" y="${top - 2}" font-size="10" fill="${C.fg3}" text-anchor="end">${this._tf('next_sun_kwh', { kwh: this._fmt(sm.sun.kwh, 1) })}</text>`);
        }
        const picked = this._selected(sm);
        for (const b of sm.blocks) {
            const y = lanesY + b.lane * (laneH + 4);
            const color = KIND_COLOR[b.kind] || C.home;
            const on = !!picked && picked.key === b.key;
            const go = (e) => { e.stopPropagation(); this._picked = b.key; };
            parts.push(svg`<g class="blk" tabindex="0" role="button" aria-label="${this._blockTitle(b)}" @click=${go}
                    @keydown=${(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(e); } }}>
                <rect x="${x(b.x0)}" y="${y}" width="${Math.max(6, x(b.x1) - x(b.x0))}" height="${laneH}" rx="4" fill="${color}"
                    fill-opacity="${b.run ? 1 : .55}" stroke="${color}" stroke-width="${on ? 2 : 1}" stroke-dasharray="${b.run ? nothing : '3 2'}"></rect></g>`);
        }
        for (const t of sm.ticks) {
            parts.push(svg`<text x="${x(t.x)}" y="${axisY}" font-size="10" fill="${C.fg3}" text-anchor="${t.x === 0 ? 'start' : t.x === 1 ? 'end' : 'middle'}">${t.label}</text>`);
        }
        if (sm.lines.now !== null) {
            const nx = x(sm.lines.now), right = sm.lines.now > 0.85;
            parts.push(svg`<line x1="${nx}" x2="${nx}" y1="${top - 6}" y2="${lanesY + lanesH}" stroke="${C.accent}" stroke-width="1.5"></line>
                <text x="${right ? nx - 4 : nx + 4}" y="${top + 8}" font-size="10" fill="${C.accent}" font-weight="500" text-anchor="${right ? 'end' : 'start'}">${this._t('next_now_marker')}</text>`);
        }
        if (sm.lines.departure) {
            const dx = x(sm.lines.departure.x), right = sm.lines.departure.x > 0.8;
            parts.push(svg`<line x1="${dx}" x2="${dx}" y1="${top - 6}" y2="${lanesY + lanesH}" stroke="${C.fg2}" stroke-width="1.5" stroke-dasharray="3 3"></line>
                <text x="${right ? dx - 4 : dx + 4}" y="${top + 8}" font-size="10" fill="${C.fg2}" font-weight="500" text-anchor="${right ? 'end' : 'start'}">${sm.lines.departure.label} ${this._t('next_car_ready')}</text>`);
        }
        return svg`<svg class="chart" viewBox="0 0 ${w} ${H}" width="${w}" height="${H}" role="img" aria-label="${this._t('next_price_and_plan')}">${parts}</svg>`;
    }

    _legend() {
        const t = (k) => this._t(k);
        const item = (color, label, op = 1) => html`<span><i style="background:${color};opacity:${op}"></i>${label}</span>`;
        return html`<div class="legend">
            ${item(C.ev, t('next_src_car'))}${item(C.battery_in, t('next_battery_charging'))}${item(C.battery_out, t('next_battery_to_house'))}
            ${item(C.home, t('next_loads'))}${item(C.solar, t('next_src_forecast'), .4)}${item(C.good, t('next_cheap'), .3)}${item(C.bad, t('next_expensive'), .3)}
            <span class="dim">${t('next_dashed_hint')}</span></div>`;
    }

    _stripPills(plan) {
        const t = (k) => this._t(k);
        const out = [];
        if (plan.fits === true) out.push(this._pill(t('next_fits_yes'), 'ok', { icon: 'mdi:check' }));
        else if (plan.fits === false) out.push(this._pill(t('next_fits_no'), 'warn'));
        if (plan.computed_at) out.push(this._pill(this._tf('next_made_at', { time: this._hhmm(plan.computed_at) })));
        if (this._day === 'tomorrow') {
            const tmw = plan.tomorrow;
            const prices = tmw ? ' · ' + t(tmw.prices === 'final' ? 'next_prices_final' : 'next_prices_pending') : '';
            out.push(this._pill(t('next_pill_provisional') + prices));
        } else if (plan.computed_at) {
            out.push(this._pill(plan.actuation ? t('next_pill_live') : t('next_pill_shadow'), plan.actuation ? 'ok' : ''));
        }
        return out;
    }

    _stripSec(plan, m) {
        const t = (k) => this._t(k);
        const sm = this._strip(plan);
        const sel = this._selected(sm);
        const hasStrip = sm.bars.length > 0 || sm.blocks.length > 0 || !!sm.sun;
        const seg = this._seg([{ key: 'today', label: t('next_today') }, { key: 'tomorrow', label: t('next_tomorrow') }], this._day,
            (k) => { this._day = k; this._picked = null; }, { small: true });
        const body = html`
            ${hasStrip ? html`<div class="strip">${this._stripSvg(sm)}</div>` : html`<p class="help">${t('next_plan_none')}</p>`}
            ${hasStrip ? this._legend() : nothing}
            ${sel ? html`<div class="reason" style="--c:${KIND_COLOR[sel.kind] || C.home}">${this._icon(sel.run ? 'mdi:play-circle' : 'mdi:clock-outline')}
                    <div class="t"><b>${this._blockName(sel)}</b> · ${this._blockSpan(sel)}${sel.kwh > 0.05 ? ' · ' + this._kwh(sel.kwh) : ''}
                    <div class="sm muted">${this._blockReason(sel, plan)}</div></div></div>`
                : (hasStrip ? html`<div class="reason">${this._icon('mdi:gesture-tap')}<div class="t"><b>${t('next_tap_block')}</b><div class="sm muted">${t('next_tap_block_sub')}</div></div></div>` : nothing)}
            <div class="btns" style="margin-top:10px">
                ${this._btn(t(this._lanes ? 'next_hide_lanes' : 'next_show_lanes'), () => { this._lanes = !this._lanes; }, { small: true, icon: 'mdi:chart-timeline' })}
                ${this._stripPills(plan)}
            </div>
            ${this._lanes ? (m.computedAt ? html`${this._timeline(m)}
                ${this._pickedText ? html`<div class="reason"><b>${this._pickedText.title}</b><span class="sm muted">${this._pickedText.text}</span></div>` : nothing}`
                : html`<p class="help">${t('next_plan_none')}</p>`) : nothing}`;
        return this._sec(t('next_price_and_plan'), body, { cls: 'span2', extra: seg });
    }

    // ── the per-device lanes fold (the one-tap-deeper view) ──
    _timeline(m) {
        const lanes = m.lanes;
        const rows = 1 + (m.price ? 1 : 0) + lanes.length;
        const H = TOP + rows * ROW + BOTTOM;
        const x = (f) => L + f * (W - L - 8);
        let r = 0;
        const parts = [];
        const laneLabel = (label, i) => svg`<text x="4" y="${TOP + i * ROW + ROW * 0.64}" font-size="11" font-weight="600" fill="${C.fg2}">${label}</text>
            <line x1="${L}" y1="${TOP + (i + 1) * ROW}" x2="${W - 8}" y2="${TOP + (i + 1) * ROW}" stroke="var(--n-line)"></line>`;
        // Sun lane: a bell over the daylight span.
        parts.push(laneLabel(this._t('next_lane_sun'), r));
        if (m.sun) {
            const pts = [];
            for (let i = 0; i <= 24; i++) {
                const f = i / 24;
                const fx = m.sun.x0 + (m.sun.x1 - m.sun.x0) * f;
                const y = TOP + r * ROW + ROW * 0.9 - Math.sin(Math.PI * f) * ROW * 0.78;
                pts.push(`${x(fx).toFixed(1)},${y.toFixed(1)}`);
            }
            parts.push(svg`<polygon points="${x(m.sun.x0)},${TOP + r * ROW + ROW * 0.9} ${pts.join(' ')} ${x(m.sun.x1)},${TOP + r * ROW + ROW * 0.9}" fill="${C.solar}" opacity="0.35" stroke="${C.solar}" stroke-width="1.5" stroke-dasharray="4 3"></polygon>`);
            if (Number.isFinite(m.sun.kwh)) parts.push(svg`<text x="${x((m.sun.x0 + m.sun.x1) / 2)}" y="${TOP + r * ROW + ROW * 0.45}" font-size="10" font-weight="600" text-anchor="middle" fill="${C.fg}">${this._fmt(m.sun.kwh, 1)} kWh</text>`);
        }
        r++;
        if (m.price) {
            parts.push(laneLabel(this._t('next_lane_price'), r));
            const max = Math.max(...m.price.map((p) => p.price), 0.01);
            for (const p of m.price) {
                const h = Math.max(3, (ROW - 8) * (p.price / max));
                parts.push(svg`<rect x="${x(p.x0) + 0.5}" y="${TOP + r * ROW + ROW - 4 - h}" width="${Math.max(1, x(p.x1) - x(p.x0) - 1)}" height="${h}" fill="${p.cheap ? C.good : LANE_COLORS.price}" opacity="0.8"></rect>`);
            }
            r++;
        }
        lanes.forEach((lane, li) => {
            parts.push(laneLabel(lane.label || this._t(lane.labelKey), r));
            lane.blocks.forEach((b, bi) => {
                const key = `${li}:${bi}`;
                const picked = this._pickedText && this._pickedText.key === key;
                parts.push(svg`<rect x="${x(b.x0) + 1}" y="${TOP + r * ROW + 5}" width="${Math.max(2, x(b.x1) - x(b.x0) - 2)}" height="${ROW - 10}" rx="6"
                    fill="${b.color || lane.color}" opacity="${this._pickedText && !picked ? 0.5 : 0.9}"
                    stroke="${b.dashed ? C.fg : 'none'}" stroke-width="1" stroke-dasharray="${b.dashed ? '3 3' : nothing}"
                    style="cursor:pointer" @click=${() => this._pick(key, lane, b)}></rect>`);
            });
            r++;
        });
        const ticks = m.ticks.map((t) => svg`<line x1="${x(t.x)}" y1="${TOP - 6}" x2="${x(t.x)}" y2="${TOP + rows * ROW}" stroke="var(--n-line)"></line>
            <text x="${x(t.x)}" y="${TOP + rows * ROW + 14}" font-size="10" text-anchor="middle" fill="${C.fg2}">${t.label}</text>`);
        return html`<div class="tl"><svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${this._t('next_timeline')}">
            ${ticks}${parts}
            <line x1="${x(0)}" y1="${TOP - 10}" x2="${x(0)}" y2="${TOP + rows * ROW}" stroke="${C.accent}" stroke-width="2"></line>
            <text x="${x(0) + 4}" y="${TOP - 12}" font-size="10" font-weight="700" fill="${C.accent}">${this._t('next_now_marker')}</text>
        </svg></div>`;
    }

    _pick(key, lane, b) {
        this._pickedText = this._pickedText && this._pickedText.key === key ? null
            : { key, title: `${lane.label || this._t(lane.labelKey)} · ${this._span(b)}`, text: this._tf(b.reasonKey, b.params).replace(/\s+/g, ' ').trim() };
        this.requestUpdate();
    }

    _span(b) {
        const m = this._m;
        if (!m) return '';
        const at = (f) => this._hhmm(new Date(m.start + f * (m.end - m.start)));
        return `${at(b.x0)} → ${at(b.x1)}`;
    }

    // ── per device ──
    _windowOf(blocks, id) {
        const mine = blocks.filter((b) => b.id === id && Number.isFinite(Date.parse(b.start)) && Number.isFinite(Date.parse(b.end)))
            .sort((p, q) => Date.parse(p.start) - Date.parse(q.start));
        if (!mine.length) return '';
        return `${this._hhmm(mine[0].start)} – ${this._hhmm(mine[mine.length - 1].end)}`;
    }

    _devRow(icon, color, name, rest, sub, btns) {
        return html`<div class="row" style="--c:${color}"><div class="k">${this._icon(icon)}<span class="t"><b>${name}</b>${rest ? html` · ${rest}` : nothing}${sub ? html`<br><span class="sm muted">${sub}</span>` : nothing}</span></div>${btns.length ? html`<div class="btns">${btns}</div>` : nothing}</div>`;
    }

    _overrideOf(deviceId) {
        const ov = this._attrs('sensor.sem_charging_state').per_charger_plan_override || {};
        const rec = ov[deviceId] || this._local[deviceId] || null;
        return rec && rec.action ? { action: String(rec.action), until: String(rec.until || '') } : null;
    }

    _overrideText(ov) {
        const word = this._t('next_override_' + ov.action);
        return ov.until ? this._tf('next_override_until', { action: word, time: ov.until }) : word;
    }

    _chargerRow(cid, plan, blocks, demands, notSched) {
        const t = (k) => this._t(k);
        const obs = this._obs();
        const id = `ev:${cid}`;
        const sel = `select.sem_charger_${cid}_charge_mode`;
        const mode = this._str(sel);
        const win = this._windowOf(blocks, id);
        const kwh = kwhOf(blocks, (x) => x === id);
        const d = demands.find((x) => x.id === id);
        const ns = notSched.find((x) => x.id === id);
        const bits = [];
        if (d?.note) bits.push(String(d.note));
        else if (d?.status) bits.push(t('next_status_' + d.status));
        else if (ns) bits.push(this._whyText(ns));
        else if (!win) bits.push(t('next_nothing_planned'));
        if (mode) bits.push(this._tf('next_mode_now', { mode: t('charge_mode_' + mode) || mode }));
        const ov = this._overrideOf(cid);
        if (ov) bits.push(this._overrideText(ov));
        const forced = mode === 'always_max' && !!this._savedMode[cid];
        const btns = [];
        if (this._confirm === cid) {
            btns.push(this._btn(t('next_confirm'), () => this._chargeNow(cid, sel, mode), { small: true, primary: true, disabled: obs }));
            btns.push(this._btn(t('next_cancel'), () => { this._confirm = null; }, { small: true }));
        } else if (ov || forced) {
            btns.push(this._btn(t('next_back_to_plan'), () => this._backToPlan(cid, sel, !!ov), { small: true, disabled: obs }));
        } else {
            btns.push(this._btn(t('next_skip'), () => this._override(cid, 'skip', minutesToPlanEnd(plan, new Date()), plan), { small: true, disabled: obs }));
            btns.push(this._btn(t('next_start_now'), () => this._override(cid, 'force', minutesToPlanEnd(plan, new Date()), plan), { small: true, primary: true, disabled: obs }));
            if (mode) btns.push(this._btn(t('next_charge_now'), () => { this._confirm = cid; }, { small: true, ghost: true, disabled: obs || mode === 'always_max' }));
        }
        const rest = win ? `${win}${kwh > 0.05 ? ' · ' + this._kwh(kwh) : ''}` : '';
        return this._devRow('mdi:car-electric', C.ev, this._chargerName(cid), rest, bits.join(' · '), btns);
    }

    _batteryRow(plan, blocks, demands) {
        const t = (k) => this._t(k);
        const obs = this._obs();
        const floor = this._num('sensor.sem_battery_dynamic_floor_pct');
        const slots = Array.isArray(plan.slots) ? plan.slots : [];
        const runs = Array.isArray(plan.batt_runs) ? plan.batt_runs : [];
        const parts = [];
        if (floor !== null) parts.push(this._tf('next_batt_holds', { floor: Math.round(floor) }));
        const inWin = this._windowOf(blocks.filter((b) => String(b.id).startsWith('battery')).map((b) => ({ ...b, id: 'battery' })), 'battery');
        if (inWin) parts.push(`${t('next_battery_charging')} ${inWin}`);
        const first = runs.length && Array.isArray(runs[0]) ? slots[runs[0][0]] : null;
        const last = runs.length && Array.isArray(runs[runs.length - 1]) ? slots[runs[runs.length - 1][1]] : null;
        if (first && last) parts.push(`${t('next_to_house')} ${this._hhmm(first.start)} – ${this._hhmm(last.end)}`);
        const d = demands.find((x) => String(x.id).startsWith('battery'));
        const arb = plan.arbitrage;
        const sub = d?.note ? String(d.note) : (plan.why ? String(plan.why) : (arb && arb.enabled && arb.reason ? String(arb.reason) : ''));
        const mode = this._str('select.sem_battery_mode');
        const options = this._attrs('select.sem_battery_mode').options || [];
        const btns = [];
        if (mode && mode !== 'auto' && options.includes('auto')) {
            btns.push(this._btn(t('next_back_to_plan'), () => this._selectOption('select.sem_battery_mode', 'auto'), { small: true, disabled: obs }));
        } else if (mode && options.includes('force_discharge')) {
            btns.push(this._btn(t('next_sell'), () => this._selectOption('select.sem_battery_mode', 'force_discharge'), { small: true, disabled: obs }));
        }
        const modeText = mode && mode !== 'auto' ? this._tf('next_mode_now', { mode: t('battery_mode_' + mode) || mode }) : '';
        return this._devRow('mdi:home-battery', C.battery_out, t('next_src_battery'), parts.join(' · '), [sub, modeText].filter(Boolean).join(' · '), btns);
    }

    _loadRow(id, plan, blocks, demands, notSched) {
        const t = (k) => this._t(k);
        const obs = this._obs();
        const key = id.replace(/^load:/, '');
        const d = demands.find((x) => x.id === id);
        const ns = notSched.find((x) => x.id === id);
        const name = this._devices()[key]?.name || d?.label || ns?.label || key;
        const win = this._windowOf(blocks, id);
        const kwh = win ? kwhOf(blocks, (x) => x === id) : Number(d?.planned_kwh) || 0;
        const bits = [];
        if (d?.note) bits.push(String(d.note));
        else if (d?.status) bits.push(t('next_status_' + d.status));
        else if (ns) bits.push(this._whyText(ns));
        const ov = this._overrideOf(key);
        if (ov) bits.push(this._overrideText(ov));
        const btns = [];
        if (ov) {
            btns.push(this._btn(t('next_back_to_plan'), () => this._overrideClear(key), { small: true, disabled: obs }));
        } else if (win) {
            btns.push(this._btn(t('next_skip'), () => this._override(key, 'skip', minutesToPlanEnd(plan, new Date()), plan), { small: true, disabled: obs }));
        } else {
            btns.push(this._btn(t('next_run_anyway'), () => this._override(key, 'force', minutesToPlanEnd(plan, new Date()), plan), { small: true, disabled: obs }));
        }
        const rest = win ? `${win}${kwh > 0.05 ? ' · ' + this._kwh(kwh) : ''}` : t('next_not_scheduled');
        return this._devRow('mdi:power-plug', C.home, name, rest, bits.join(' · '), btns);
    }

    _deviceSec(plan) {
        const t = (k) => this._t(k);
        const blocks = Array.isArray(plan.blocks) ? plan.blocks : [];
        const demands = Array.isArray(plan.demands) ? plan.demands : [];
        const notSched = Array.isArray(plan.not_scheduled) ? plan.not_scheduled : [];
        const rows = this._chargers.map((cid) => this._chargerRow(cid, plan, blocks, demands, notSched));
        const hasBattery = plan.has_battery !== false
            && (this._has('select.sem_battery_mode') || blocks.some((b) => String(b.id).startsWith('battery')) || (Array.isArray(plan.batt_runs) && plan.batt_runs.length > 0));
        if (hasBattery) rows.push(this._batteryRow(plan, blocks, demands));
        const loadIds = new Set();
        for (const d of demands) if (String(d.id).startsWith('load:')) loadIds.add(String(d.id));
        for (const b of blocks) if (String(b.id).startsWith('load:')) loadIds.add(String(b.id));
        for (const n of notSched) if (String(n.id).startsWith('load:')) loadIds.add(String(n.id));
        for (const id of loadIds) rows.push(this._loadRow(id, plan, blocks, demands, notSched));
        if (!rows.length) return nothing;
        return this._sec(t('next_per_device'), html`<div class="rows">${rows}</div>
            <p class="help">${this._obs() ? t('next_observing_hint') : t('next_override_help')}</p>`);
    }

    async _override(deviceId, action, minutes, plan) {
        const mins = Math.max(1, Math.min(1440, Math.round(Number(minutes) || 60)));
        if (!await this._callService(DOMAIN, 'plan_override', { device_id: deviceId, action, minutes: mins })) return;
        this._local = { ...this._local, [deviceId]: { action, until: this._hhmm(new Date(Date.now() + mins * 60e3)) } };
        this._localStamp = String(plan?.computed_at || '');
        this.requestUpdate();
    }

    async _overrideClear(deviceId) {
        if (!await this._callService(DOMAIN, 'plan_override_clear', { device_id: deviceId })) return false;
        const { [deviceId]: _gone, ...rest } = this._local;
        this._local = rest;
        this.requestUpdate();
        return true;
    }

    async _chargeNow(cid, sel, mode) {
        this._confirm = null;
        if (await this._callService('select', 'select_option', { entity_id: sel, option: 'always_max' })) {
            this._savedMode = { ...this._savedMode, [cid]: mode };
        }
    }

    async _backToPlan(cid, sel, hasOverride) {
        if (hasOverride && !await this._overrideClear(cid)) return;
        const prev = this._savedMode[cid];
        if (prev) {
            if (!await this._callService('select', 'select_option', { entity_id: sel, option: prev })) return;
            const { [cid]: _gone, ...rest } = this._savedMode;
            this._savedMode = rest;
        }
        this.requestUpdate();
    }

    // ── expected ──
    _expectedSec(plan, m) {
        const t = (k) => this._t(k);
        const obs = this._obs();
        const tiles = [];
        const cost = Number(plan.total_cost);
        if (Array.isArray(plan.blocks) && Number.isFinite(cost)) {
            const gridKwh = kwhOf(plan.blocks, (id) => !String(id).startsWith('battery_out'));
            tiles.push({ label: t('next_grid_cost'), value: this._fmt(cost, 2), unit: this._currency(), sub: `${this._kwh(gridKwh)} · ${t('next_tonight')}` });
        }
        const sun = this._num('sensor.sem_forecast_tomorrow_kwh');
        if (sun !== null) {
            const trust = this._num('sensor.sem_forecast_trust_d2');
            const sub = trust !== null && trust > 0 && trust <= 1.5
                ? `${t('next_forecast')} · ${this._tf('next_trusted', { pct: Math.round(trust * 100) })}` : t('next_forecast');
            tiles.push({ label: t('next_sun_tomorrow'), value: this._fmt(sun, 1), unit: 'kWh', sub });
        }
        const rows = [];
        const arb = plan.arbitrage;
        if (arb && arb.enabled) {
            const profit = Number(arb.est_profit);
            rows.push(this._row('mdi:swap-vertical', t('next_arbitrage'), arb.opportunity ? (Number.isFinite(profit) ? this._money(profit) : t('next_yes')) : t('next_off'), arb.reason || ''));
        }
        if (this._has('switch.sem_energy_plan_actuation')) {
            const on = this._str('switch.sem_energy_plan_actuation') === 'on';
            rows.push(this._row('mdi:toggle-switch-outline', t('next_plan_acts'),
                this._btn(on ? t('next_on') : t('next_off'), () => this._toggleSwitch('switch.sem_energy_plan_actuation'), { small: true, primary: on, disabled: obs }),
                t('next_actuation_sub')));
        }
        rows.push(this._row('mdi:sync', t('next_replan'),
            this._btn(t('next_now_btn'), () => this._callService(DOMAIN, 'replan', {}), { small: true, disabled: obs }),
            m.computedAt ? this._tf('next_replan_last', { time: this._hhmm(m.computedAt) }) : ''));
        return this._sec(t('next_expected'), html`${tiles.length ? this._tiles(tiles, { three: tiles.length === 3 }) : nothing}
            <div class="rows" style="margin-top:8px">${rows}</div>`);
    }

    // ── decisions today ──
    _logRow(rec, many) {
        const t = (k) => this._t(k);
        const tz = this._hass?.config?.time_zone;
        const lang = this._hass?.language || 'en';
        const kind = WHY_KINDS[rec.device_kind] || WHY_KINDS.load;
        const plain = plainReason(rec, t);
        const why = plain || rec.text || '';
        return html`<div class="row" style="--c:${kind.color}"><div class="k"><span class="dim num sm tm">${rowTime(rec.time, lang, new Date(), tz)}</span>
            <span class="t"><b>${deviceName(rec, t, many[rec.device_kind] > 1)}</b> · ${changeLabel(rec, t)}${rec.observer ? html` ${this._pill(t('why_observer'), 'warn')}` : nothing}
            ${why ? html`<br><span class="sm muted" title="${plain ? rec.text || '' : ''}">${why}</span>` : nothing}</span></div></div>`;
    }

    _decisionsSec() {
        const t = (k) => this._t(k);
        const all = this._records || [];
        const chips = whyChips(all, t);
        const chip = chips.some((c) => c.key === this._chip) ? this._chip : '';
        const many = {};
        for (const c of chips) many[c.kind] = (many[c.kind] || 0) + 1;
        const rows = filterRecords(all, chip);
        const tz = this._hass?.config?.time_zone;
        const todays = rows.filter((r) => isToday(r.time, new Date(), tz));
        const shown = (todays.length ? todays : rows).slice(0, SHOWN_ROWS);
        const earlier = rows.slice(shown.length);
        const body = html`
            ${chips.length ? this._seg([{ key: '', label: t('why_all') }, ...chips.map((c) => ({ key: c.key, label: c.name }))], chip, (k) => { this._chip = k; }, { small: true }) : nothing}
            ${this._logError ? html`<p class="help">${t('why_load_error')}</p>` : nothing}
            ${this._records !== null && !rows.length && !this._logError ? html`<p class="help">${t('why_empty')}</p>` : nothing}
            <div class="rows" style="margin-top:8px">${shown.map((r) => this._logRow(r, many))}${this._fold ? earlier.map((r) => this._logRow(r, many)) : nothing}</div>
            ${earlier.length ? this._link(this._fold ? t('next_less') : this._tf(earlierKey(earlier, new Date(), tz), { n: earlier.length }) + ' ›', () => { this._fold = !this._fold; }) : nothing}`;
        return this._sec(t('next_decisions_today'), body);
    }

    // ── lead ──
    _lead(plan, m) {
        if (this._day === 'tomorrow') {
            const sun = this._num('sensor.sem_forecast_tomorrow_kwh');
            const sunLine = sun !== null ? this._tf('next_plan_tmw_main', { sun: this._fmt(sun, 1) }) : '';
            const tmw = plan.tomorrow;
            if (!tmw) return { main: this._t('next_plan_tmw_none'), sub: sunLine };
            return { main: sunLine || this._t('next_plan_tmw_plain'), sub: this._t(tmw.prices === 'final' ? 'next_plan_tmw_sub_final' : 'next_plan_tmw_sub_prelim') };
        }
        const lead = planLead(plan, {
            computedAt: m.computedAt ? this._hhmm(m.computedAt) : '',
            cost: Number.isFinite(Number(m.cost)) ? this._money(Number(m.cost)) : '',
            fitsKey: m.fits === undefined ? '' : this._t(m.fits ? 'next_fits_yes' : 'next_fits_no'),
            sunTomorrowKwh: this._num('sensor.sem_forecast_tomorrow_kwh'),
        });
        const flat = (this._str('sensor.sem_tariff_price_level') || 'flat') === 'flat';
        const main = this._tf(lead.main.key, lead.main.params);
        const sub = lead.sub ? this._tf(lead.sub.key, lead.sub.params) + (flat ? ' ' + this._t('next_one_rate_sub') : '') : '';
        return { main, sub };
    }

    render() {
        if (!this._hass) return nothing;
        const plan = this._plan();
        const stamp = String(plan.computed_at || '');
        if (stamp !== this._localStamp) { this._local = {}; this._localStamp = stamp; }
        const m = this._model();
        this._m = m;
        return this._frame(this._lead(plan, m), html`<div class="grid">
            ${this._stripSec(plan, m)}
            ${this._deviceSec(plan)}
            ${this._expectedSec(plan, m)}
            ${this._decisionsSec()}
        </div>`);
    }
}

semDefineCard('sem-next-plan-card', SEMNextPlanCard, {
    type: 'sem-next-plan-card',
    name: 'SEM Next · Plan',
    description: 'The day as one strip: prices, sun, the plan per device, the one-night overrides and today\'s decisions',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-plan-card',
    preview: true,
});
