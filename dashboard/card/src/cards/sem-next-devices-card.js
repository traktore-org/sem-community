/**
 * SEM Next · Devices (#1321)
 *
 * One card shape for every device: what it does now · what it may do ·
 * its targets · today · next · one change. Chargers from their per-charger
 * entities, the battery from the battery entities, loads from the load
 * manager's device map. Controls bind to the real entities.
 *
 * Config:
 *   type: custom:sem-next-devices-card
 */

import { SEMNextBase, html, nothing, nextCss, NEXT_COLORS as C } from '../base/sem-next-base.js';
import { semDefineCard } from '../base/sem-shared.js';

const IDS = ['sensor.sem_battery_soc', 'sensor.sem_battery_power', 'sensor.sem_battery_dynamic_floor_pct',
             'sensor.sem_battery_spendable_kwh', 'number.sem_battery_buffer_soc', 'number.sem_battery_priority_soc',
             'select.sem_battery_mode', 'switch.sem_battery_may_assist_ev', 'sensor.sem_daily_battery_charge_energy',
             'sensor.sem_daily_battery_discharge_energy', 'sensor.sem_controllable_devices_count', 'sensor.sem_energy_plan'];
const CHARGER_SUFFIXES = ['power', 'commanded_current', 'daily_energy', 'session_energy', 'session_solar_share',
                          'vehicle_soc', 'charge_mode', 'daily_ev_target', 'daily_ev_target_max', 'target_soc',
                          'target_soc_max', 'ev_target_type', 'target_time', 'pause_charging', 'minimum_current', 'maximum_current'];

class SEMNextDevicesCard extends SEMNextBase {
    static get styles() { return nextCss; }

    _watchIds() {
        const per = [];
        for (const cid of this._chargers) {
            for (const dom of ['sensor', 'number', 'select', 'time', 'switch']) {
                for (const s of CHARGER_SUFFIXES) {
                    const id = `${dom}.sem_charger_${cid}_${s}`;
                    if (this._hass?.states[id]) per.push(id);
                }
            }
        }
        const devices = this._attrs('sensor.sem_controllable_devices_count').devices || {};
        for (const info of Object.values(devices)) {
            if (info?.power_entity) per.push(info.power_entity);
            if (info?.switch_entity) per.push(info.switch_entity);
        }
        return [...super._watchIds(), ...IDS, ...per];
    }

    _nextBlock(prefix) {
        const plan = this._attrs('sensor.sem_energy_plan');
        const now = Date.now();
        const next = (Array.isArray(plan.blocks) ? plan.blocks : [])
            .filter((b) => String(b.id) === prefix && Date.parse(b.end) > now)
            .sort((a, b) => Date.parse(a.start) - Date.parse(b.start))[0];
        if (!next) return '';
        const s = new Date(Math.max(now, Date.parse(next.start))), e = new Date(Date.parse(next.end));
        const hh = (d) => String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
        return `${hh(s)} → ${hh(e)} · ${this._fmtKw(next.power_w)} kW`;
    }

    _charger(cid) {
        const ent = (dom, s) => this._chargerEntity(dom, cid, s);
        const powerW = this._powerW(`sensor.sem_charger_${cid}_power`);
        const amps = this._num(`sensor.sem_charger_${cid}_commanded_current`);
        const done = this._num(`sensor.sem_charger_${cid}_daily_energy`);
        const session = this._num(`sensor.sem_charger_${cid}_session_energy`);
        const share = this._num(`sensor.sem_charger_${cid}_session_solar_share`);
        const soc = this._num(`sensor.sem_charger_${cid}_vehicle_soc`);
        const modeId = ent('select', 'charge_mode');
        const mode = modeId ? this._str(modeId) : '';
        const typeId = ent('select', 'ev_target_type');
        const type = typeId ? this._str(typeId) : 'kwh';
        const minId = type === 'soc' ? ent('number', 'target_soc') : ent('number', 'daily_ev_target');
        const maxId = type === 'soc' ? ent('number', 'target_soc_max') : ent('number', 'daily_ev_target_max');
        const timeId = ent('time', 'target_time');
        const pauseId = ent('switch', 'pause_charging');
        const unit = type === 'soc' ? '%' : 'kWh';
        const charging = powerW !== null && powerW > 50;
        const status = charging
            ? this._tf('next_dev_charging', { kw: this._fmtKw(powerW), amps: amps === null ? '—' : Math.round(amps) })
            : (pauseId && this._str(pauseId) === 'on' ? this._t('next_dev_paused') : this._t('next_dev_idle'));
        const obs = this._observer();
        return html`<div class="sec">
            <h3><span class="src"><i style="background:${C.ev}"></i>${this._chargerName(cid)}</span></h3>
            <div class="lead" style="font-size:1rem">${status}
                <small>${done !== null ? this._tf('next_dev_today_kwh', { kwh: this._fmt(done, 1) }) : ''}${session !== null ? ` · ${this._t('next_session')} ${this._fmt(session, 1)} kWh` : ''}${share !== null ? ` · ${this._fmt(share, 0)} % ${this._t('next_from_sun')}` : ''}${soc !== null ? ` · ${this._t('next_car_soc')} ${this._fmt(soc, 0)} %` : ''}</small>
            </div>
            <dl class="kv">
                ${modeId ? html`<dt>${this._t('next_mode')}</dt><dd>
                    <select ?disabled=${obs} @change=${(e) => this._selectOption(modeId, e.target.value)}>
                        ${(this._attrs(modeId).options || []).map((o) => html`<option value="${o}" ?selected=${o === mode}>${this._t('charge_mode_' + o) || o}</option>`)}
                    </select></dd>` : nothing}
                ${minId ? html`<dt>${this._t('next_at_least')}</dt><dd><input type="number" ?disabled=${obs} .value=${String(this._num(minId) ?? '')} min="${this._attrs(minId).min ?? 0}" max="${this._attrs(minId).max ?? 200}" step="${this._attrs(minId).step ?? 0.5}" @change=${(e) => this._setNumber(minId, Number(e.target.value))}> ${unit}</dd>` : nothing}
                ${maxId ? html`<dt>${this._t('next_up_to')}</dt><dd><input type="number" ?disabled=${obs} .value=${String(this._num(maxId) ?? '')} min="${this._attrs(maxId).min ?? 0}" max="${this._attrs(maxId).max ?? 200}" step="${this._attrs(maxId).step ?? 0.5}" @change=${(e) => this._setNumber(maxId, Number(e.target.value))}> ${unit}</dd>` : nothing}
                ${timeId ? html`<dt>${this._t('next_charge_by')}</dt><dd><input type="time" ?disabled=${obs} .value=${(this._str(timeId) || '').slice(0, 5)} @change=${(e) => this._setTime(timeId, e.target.value)}></dd>` : nothing}
                <dt>${this._t('next_next')}</dt><dd>${this._nextBlock(`ev:${cid}`) || this._t('next_nothing_planned')}</dd>
            </dl>
            ${pauseId ? html`<label class="toggle"><input type="checkbox" ?disabled=${obs} .checked=${this._str(pauseId) === 'on'} @change=${() => this._toggleSwitch(pauseId)}> ${this._t('next_pause')}</label>` : nothing}
        </div>`;
    }

    async _setTime(id, value) {
        if (!value) return;
        await this._hass.callService('time', 'set_value', { entity_id: id, time: value.length === 5 ? value + ':00' : value });
    }

    _battery() {
        const soc = this._num('sensor.sem_battery_soc');
        if (soc === null) return nothing;
        const p = this._powerW('sensor.sem_battery_power');
        const floor = this._num('sensor.sem_battery_dynamic_floor_pct');
        const spend = this._num('sensor.sem_battery_spendable_kwh');
        const modeId = this._hass.states['select.sem_battery_mode'] ? 'select.sem_battery_mode' : null;
        const bufferId = this._hass.states['number.sem_battery_buffer_soc'] ? 'number.sem_battery_buffer_soc' : null;
        const assistId = this._hass.states['switch.sem_battery_may_assist_ev'] ? 'switch.sem_battery_may_assist_ev' : null;
        const cin = this._num('sensor.sem_daily_battery_charge_energy'), cout = this._num('sensor.sem_daily_battery_discharge_energy');
        const obs = this._observer();
        const status = p !== null && p < -50 ? this._tf('next_dev_batt_house', { kw: this._fmtKw(-p), soc: Math.round(soc) })
            : (p !== null && p > 50 ? this._tf('next_dev_batt_charging', { kw: this._fmtKw(p), soc: Math.round(soc) }) : this._tf('next_dev_batt_rest', { soc: Math.round(soc) }));
        const sub = floor !== null ? this._tf('next_why_batt_floor_short', { floor: Math.round(floor) }) : '';
        return html`<div class="sec">
            <h3><span class="src"><i style="background:${C.battery_out}"></i>${this._t('next_src_battery')}</span></h3>
            <div class="lead" style="font-size:1rem">${status}<small>${sub}</small></div>
            <dl class="kv">
                ${modeId ? html`<dt>${this._t('next_mode')}</dt><dd><select ?disabled=${obs} @change=${(e) => this._selectOption(modeId, e.target.value)}>
                    ${(this._attrs(modeId).options || []).map((o) => html`<option value="${o}" ?selected=${o === this._str(modeId)}>${this._t('battery_mode_' + o) || o}</option>`)}</select></dd>` : nothing}
                ${bufferId ? html`<dt>${this._t('next_buffer')}</dt><dd><input type="number" ?disabled=${obs} .value=${String(this._num(bufferId) ?? '')} min="0" max="100" step="1" @change=${(e) => this._setNumber(bufferId, Number(e.target.value))}> %</dd>` : nothing}
                ${cin !== null || cout !== null ? html`<dt>${this._t('next_today')}</dt><dd class="num">${this._t('next_in')} ${this._fmt(cin, 1)} · ${this._t('next_out')} ${this._fmt(cout, 1)} kWh</dd>` : nothing}
                ${spend !== null ? html`<dt>${this._t('next_spendable')}</dt><dd class="num">${this._fmt(spend, 1)} kWh</dd>` : nothing}
                <dt>${this._t('next_next')}</dt><dd>${this._nextBlock('battery') || this._t('next_follows_sun')}</dd>
            </dl>
            ${assistId ? html`<label class="toggle"><input type="checkbox" ?disabled=${obs} .checked=${this._str(assistId) === 'on'} @change=${() => this._toggleSwitch(assistId)}> ${this._t('next_may_feed_car')}</label>` : nothing}
        </div>`;
    }

    _loads() {
        const devices = this._attrs('sensor.sem_controllable_devices_count').devices || {};
        const entries = Object.entries(devices);
        if (!entries.length) {
            return html`<div class="sec"><h3><span class="src"><i style="background:${C.home}"></i>${this._t('next_loads')}</span></h3>
                <div class="hint">${this._t('next_no_loads')}</div></div>`;
        }
        const obs = this._observer();
        return entries.map(([id, info]) => {
            const p = info.power_entity ? this._powerW(info.power_entity) : null;
            const sw = info.switch_entity && this._hass.states[info.switch_entity] ? info.switch_entity : null;
            const on = sw ? this._str(sw) === 'on' : !!info.is_on;
            const status = info.is_shed ? this._t('next_dev_shed') : (on ? this._tf('next_dev_on', { kw: this._fmtKw(p ?? info.current_power ?? 0) }) : this._t('next_dev_off'));
            return html`<div class="sec">
                <h3><span class="src"><i style="background:${C.home}"></i>${info.name || id}</span></h3>
                <div class="lead" style="font-size:1rem">${status}<small>${info.shed_reason || ''}</small></div>
                <dl class="kv">
                    <dt>${this._t('next_mode')}</dt><dd>${info.control_mode ? this._t('load_mode_' + info.control_mode) || info.control_mode : (info.is_controllable ? this._t('next_managed') : this._t('next_watch_only'))}</dd>
                    <dt>${this._t('next_priority')}</dt><dd class="num">${info.priority ?? '—'}</dd>
                    ${info.power_rating ? html`<dt>${this._t('next_rated')}</dt><dd class="num">${this._fmtKw(info.power_rating)} kW</dd>` : nothing}
                    <dt>${this._t('next_next')}</dt><dd>${this._nextBlock(`load:${id}`) || this._t('next_when_surplus')}</dd>
                </dl>
                ${sw ? html`<label class="toggle"><input type="checkbox" ?disabled=${obs} .checked=${on} @change=${() => this._toggleSwitch(sw)}> ${this._t('next_switch_on')}</label>` : nothing}
            </div>`;
        });
    }

    render() {
        if (!this._hass) return nothing;
        const nCh = this._chargers.length;
        const charging = this._chargers.filter((cid) => (this._powerW(`sensor.sem_charger_${cid}_power`) || 0) > 50).length;
        const soc = this._num('sensor.sem_battery_soc');
        const main = this._tf('next_dev_lead', { n: nCh + (soc === null ? 0 : 1), charging });
        return html`<ha-card><div class="wrap">
            ${this._renderHead()}
            ${this._renderLead(main, this._t('next_dev_lead_sub'))}
            <div class="grid2">
                ${this._chargers.map((cid) => this._charger(cid))}
                ${this._battery()}
                ${this._loads()}
            </div>
        </div></ha-card>`;
    }
}

semDefineCard('sem-next-devices-card', SEMNextDevicesCard, {
    type: 'sem-next-devices-card',
    name: 'SEM Next · Devices',
    description: 'Every charger, battery and load in one card shape: status, mode, targets, today, next, one change',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-devices-card',
    preview: true,
});
