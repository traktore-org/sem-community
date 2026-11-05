/**
 * SEM Next · Now (#1321)
 *
 * What SEM does right now and why, in one line and then the detail: the
 * power flow, the reasons per device, today's totals, money, and what
 * comes next. Every number comes from an SEM entity; a missing entity
 * leaves its row out.
 *
 * Config:
 *   type: custom:sem-next-now-card
 */

import { SEMNextBase, html, svg, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { semDefineCard } from '../base/sem-shared.js';
import { nowLead } from '../util/next-lead.js';

const IDS = [
    'sensor.sem_solar_power', 'sensor.sem_grid_power', 'sensor.sem_battery_power', 'sensor.sem_battery_soc',
    'sensor.sem_home_consumption_power', 'sensor.sem_ev_power', 'sensor.sem_charging_strategy',
    'sensor.sem_battery_dynamic_floor_pct', 'number.sem_battery_buffer_soc', 'sensor.sem_consecutive_peak_15min',
    'sensor.sem_target_peak_limit', 'sensor.sem_daily_solar_energy', 'sensor.sem_forecast_today_kwh',
    'sensor.sem_daily_grid_import_energy', 'sensor.sem_daily_grid_export_energy', 'sensor.sem_daily_home_energy',
    'sensor.sem_daily_ev_energy', 'sensor.sem_self_consumption_rate', 'sensor.sem_autarky_rate',
    'sensor.sem_daily_co2_avoided', 'sensor.sem_daily_costs', 'sensor.sem_daily_savings', 'sensor.sem_monthly_costs',
    'sensor.sem_monthly_savings', 'sensor.sem_tariff_current_import_rate', 'sensor.sem_tariff_current_export_rate',
    'sensor.sem_tariff_price_level', 'sensor.sem_energy_plan', 'sensor.sem_forecast_tomorrow_kwh',
];

class SEMNextNowCard extends SEMNextBase {
    static get styles() { return nextCss; }

    _watchIds() {
        const per = [];
        for (const cid of this._chargers) {
            per.push(`sensor.sem_charger_${cid}_power`, `sensor.sem_charger_${cid}_commanded_current`,
                     `sensor.sem_charger_${cid}_daily_energy`, `number.sem_charger_${cid}_daily_ev_target`,
                     `time.sem_charger_${cid}_target_time`, `sensor.sem_charger_${cid}_vehicle_soc`,
                     `number.sem_charger_${cid}_target_soc`);
        }
        return [...super._watchIds(), ...IDS, ...per];
    }

    /** The first charger with a car, as the lead's car fact. */
    _carFact() {
        for (const cid of this._chargers) {
            const powerW = this._powerW(`sensor.sem_charger_${cid}_power`);
            const amps = this._num(`sensor.sem_charger_${cid}_commanded_current`);
            const remaining = this._remainingKwh(cid);
            const present = powerW !== null && (powerW > 50 || (remaining !== null && remaining > 0.1));
            if (!present) continue;
            return { present: true, charging: powerW > 50, powerW, amps, remainingKwh: remaining,
                     targetTime: (this._str(`time.sem_charger_${cid}_target_time`) || '').slice(0, 5), cid };
        }
        return null;
    }

    _remainingKwh(cid) {
        const type = this._str(`select.sem_charger_${cid}_ev_target_type`) || 'kwh';
        if (type === 'soc') {
            const soc = this._num(`sensor.sem_charger_${cid}_vehicle_soc`);
            const target = this._num(`number.sem_charger_${cid}_target_soc`);
            const cap = this._num(`number.sem_charger_${cid}_ev_battery_capacity_kwh`);
            if (soc === null || target === null || cap === null) return null;
            return Math.max(0, (target - soc) / 100 * cap);
        }
        const target = this._num(`number.sem_charger_${cid}_daily_ev_target`);
        const done = this._num(`sensor.sem_charger_${cid}_daily_energy`);
        if (target === null || done === null) return null;
        return Math.max(0, target - done);
    }

    _lead() {
        const soc = this._num('sensor.sem_battery_soc');
        const f = {
            night: this._night(), observer: this._observer(),
            solarW: this._powerW('sensor.sem_solar_power'), gridW: this._powerW('sensor.sem_grid_power'),
            batteryW: this._powerW('sensor.sem_battery_power'),
            car: this._carFact(),
            battery: soc === null ? null : { soc, floorPct: this._num('sensor.sem_battery_dynamic_floor_pct'),
                                             bufferPct: this._num('number.sem_battery_buffer_soc') },
            sunAt: this._str('sensor.sem_night_end_time'), nightStart: this._str('sensor.sem_night_start_time'),
        };
        const r = nowLead(f);
        const main = (r.prefix ? this._t(r.prefix) + ' ' : '') + this._tf(r.main.key, r.main.params);
        const sub = r.sub ? this._tf(r.sub.key, r.sub.params) : '';
        return { main, sub };
    }

    _flow() {
        const solarR = this._powerW('sensor.sem_solar_power');
        const gridR = this._powerW('sensor.sem_grid_power');
        const battR = this._powerW('sensor.sem_battery_power');
        const homeR = this._powerW('sensor.sem_home_consumption_power');
        const evR = this._powerW('sensor.sem_ev_power');
        const solar = solarR ?? 0, grid = gridR ?? 0, batt = battR ?? 0, home = homeR ?? 0, ev = evR ?? 0;
        const soc = this._num('sensor.sem_battery_soc');
        const node = (x, y, label, value, color, dim) => svg`
            <circle cx="${x}" cy="${y}" r="26" fill="var(--card-background-color)" stroke="${color}" stroke-width="2.5" opacity="${dim ? 0.45 : 1}"></circle>
            <text x="${x}" y="${y - 4}" text-anchor="middle" font-size="11" font-weight="600" fill="var(--primary-text-color)">${label}</text>
            <text x="${x}" y="${y + 11}" text-anchor="middle" font-size="11" fill="var(--secondary-text-color)">${value}</text>`;
        const arrow = (d, color, on) => on ? svg`<path d="${d}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" marker-end="url(#nxarr)"></path>` : nothing;
        const kw = (w) => w === null ? '—' : `${(Math.abs(w) / 1000).toFixed(1)} kW`;
        return html`
            <svg viewBox="0 0 360 170" width="100%" role="img" aria-label="${this._t('next_power_now')}">
                <defs><marker id="nxarr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="context-stroke"></path></marker></defs>
                ${node(60, 40, this._t('next_src_solar'), kw(solarR), C.solar, solar < 50)}
                ${node(60, 130, this._t('next_src_grid'), kw(gridR), C.grid, Math.abs(grid) < 50)}
                ${node(180, 85, this._t('next_src_house'), kw(homeR), C.home, homeR === null)}
                ${node(300, 40, this._t('next_src_battery'), soc === null ? kw(battR) : `${Math.round(soc)} %`, C.battery_out, Math.abs(batt) < 50)}
                ${node(300, 130, this._t('next_src_car'), kw(evR), C.ev, ev < 50)}
                ${arrow('M88 48 C120 60 130 70 148 78', C.solar, solar > 50)}
                ${arrow('M88 122 C120 110 130 100 148 93', C.grid, grid < -50)}
                ${arrow('M148 93 C130 100 120 110 88 122', C.export, grid > 50)}
                ${arrow('M212 78 C240 70 250 60 272 48', C.battery_in, batt > 50)}
                ${arrow('M272 48 C250 60 240 70 212 78', C.battery_out, batt < -50)}
                ${arrow('M212 95 C240 105 250 118 272 126', C.ev, ev > 50)}
            </svg>`;
    }

    _why() {
        const rows = [];
        const strat = this._hass?.states['sensor.sem_charging_strategy'];
        if (strat && strat.state && strat.state !== 'unavailable') {
            const reason = String(strat.attributes?.reason || strat.state);
            const [head, ...rest] = reason.split(/\s[—–-]\s|\[/);
            rows.push({ dot: 'EV', color: C.ev, title: head.trim(), text: rest.join(' ').replace(/\]$/, '').trim() });
        }
        const soc = this._num('sensor.sem_battery_soc');
        const floor = this._num('sensor.sem_battery_dynamic_floor_pct');
        const batt = this._powerW('sensor.sem_battery_power');
        if (soc !== null) {
            const title = batt !== null && batt < -50 ? this._t('next_why_batt_house')
                : (batt !== null && batt > 50 ? this._t('next_why_batt_charging') : this._t('next_why_batt_rest'));
            const text = (floor !== null && soc < floor)
                ? this._tf('next_why_batt_floor', { soc: Math.round(soc), floor: Math.round(floor) })
                : this._tf('next_sub_battery_at', { soc: Math.round(soc) });
            rows.push({ dot: 'B', color: C.battery_out, title, text });
        }
        const peak = this._num('sensor.sem_consecutive_peak_15min');
        const limit = this._num('sensor.sem_target_peak_limit');
        const grid = this._powerW('sensor.sem_grid_power');
        if (grid !== null && peak !== null) {
            rows.push({ dot: 'G', color: C.grid,
                title: grid < -50 ? this._tf('next_why_import', { kw: this._fmtKw(-grid) }) : (grid > 50 ? this._tf('next_why_export', { kw: this._fmtKw(grid) }) : this._t('next_why_grid_quiet')),
                text: limit !== null ? this._tf('next_why_peak', { kw: this._fmt(peak, 1), limit: this._fmt(limit, 1) }) : this._tf('next_why_peak_nolimit', { kw: this._fmt(peak, 1) }) });
        }
        if (!rows.length) return nothing;
        return html`<div class="sec"><h3>${this._t('next_why')}</h3><div class="why">
            ${rows.map((r) => html`<div class="row"><div class="dot" style="background:${r.color}">${r.dot}</div><div><b>${r.title}</b><span>${r.text}</span></div></div>`)}
        </div></div>`;
    }

    _today() {
        const solar = this._num('sensor.sem_daily_solar_energy');
        const fc = this._num('sensor.sem_forecast_today_kwh');
        const imp = this._num('sensor.sem_daily_grid_import_energy');
        const exp = this._num('sensor.sem_daily_grid_export_energy');
        const home = this._num('sensor.sem_daily_home_energy');
        const ev = this._num('sensor.sem_daily_ev_energy');
        const max = Math.max(1, ...[solar, imp, home, ev].filter((v) => v !== null));
        const tile = (v, label, color, extra) => v === null ? nothing : html`
            <div class="tile"><b class="num">${this._fmt(v, 1)} <small>kWh</small></b>
                <span class="src"><i style="background:${color}"></i>${label}${extra ? ' · ' + extra : ''}</span>
                <div class="bar"><i style="width:${Math.min(100, v / max * 100)}%;background:${color}"></i></div></div>`;
        const pct = (fc && solar !== null && fc > 0) ? this._tf('next_pct_forecast', { pct: Math.round(solar / fc * 100) }) : '';
        const self = this._num('sensor.sem_self_consumption_rate');
        const aut = this._num('sensor.sem_autarky_rate');
        const co2 = this._num('sensor.sem_daily_co2_avoided');
        return html`<div class="sec"><h3>${this._t('next_today')}</h3>
            <div class="tiles">
                ${tile(solar, this._t('next_src_solar'), C.solar, pct)}
                ${tile(imp, this._t('next_grid_in'), C.grid, exp !== null ? `${this._fmt(exp, 1)} ${this._t('next_out')}` : '')}
                ${tile(home, this._t('next_src_house'), C.home, '')}
                ${tile(ev, this._t('next_src_car'), C.ev, '')}
            </div>
            <dl class="kv">
                ${self !== null ? html`<dt>${this._t('next_self_use')}</dt><dd class="num">${this._fmt(self, 0)} %</dd>` : nothing}
                ${aut !== null ? html`<dt>${this._t('next_own_supply')}</dt><dd class="num">${this._fmt(aut, 0)} %</dd>` : nothing}
                ${co2 !== null ? html`<dt>${this._t('next_co2_avoided')}</dt><dd class="num">${this._fmt(co2, 1)} ${this._kgUnit('daily_co2_avoided')}</dd>` : nothing}
            </dl></div>`;
    }

    _money() {
        const cur = this._currency();
        const cost = this._num('sensor.sem_daily_costs'), saved = this._num('sensor.sem_daily_savings');
        const mcost = this._num('sensor.sem_monthly_costs'), msaved = this._num('sensor.sem_monthly_savings');
        const imp = this._num('sensor.sem_tariff_current_import_rate'), exp = this._num('sensor.sem_tariff_current_export_rate');
        const level = this._str('sensor.sem_tariff_price_level');
        if (cost === null && imp === null) return nothing;
        return html`<div class="sec"><h3>${this._t('next_money')}</h3><dl class="kv">
            ${cost !== null ? html`<dt>${this._t('next_today')}</dt><dd class="num">${this._fmt(cost, 2)} ${cur}</dd>` : nothing}
            ${saved !== null ? html`<dt>${this._t('next_saved')}</dt><dd class="num" style="color:${C.good}">${this._fmt(saved, 2)} ${cur}</dd>` : nothing}
            ${imp !== null ? html`<dt>${this._t('next_price')}</dt><dd class="num">${level === 'flat' || !level ? this._t('next_one_rate') + ' · ' : ''}${this._fmt(imp, 2)}${exp !== null ? ' / ' + this._fmt(exp, 3) : ''}</dd>` : nothing}
            ${mcost !== null ? html`<dt>${this._t('next_this_month')}</dt><dd class="num">${this._fmt(mcost, 2)} ${cur}${msaved !== null ? ' · ' + this._t('next_saved').toLowerCase() + ' ' + this._fmt(msaved, 2) : ''}</dd>` : nothing}
        </dl></div>`;
    }

    _next() {
        const items = [];
        const plan = this._attrs('sensor.sem_energy_plan');
        const now = Date.now();
        const blocks = (Array.isArray(plan.blocks) ? plan.blocks : [])
            .filter((b) => Date.parse(b.start) > now).sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
        if (blocks.length) {
            const b = blocks[0];
            const d = new Date(Date.parse(b.start));
            const who = String(b.id).startsWith('ev:') ? this._t('next_src_car') : (String(b.id).startsWith('battery') ? this._t('next_src_battery') : String(b.id).replace(/^load:/, ''));
            items.push({ cls: '', title: this._tf('next_next_block', { who }), sub: `${this._fmtKw(b.power_w)} kW`, at: this._hhmm(d) });
        }
        const tomorrow = this._num('sensor.sem_forecast_tomorrow_kwh');
        const sunAt = this._str('sensor.sem_night_end_time');
        if (tomorrow !== null) items.push({ cls: 'off', title: this._t('next_sun_tomorrow'), sub: this._tf('next_kwh_expected', { kwh: this._fmt(tomorrow, 1) }), at: sunAt });
        const ns = this._str('sensor.sem_night_start_time');
        if (ns) items.push({ cls: 'off', title: this._t('next_night_starts'), sub: this._t('next_night_starts_sub'), at: ns });
        if (!items.length) return nothing;
        return html`<div class="sec"><h3>${this._t('next_next')}</h3><div class="list">
            ${items.map((i) => html`<div class="item"><i class="${i.cls}"></i><div>${i.title}<span>${i.sub}</span></div><b class="num">${i.at}</b></div>`)}
        </div></div>`;
    }

    _hhmm(d) { return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }

    render() {
        if (!this._hass) return nothing;
        const lead = this._lead();
        return html`<ha-card><div class="wrap">
            ${this._renderHead()}
            ${this._renderLead(lead.main, lead.sub)}
            <div class="grid2">
                <div class="sec wide"><h3>${this._t('next_power_now')}</h3>${this._flow()}</div>
                ${this._why()}
                ${this._today()}
                ${this._money()}
                ${this._next()}
            </div>
        </div></ha-card>`;
    }
}

semDefineCard('sem-next-now-card', SEMNextNowCard, {
    type: 'sem-next-now-card',
    name: 'SEM Next · Now',
    description: 'What SEM does right now and why: power flow, reasons, today, money, next',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-now-card',
    preview: true,
});
