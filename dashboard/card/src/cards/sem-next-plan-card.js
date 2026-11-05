/**
 * SEM Next · Plan (#1321)
 *
 * The next 24 hours as one picture: the sun, the price when it moves,
 * the grid, the battery and one lane per charger and load, from
 * sensor.sem_energy_plan. Tap a block for its reason. Below: why this
 * plan, the expected numbers, and the one change a user can make now.
 *
 * Config:
 *   type: custom:sem-next-plan-card
 */

import { SEMNextBase, html, svg, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { semDefineCard } from '../base/sem-shared.js';
import { planLead, kwhOf } from '../util/next-lead.js';
import { laneModel, LANE_COLORS } from '../util/next-timeline.js';

const IDS = ['sensor.sem_energy_plan', 'sensor.sem_forecast_tomorrow_kwh', 'sensor.sem_forecast_today_kwh',
             'sensor.sem_tariff_price_level', 'sensor.sem_controllable_devices_count', 'switch.sem_energy_plan_actuation'];
const W = 720, L = 54, ROW = 30, TOP = 24, BOTTOM = 20;

class SEMNextPlanCard extends SEMNextBase {
    static get properties() { return { _picked: { state: true }, _confirm: { state: true } }; }
    static get styles() { return nextCss; }

    constructor() {
        super();
        this._picked = null;
        this._confirm = null;     // charger id awaiting "Charge now" confirmation
        this._savedMode = {};     // charger id → mode before "Charge now"
    }

    _watchIds() {
        const per = this._chargers.map((cid) => `select.sem_charger_${cid}_charge_mode`);
        return [...super._watchIds(), ...IDS, ...per];
    }

    _loads() {
        const devices = this._attrs('sensor.sem_controllable_devices_count').devices || {};
        return Object.entries(devices).map(([id, info]) => ({ id, name: info?.name || id }));
    }

    _model() {
        return laneModel({
            now: new Date(), plan: this._attrs('sensor.sem_energy_plan'),
            chargers: this._chargers.map((cid) => ({ id: cid, name: this._chargerName(cid) })),
            loads: this._loads(),
            nightStart: this._str('sensor.sem_night_start_time'), nightEnd: this._str('sensor.sem_night_end_time'),
            forecastTomorrowKwh: this._num('sensor.sem_forecast_tomorrow_kwh'),
            forecastTodayKwh: this._num('sensor.sem_forecast_today_kwh'),
        });
    }

    _timeline(m) {
        const lanes = m.lanes;
        const rows = 1 + (m.price ? 1 : 0) + lanes.length;
        const H = TOP + rows * ROW + BOTTOM;
        const x = (f) => L + f * (W - L - 8);
        let r = 0;
        const parts = [];
        const laneLabel = (label, i) => svg`<text x="4" y="${TOP + i * ROW + ROW * 0.64}" font-size="11" font-weight="600" fill="var(--secondary-text-color)">${label}</text>
            <line x1="${L}" y1="${TOP + (i + 1) * ROW}" x2="${W - 8}" y2="${TOP + (i + 1) * ROW}" stroke="var(--divider-color)"></line>`;
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
            if (Number.isFinite(m.sun.kwh)) parts.push(svg`<text x="${x((m.sun.x0 + m.sun.x1) / 2)}" y="${TOP + r * ROW + ROW * 0.45}" font-size="10" font-weight="600" text-anchor="middle" fill="var(--primary-text-color)">${this._fmt(m.sun.kwh, 1)} kWh</text>`);
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
                const picked = this._picked === key;
                parts.push(svg`<rect x="${x(b.x0) + 1}" y="${TOP + r * ROW + 5}" width="${Math.max(2, x(b.x1) - x(b.x0) - 2)}" height="${ROW - 10}" rx="6"
                    fill="${b.color || lane.color}" opacity="${this._picked && !picked ? 0.5 : 0.9}"
                    stroke="${b.dashed ? 'var(--primary-text-color)' : 'none'}" stroke-width="1" stroke-dasharray="${b.dashed ? '3 3' : ''}"
                    style="cursor:pointer" @click=${() => this._pick(key, lane, b)}></rect>`);
            });
            r++;
        });
        const ticks = m.ticks.map((t) => svg`<line x1="${x(t.x)}" y1="${TOP - 6}" x2="${x(t.x)}" y2="${TOP + rows * ROW}" stroke="var(--divider-color)"></line>
            <text x="${x(t.x)}" y="${TOP + rows * ROW + 14}" font-size="10" text-anchor="middle" fill="var(--secondary-text-color)">${t.label}</text>`);
        return html`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${this._t('next_timeline')}">
            ${ticks}${parts}
            <line x1="${x(0)}" y1="${TOP - 10}" x2="${x(0)}" y2="${TOP + rows * ROW}" stroke="${C.accent}" stroke-width="2"></line>
            <text x="${x(0) + 4}" y="${TOP - 12}" font-size="10" font-weight="700" fill="${C.accent}">${this._t('next_now_marker')}</text>
        </svg>`;
    }

    _pick(key, lane, b) {
        this._picked = this._picked === key ? null : key;
        this._pickedText = this._picked
            ? { title: `${lane.label || this._t(lane.labelKey)} · ${this._span(b)}`, text: this._tf(b.reasonKey, b.params) }
            : null;
    }

    _span(b) {
        const m = this._m;
        if (!m) return '';
        const at = (f) => { const d = new Date(m.start + f * (m.end - m.start)); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
        return `${at(b.x0)} → ${at(b.x1)}`;
    }

    _why(m) {
        const rows = [];
        const plan = this._attrs('sensor.sem_energy_plan');
        if (m.why) rows.push({ dot: 'P', color: C.accent, title: this._t('next_plan_says'), text: String(m.why) });
        for (const d of (Array.isArray(plan.demands) ? plan.demands : [])) {
            const isEv = String(d.id).startsWith('ev:');
            const name = isEv ? this._chargerName(String(d.id).slice(3)) : String(d.id).replace(/^(load|battery):?/, '') || this._t('next_src_battery');
            rows.push({ dot: isEv ? 'EV' : (String(d.id).startsWith('battery') ? 'B' : 'L'), color: isEv ? C.ev : (String(d.id).startsWith('battery') ? C.battery_in : C.home),
                title: `${name}: ${this._t('next_status_' + (d.status || 'fits'))}`, text: d.note || '' });
        }
        for (const n of m.notScheduled) rows.push({ dot: '!', color: C.warn, title: this._t('next_not_scheduled'), text: typeof n === 'string' ? n : (n?.id || '') + ' ' + (n?.reason || n?.note || '') });
        if (!rows.length) return nothing;
        return html`<div class="sec"><h3>${this._t('next_why_plan')}</h3><div class="why">
            ${rows.map((r) => html`<div class="row"><div class="dot" style="background:${r.color}">${r.dot}</div><div><b>${r.title}</b>${r.text ? html`<span>${r.text}</span>` : nothing}</div></div>`)}
        </div></div>`;
    }

    _expected(m) {
        const plan = this._attrs('sensor.sem_energy_plan');
        const gridKwh = kwhOf(plan.blocks, (id) => !String(id).startsWith('battery_out'));
        const cur = this._currency();
        const tomorrow = this._num('sensor.sem_forecast_tomorrow_kwh');
        return html`<div class="sec"><h3>${this._t('next_expected')}</h3><dl class="kv">
            ${plan.blocks ? html`<dt>${this._t('next_grid_planned')}</dt><dd class="num">${this._fmt(gridKwh, 1)} kWh${Number.isFinite(Number(m.cost)) ? ` · ${this._fmt(Number(m.cost), 2)} ${cur}` : ''}</dd>` : nothing}
            ${tomorrow !== null ? html`<dt>${this._t('next_sun_tomorrow')}</dt><dd class="num">${this._fmt(tomorrow, 1)} kWh</dd>` : nothing}
            ${m.computedAt ? html`<dt>${this._t('next_plan_made')}</dt><dd class="num">${this._stamp(m.computedAt)}</dd>` : nothing}
            ${m.fits !== undefined ? html`<dt>${this._t('next_plan_fits')}</dt><dd>${m.fits ? this._t('next_yes') : this._t('next_no')}</dd>` : nothing}
        </dl></div>`;
    }

    _stamp(iso) {
        const t = Date.parse(iso);
        if (!Number.isFinite(t)) return String(iso);
        const d = new Date(t);
        return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    }

    _change() {
        if (!this._chargers.length) return nothing;
        const obs = this._observer();
        return html`<div class="sec"><h3>${this._t('next_change_now')}</h3>
            ${this._chargers.map((cid) => {
                const sel = `select.sem_charger_${cid}_charge_mode`;
                const mode = this._str(sel);
                if (!mode) return nothing;
                const forced = mode === 'always_max';
                const asking = this._confirm === cid;
                return html`<div class="item"><i class="${forced ? 'warn' : ''}"></i>
                    <div>${this._chargerName(cid)}<span>${this._t('next_mode')}: ${this._t('charge_mode_' + mode) || mode}</span></div>
                    <div class="btns">
                        ${asking ? html`
                            <button class="btn primary" ?disabled=${obs} @click=${() => this._chargeNow(cid, sel, mode)}>${this._t('next_confirm')}</button>
                            <button class="btn" @click=${() => { this._confirm = null; }}>${this._t('next_cancel')}</button>`
                        : (forced && this._savedMode[cid]
                            ? html`<button class="btn" ?disabled=${obs} @click=${() => this._backToPlan(cid, sel)}>${this._t('next_back_to_plan')}</button>`
                            : html`<button class="btn primary" ?disabled=${obs || forced} @click=${() => { this._confirm = cid; }}>${this._t('next_charge_now')}</button>`)}
                    </div></div>`;
            })}
            <div class="hint">${obs ? this._t('next_observing_hint') : this._t('next_change_hint')}</div>
        </div>`;
    }

    async _chargeNow(cid, sel, mode) {
        this._savedMode = { ...this._savedMode, [cid]: mode };
        this._confirm = null;
        await this._hass.callService('select', 'select_option', { entity_id: sel, option: 'always_max' });
    }

    async _backToPlan(cid, sel) {
        const prev = this._savedMode[cid];
        if (!prev) return;
        await this._hass.callService('select', 'select_option', { entity_id: sel, option: prev });
        const { [cid]: _gone, ...rest } = this._savedMode;
        this._savedMode = rest;
        this.requestUpdate();
    }

    render() {
        if (!this._hass) return nothing;
        const m = this._model();
        this._m = m;
        const plan = this._attrs('sensor.sem_energy_plan');
        const lead = planLead(plan, { computedAt: m.computedAt ? this._stamp(m.computedAt) : '', cost: Number.isFinite(Number(m.cost)) ? `${this._fmt(Number(m.cost), 2)} ${this._currency()}` : '',
            fitsKey: m.fits === undefined ? '' : this._t(m.fits ? 'next_fits_yes' : 'next_fits_no'), sunTomorrowKwh: this._num('sensor.sem_forecast_tomorrow_kwh') });
        const flat = (this._str('sensor.sem_tariff_price_level') || 'flat') === 'flat';
        const main = this._tf(lead.main.key, lead.main.params);
        const sub = lead.sub ? this._tf(lead.sub.key, lead.sub.params) + (flat ? ' ' + this._t('next_one_rate_sub') : '') : '';
        return html`<ha-card><div class="wrap">
            ${this._renderHead()}
            ${this._renderLead(main, sub)}
            <div class="grid2">
                <div class="sec wide"><h3>${this._t('next_timeline')}</h3>
                    ${m.computedAt ? this._timeline(m) : html`<div class="hint">${this._t('next_plan_none')}</div>`}
                    <div class="hint" style="display:flex;flex-wrap:wrap;gap:10px 14px">
                        <span class="src"><i style="background:${C.solar}"></i>${this._t('next_lane_sun')}</span>
                        <span class="src"><i style="background:${C.grid}"></i>${this._t('next_lane_grid')}</span>
                        <span class="src"><i style="background:${C.battery_in}"></i>${this._t('next_battery_charging')}</span>
                        <span class="src"><i style="background:${C.battery_out}"></i>${this._t('next_battery_to_house')}</span>
                        <span class="src"><i style="background:${C.ev}"></i>${this._t('next_src_car')}</span>
                        <span class="src"><i style="background:${C.home}"></i>${this._t('next_lane_load')}</span>
                    </div>
                    <div class="tile">${this._pickedText
                        ? html`<b style="font-size:0.95rem">${this._pickedText.title}</b><span>${this._pickedText.text}</span>`
                        : html`<b style="font-size:0.95rem">${this._t('next_tap_block')}</b><span>${this._t('next_tap_block_sub')}</span>`}</div>
                    <div class="hint">${this._t('next_dashed_hint')}</div>
                </div>
                ${this._why(m)}
                ${this._expected(m)}
                ${this._change()}
            </div>
        </div></ha-card>`;
    }
}

semDefineCard('sem-next-plan-card', SEMNextPlanCard, {
    type: 'sem-next-plan-card',
    name: 'SEM Next · Plan',
    description: 'The next 24 hours as one timeline, why this plan, and one change you can make now',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-plan-card',
    preview: true,
});
