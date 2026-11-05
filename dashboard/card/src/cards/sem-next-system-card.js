/**
 * SEM Next · System (#1321)
 *
 * Health first: is every source fresh, is the plan current, what did SEM
 * refuse and why. Then the settings that answer a question, with the
 * real controls, and a link to the classic Configuration tab for the rest.
 *
 * Config:
 *   type: custom:sem-next-system-card
 */

import { SEMNextBase, html, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { semDefineCard } from '../base/sem-shared.js';
import { sourceRows, ageLabel, SOURCE_ROWS } from '../util/next-freshness.js';
import { plainReason, deviceName } from '../util/why-rows.js';

const IDS = ['sensor.sem_diag_version', 'sensor.sem_energy_plan', 'sensor.sem_target_peak_limit',
             'number.sem_night_start_offset_min', 'number.sem_night_earliest_start', 'number.sem_night_latest_end',
             'select.sem_battery_mode', 'number.sem_battery_buffer_soc', 'number.sem_battery_priority_soc',
             'number.sem_battery_assist_min_surplus', 'switch.sem_battery_may_assist_ev', 'switch.sem_energy_plan_actuation',
             ...SOURCE_ROWS.map((r) => r.entity)];

class SEMNextSystemCard extends SEMNextBase {
    static get styles() { return nextCss; }

    _watchIds() {
        const per = [];
        for (const cid of this._chargers) per.push(`time.sem_charger_${cid}_target_time`, `number.sem_charger_${cid}_daily_ev_target`);
        return [...super._watchIds(), ...IDS, ...per];
    }

    _sources() {
        const rows = sourceRows(this._hass.states, Date.now());
        if (!rows.length) return nothing;
        const cls = { ok: '', old: 'warn', off: 'bad', missing: 'off' };
        return html`<div class="sec"><h3>${this._t('next_sources')}</h3><div class="list">
            ${rows.map((r) => html`<div class="item"><i class="${cls[r.state] || ''}"></i>
                <div>${this._t(r.key)}<span>${this._name(r.entity)}${r.age === null ? '' : ' · ' + ageLabel(r.age)}</span></div>
                <b>${this._t('next_fresh_' + r.state)}</b></div>`)}
        </div></div>`;
    }

    _refused() {
        const attrs = this._attrs('switch.sem_observer_mode');
        const obs = this._observer();
        const withheld = Object.values(attrs.withheld_commands || {});
        const would = Object.values(attrs.would_decisions || {}).filter((d) => d && d.action && d.action !== 'idle');
        const rows = obs ? would : withheld;
        const t = (k) => this._t(k);
        return html`<div class="sec"><h3>${obs ? this._t('next_would_do') : this._t('next_refused')}</h3>
            ${rows.length ? html`<div class="list">${rows.slice(0, 8).map((r) => html`<div class="item"><i class="warn"></i>
                <div>${deviceName(r, t)}${r.action ? ` · ${r.action}` : ''}<span>${plainReason(r, t) || r.reason || ''}</span></div>
                <b class="num">${Number.isFinite(Number(r.power_w)) ? this._fmtKw(Number(r.power_w)) + ' kW' : ''}</b></div>`)}</div>`
            : html`<div class="hint">${obs ? this._t('next_would_none') : this._t('next_refused_none')}</div>`}
        </div>`;
    }

    _numRow(id, labelKey, unit, step = 1) {
        if (!this._hass.states[id]) return nothing;
        const a = this._attrs(id);
        return html`<dt>${this._t(labelKey)}</dt><dd><input type="number" .value=${String(this._num(id) ?? '')} min="${a.min ?? 0}" max="${a.max ?? 1000}" step="${a.step ?? step}" @change=${(e) => this._setNumber(id, Number(e.target.value))}> ${unit}</dd>`;
    }

    _settings() {
        const offset = this._hass.states['number.sem_night_start_offset_min'] ? 'number.sem_night_start_offset_min' : null;
        const earliest = !offset && this._hass.states['number.sem_night_earliest_start'] ? 'number.sem_night_earliest_start' : null;
        const modeId = this._hass.states['select.sem_battery_mode'] ? 'select.sem_battery_mode' : null;
        const assistId = this._hass.states['switch.sem_battery_may_assist_ev'] ? 'switch.sem_battery_may_assist_ev' : null;
        const actId = this._hass.states['switch.sem_energy_plan_actuation'] ? 'switch.sem_energy_plan_actuation' : null;
        const peak = this._num('sensor.sem_target_peak_limit');
        return html`
            <div class="sec"><h3>${this._t('next_q_car_grid')}</h3><dl class="kv">
                ${offset ? this._numRow(offset, 'next_night_offset', 'min', 5) : nothing}
                ${earliest ? this._numRow(earliest, 'next_night_earliest', 'h', 0.5) : nothing}
                ${this._numRow('number.sem_night_latest_end', 'next_night_end', 'h', 0.5)}
                ${this._chargers.map((cid) => {
                    const timeId = this._chargerEntity('time', cid, 'target_time');
                    const targetId = this._chargerEntity('number', cid, 'daily_ev_target');
                    return html`
                        ${timeId ? html`<dt>${this._chargerName(cid)} · ${this._t('next_charge_by')}</dt><dd><input type="time" .value=${(this._str(timeId) || '').slice(0, 5)} @change=${(e) => this._hass.callService('time', 'set_value', { entity_id: timeId, time: e.target.value + ':00' })}></dd>` : nothing}
                        ${targetId ? this._numRow(targetId, 'next_at_least', 'kWh', 0.5) : nothing}`;
                })}
            </dl><div class="hint">${this._t('next_q_car_grid_hint')}</div></div>
            <div class="sec"><h3>${this._t('next_q_battery')}</h3><dl class="kv">
                ${modeId ? html`<dt>${this._t('next_mode')}</dt><dd><select @change=${(e) => this._selectOption(modeId, e.target.value)}>
                    ${(this._attrs(modeId).options || []).map((o) => html`<option value="${o}" ?selected=${o === this._str(modeId)}>${this._t('battery_mode_' + o) || o}</option>`)}</select></dd>` : nothing}
                ${this._numRow('number.sem_battery_buffer_soc', 'next_buffer', '%')}
                ${this._numRow('number.sem_battery_priority_soc', 'next_priority_soc', '%')}
                ${this._numRow('number.sem_battery_assist_min_surplus', 'next_solar_gate', 'W', 50)}
                ${assistId ? html`<dt>${this._t('next_may_feed_car')}</dt><dd><label class="toggle"><input type="checkbox" .checked=${this._str(assistId) === 'on'} @change=${() => this._toggleSwitch(assistId)}></label></dd>` : nothing}
            </dl></div>
            <div class="sec"><h3>${this._t('next_q_limits')}</h3><dl class="kv">
                ${peak !== null ? html`<dt>${this._t('next_peak_limit')}</dt><dd class="num">${this._fmt(peak, 1)} kW</dd>` : nothing}
                ${actId ? html`<dt>${this._t('next_plan_acts')}</dt><dd><label class="toggle"><input type="checkbox" .checked=${this._str(actId) === 'on'} @change=${() => this._toggleSwitch(actId)}></label></dd>` : nothing}
                <dt>${this._t('next_observer')}</dt><dd>${this._observer() ? this._t('next_yes') : this._t('next_no')}</dd>
            </dl><a class="btn" href="/sem-dashboard/config">${this._t('next_all_settings')}</a></div>`;
    }

    render() {
        if (!this._hass) return nothing;
        const rows = sourceRows(this._hass.states, Date.now());
        const bad = rows.filter((r) => r.state !== 'ok');
        const plan = this._attrs('sensor.sem_energy_plan');
        const age = plan.computed_at ? Math.round((Date.now() - Date.parse(plan.computed_at)) / 60000) : null;
        const main = bad.length ? this._tf('next_sys_lead_bad', { n: bad.length }) : this._t('next_sys_lead_ok');
        const ver = this._str('sensor.sem_diag_version');
        const sub = [age !== null && Number.isFinite(age) ? this._tf('next_plan_age', { min: age }) : '',
                     this._observer() ? this._t('next_observer_on') : this._t('next_observer_off'),
                     ver ? `SEM ${ver}` : ''].filter(Boolean).join(' · ');
        return html`<ha-card><div class="wrap">
            ${this._renderHead()}
            ${this._renderLead(main, sub)}
            <div class="grid2">
                ${this._sources()}
                ${this._refused()}
                ${this._settings()}
            </div>
        </div></ha-card>`;
    }
}

semDefineCard('sem-next-system-card', SEMNextSystemCard, {
    type: 'sem-next-system-card',
    name: 'SEM Next · System',
    description: 'Health first: source freshness, what SEM refused, and the settings grouped by question',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-system-card',
    preview: true,
});
