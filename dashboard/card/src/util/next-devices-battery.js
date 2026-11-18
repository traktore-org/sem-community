/**
 * (#1321) The Devices screen's battery body: mode, stats, the zone bar
 * with its sentence, and the rows Tonight · Charge pacing · Sell window ·
 * per battery · Evidence · Health. A function of the card; every row
 * exists only when its entity does.
 */

import { html, nothing } from '../base/sem-next-base.js';
import { providerName } from './forecast-evidence.js';
import { zonesModel } from './next-devices.js';
import { BATTERY_LEVELS, BATTERY_QUESTIONS, batteryLevels, batterySaysFromStates, batteryFloorPct, kwhAboveFloor, batteryUnits } from './battery-questions.js';

/** (#1354) The entity of a shared battery level by its id. */
const LEVEL = Object.fromEntries(BATTERY_LEVELS.map((l) => [l.id, l.entity]));

const AUTO_MODES = ['auto', 'self_consumption', 'allow_arbitrage'];
const SPEND = 'sensor.sem_battery_spendable_kwh';

/** The pack's capacity in kWh from the first source that answers. */
function capacityKwh(card) {
    for (const id of ['sensor.sem_battery_measured_capacity_kwh', 'sensor.sem_diag_battery_capacity', 'number.sem_battery_capacity']) {
        const v = card._num(id);
        if (v !== null && v > 0) return v;
    }
    const a = Number(card._attrs(SPEND).measured_capacity_kwh);
    return Number.isFinite(a) && a > 0 ? a : null;
}

export function batteryBody(card, row) {
    const t = (k) => card._t(k);
    const tf = (k, p) => card._tf(k, p);
    const dis = false;   // (#1321) the battery's settings are SEM's own: editable while watching
    const num = card._num.bind(card);

    // ── mode ──
    const modeId = card._has('select.sem_battery_mode') ? 'select.sem_battery_mode' : null;
    const mode = modeId ? card._str(modeId) : '';
    const options = modeId ? (card._attrs(modeId).options || []) : [];
    // (#1321) SEM's battery mode is ONE setting (this select); Auto and Self-consumption are two of its
    // values, so it is one control. The inverter's own mode is not on this card.
    const order = ['off', ...AUTO_MODES, 'force_charge', 'force_discharge'];
    const labelOf = { off: t('charge_mode_off'), force_charge: t('next_charge'), force_discharge: t('next_discharge') };
    const segItems = order.filter((o) => options.includes(o))
        .map((o) => ({ key: o, label: labelOf[o] || t('battery_mode_' + o) || o }));
    const segKey = mode;
    const pick = (key) => { if (modeId) card._selectOption(modeId, key); };
    const hint = mode ? t('battery_mode_hint_' + mode) : '';

    // ── stats ──
    const soc = num('sensor.sem_battery_soc');
    const powerW = card._powerW('sensor.sem_battery_power');
    const status = (card._str('sensor.sem_battery_status') || '').toLowerCase();
    const cap = capacityKwh(card);
    const stored = soc !== null && cap ? (soc / 100) * cap : null;
    const cin = num('sensor.sem_daily_battery_charge_energy'), cout = num('sensor.sem_daily_battery_discharge_energy');
    const statusWord = status === 'selling' ? t('selling_to_grid')
        : (powerW !== null && powerW > 50) || status === 'charging' ? t('charging')
        : (powerW !== null && powerW < -50) || status === 'discharging' ? t('discharging')
        : (powerW !== null || status) ? t('idle') : '';
    const stats = [
        [t('next_charge'), soc === null ? '—' : Math.round(soc) + ' %', stored === null ? (cap ? card._kwh(cap) : '') : tf('next_stored_of', { stored: card._fmt(stored, 1), cap: card._fmt(cap, 1) })],
        [t('next_power'), powerW === null ? '—' : (powerW < 0 ? '−' : '') + card._kw(Math.abs(powerW)), statusWord],
        [t('next_today'), cin === null && cout === null ? '—' : card._fmt(cin, 1) + ' / ' + card._fmt(cout, 1) + ' kWh', t('next_in_out')],
    ];

    // ── zones ──
    // (#1354) the levels come from the shared battery model, as on the classic Battery tab
    const ids = { priority: LEVEL.priority, buffer: LEVEL.buffer, auto: LEVEL.autostart, tonight: 'sensor.sem_battery_dynamic_floor_pct' };
    const lv = batteryLevels(card._hass?.states);
    // (#1321) the reserve the plan uses (its own floor when published, else the setting)
    const floorPct = batteryFloorPct(card._hass?.states, card._attrs('sensor.sem_energy_plan'));
    const z = zonesModel({ soc, priority: lv.priority, buffer: lv.buffer, autoStart: lv.autostart, floor: num(ids.tonight), reserve: floorPct });
    const above = kwhAboveFloor(soc, floorPct, cap);
    // (#1321) the bar is the picture only: the five zone names are the rows below, so the
    // bar carries one marker, "now" at the battery's level
    const zones = z.marks.length || z.cur !== null ? html`<div class="zones" style="--z1:${z.z1}%;--z2:${z.z2}%">
        ${z.cur === null ? nothing : html`<span class="z ${z.cur >= 85 ? 'r' : z.cur <= 15 ? 'l' : ''}" style="left:${z.cur}%">${t('next_now_marker')} ${Math.round(soc)} %</span>
            <span class="cur" style="left:${z.cur}%"></span>`}</div>` : nothing;
    const parts = [];
    // what it does now and next, the same words as the classic Battery tab
    const says = batterySaysFromStates(card._hass?.states);
    parts.push(html`${tf(says.now.key, says.now.params)}${says.next ? html` ${tf(says.next.key, says.next.params)}` : nothing}`);
    if (above !== null) parts.push(tf('next_above_reserve', { kwh: card._fmt(above, 1), reserve: Math.round(floorPct) }));
    const sentence = parts.length ? html`<p class="sent">${parts.map((p, i) => html`${i ? ' ' : ''}${p}`)}</p>` : nothing;

    // ── the zone settings as rows (#1321): the bar above stays the picture ──
    const Q = BATTERY_QUESTIONS;
    const assistId = card._has(Q.may_assist.entity) ? Q.may_assist.entity : null;
    const maxId = card._has(Q.assist_max.entity) ? Q.assist_max.entity : null;
    const gateId = card._has(Q.solar_gate.entity) ? Q.solar_gate.entity : null;
    const assistOn = assistId ? card._str(assistId) === 'on' : true;
    const numRow = (q, id, text) => {
        const a = card._attrs(id), label = card._lbl(q.key);
        return card._setRow({ label, help: t(q.sub), value: text, disabled: dis,
            onTap: () => card._editDialog({ title: label, kind: 'number', value: num(id), min: a.min, max: a.max, step: a.step,
                unit: a.unit_of_measurement || '', onCommit: (x) => card._setNumber(id, x) }) });
    };
    const levelRows = [];
    if (card._has(ids.priority)) levelRows.push(numRow({ key: 'bq_priority', sub: 'bq_priority_sub' }, ids.priority, Math.round(num(ids.priority)) + ' %'));
    if (assistId) {
        levelRows.push(card._setRow({ label: card._lbl(Q.may_assist.key), help: t(Q.may_assist.sub), disabled: dis,
            toggle: { on: assistOn, onChange: () => card._toggleSwitch(assistId) } }));
    }
    // (#1354) the help starts at the buffer and is full from auto-start
    // (coordinator/decide.py `soc_zone`, flow_calculator.py `battery_assist_potential_w`)
    if (assistOn) {
        if (card._has(ids.buffer)) levelRows.push(numRow({ key: 'bq_buffer', sub: 'bq_buffer_sub' }, ids.buffer, Math.round(num(ids.buffer)) + ' %'));
        if (card._has(ids.auto)) levelRows.push(numRow({ key: 'bq_autostart', sub: 'bq_autostart_sub' }, ids.auto, Math.round(num(ids.auto)) + ' %'));
        if (maxId) levelRows.push(numRow(Q.assist_max, maxId, card._kw(num(maxId))));
        if (gateId) levelRows.push(numRow(Q.solar_gate, gateId, card._fmt(num(gateId), 0) + ' W'));
    }

    // ── rows ──
    const rows = [];
    const moreRows = [];
    const sa = card._attrs(SPEND);
    if (card._has(SPEND) && sa.phase) {
        const need = Number(sa.overnight_need_kwh), refill = Number(sa.expected_refill_kwh);
        const nights = Number(sa.nights_sealed), spend = num(SPEND);
        const subs = [];
        if (Number.isFinite(refill)) subs.push(tf('next_refill', { kwh: card._fmt(refill, 1) }));
        if (spend !== null) subs.push(tf('next_spendable_kwh', { kwh: card._fmt(spend, 1) }));
        if (Number.isFinite(nights)) subs.push(tf('next_nights_learned', { n: nights }));
        const rebuild = card._val(t('rebuild_nights'), () => card._askFirst(t('rebuild_nights'), () => card._svc('backfill_battery_nights', { days: 365 })), { disabled: dis });
        rows.push(card._row('mdi:weather-night', t('tonight'),
            (t('planning_phase_' + sa.phase) || sa.phase) + (Number.isFinite(need) ? ' · ' + tf('next_needs_kwh', { kwh: card._fmt(need, 1) }) : ''),
            html`${subs.join(' · ')}${sa.phase === 'learning' ? html`${subs.length ? ' · ' : ''}${rebuild}` : ''}`));
    }
    const paceId = 'sensor.sem_battery_charge_pacing';
    const paceSw = card._has(Q.pacing.entity) ? Q.pacing.entity : null;
    if (card._has(paceId) || paceSw) {
        const a = card._attrs(paceId);
        const code = a.reason_code || 'none';
        const blocked = { no_limit_entity: 'pacing_no_limit', limit_unreadable: 'pacing_limit_unreadable',
            write_refused: 'pacing_write_refused', yielded: 'pacing_yielded' }[a.action];
        const capW = Number(a.cap_w);
        const capText = Number.isFinite(capW) && capW > 0 ? card._kw(capW) : '';
        const at = a.full_at ? card._hhmm(a.full_at) : '';
        let value = t('next_none');
        if (blocked) value = t(blocked);
        else if (code !== 'none' && code !== 'night') value = (a.enabled ? '' : t('pacing_would') + ' ') + (t('pacing_' + code) || code) + (at ? ' · ' + t('pacing_full_by') + ' ' + at : '');
        moreRows.push(card._row('mdi:speedometer', t('charge_pacing'), value, capText));
        if (paceSw) moreRows.push(card._setRow({ label: card._lbl(Q.pacing.key), help: t(Q.pacing.sub), disabled: dis,
            toggle: { on: card._str(paceSw) === 'on', onChange: () => card._toggleSwitch(paceSw) } }));
    }
    const sellSw = card._has(Q.may_export.entity) ? Q.may_export.entity : null;
    const st = sa.battery_sell_state && sa.battery_sell_state !== 'none' ? sa.battery_sell_state : '';
    if (sellSw || st) {
        const until = sa.battery_sell_until ? card._hhmm(sa.battery_sell_until) : '';
        const value = st === 'selling' ? t('spend_selling') + (until ? ' · ' + t('spend_until') + ' ' + until : '')
            : st === 'scheduled' ? t('spend_sell_planned') + (until ? ' · ' + until : '') : t('next_none');
        const rate = num('sensor.sem_tariff_current_export_rate');
        moreRows.push(card._row('mdi:transmission-tower-export', t('next_sell_window'), value,
            rate === null ? '' : tf('next_export_rate', { rate: card._price(rate) })));
        if (sellSw) moreRows.push(card._setRow({ label: card._lbl(Q.may_export.key), help: t(Q.may_export.sub), disabled: dis,
            toggle: { on: card._str(sellSw) === 'on', onChange: () => card._toggleSwitch(sellSw) } }));
    }
    const bats = card._batteries || [];
    if (bats.length) {
        // (#1321) one row per setting and battery: mode, the level SEM sells down to, the size
        bats.forEach((bid, i) => {
            const n = tf('next_battery_n', { n: i + 1 });
            const id = 'select.sem_battery_' + bid + '_mode';
            const m = card._str(id);
            const lbl = (k) => (bats.length > 1 ? n + ' · ' : '') + card._lbl(k);
            rows.push(card._setRow({ label: lbl('mode'), value: t('battery_mode_' + m) || m || '—', disabled: !card._has(id), blocked: card._devOff(id),
                onTap: () => card._editDialog({ title: lbl('mode'), ...card._selEdit('bmode:' + bid, {
                    value: m, options: (card._attrs(id).options || []).map((o) => ({ key: o, label: t('battery_mode_' + o) || o })),
                    onCommit: (o) => card._selectOption(id, o) }) }) }));
            const rid = 'number.sem_battery_' + bid + '_reserve_soc';
            if (card._has(rid)) {
                const a = card._attrs(rid);
                rows.push(card._setRow({ label: lbl(Q.reserve.key), help: t(Q.reserve.sub), value: card._fmt(num(rid), 0) + ' %', disabled: dis,
                    onTap: () => card._editDialog({ title: lbl(Q.reserve.key), kind: 'number', value: num(rid), min: a.min, max: a.max, step: a.step,
                        unit: '%', onCommit: (x) => card._setNumber(rid, x) }) }));
            }
            // (#1373) each battery's size weighs the total level; unset shows a dash
            const cid = 'number.sem_battery_' + bid + '_capacity_kwh';
            if (card._has(cid)) {
                const a = card._attrs(cid), v = num(cid);
                rows.push(card._setRow({ label: lbl('battery_size_label'), value: v === null ? '—' : card._fmt(v, 1) + ' kWh', disabled: dis,
                    onTap: () => card._editDialog({ title: lbl('battery_size_label'), kind: 'number', value: v, min: a.min, max: a.max, step: a.step,
                        unit: 'kWh', onCommit: (x) => card._setNumber(cid, x) }) }));
            }
        });
        // (#1321) each battery's own level and power, when SEM publishes them
        const units = batteryUnits(card._hass?.states, bats);
        units.forEach((u) => {
            const i = bats.indexOf(u.bid);
            const pw = u.powerW === null ? '—' : (u.powerW < 0 ? '−' : '') + card._kw(Math.abs(u.powerW));
            rows.push(card._row('mdi:battery-outline', tf('next_battery_n', { n: i + 1 }),
                (u.soc === null ? '—' : Math.round(u.soc) + ' %') + ' · ' + pw,
                (() => { const k = String(u.status || '').toLowerCase(); const w = k ? t(k) : ''; return w && w !== k ? w : (u.status || ''); })()));
        });
    }
    const src = card._str('sensor.sem_forecast_source');
    const d1 = card._has('sensor.sem_forecast_trust_d1') ? num('sensor.sem_forecast_trust_d1') : (Number.isFinite(Number(sa.forecast_trust_d1)) ? Number(sa.forecast_trust_d1) * 100 : null);
    const d2 = card._has('sensor.sem_forecast_trust_d2') ? num('sensor.sem_forecast_trust_d2') : (Number.isFinite(Number(sa.forecast_trust_d2)) ? Number(sa.forecast_trust_d2) * 100 : null);
    if (src || d1 !== null || d2 !== null) {
        const pct = (x) => (x === null ? t('learning') : Math.round(x) + ' %');
        rows.push(card._row('mdi:check-decagram-outline', t('next_evidence'),
            (providerName(src) || t('next_src_forecast')) + ' · ' + pct(d1) + ' / ' + pct(d2),
            html`${t('next_trusted_sub')}${card._has(SPEND) ? html` · ${card._val(t('rebuild_nights'), () => card._askFirst(t('rebuild_nights'), () => card._svc('backfill_battery_nights', { days: 365 })), { disabled: dis })}` : ''}`, { more: true }));
    }
    const health = num('sensor.sem_battery_health_score'), cycles = num('sensor.sem_battery_cycles_estimated');
    const temp = num('sensor.sem_battery_temperature');
    const measured = num('sensor.sem_battery_measured_capacity_kwh'), nameplate = num('sensor.sem_diag_battery_capacity');
    if ([health, cycles, temp, measured].some((x) => x !== null)) {
        const top = [];
        if (health !== null) top.push(Math.round(health) + ' %');
        if (cycles !== null) top.push(tf('next_cycles', { n: Math.round(cycles) }));
        const sub = [];
        if (temp !== null) sub.push(card._fmt(temp, 0) + ' ' + (card._unitOf('sensor.sem_battery_temperature') || '°C'));
        if (measured !== null) sub.push(nameplate ? tf('next_measured_of', { cap: card._fmt(measured, 1), nameplate: card._fmt(nameplate, 1) }) : card._kwh(measured));
        rows.push(card._row('mdi:heart-pulse', t('health'), top.join(' · ') || '—', sub.join(' · '), { more: true }));
    }

    return html`
        ${segItems.length ? card._seg(segItems, segKey, pick, { disabled: card._devOff(modeId) }) : nothing}
        ${hint ? html`<div class="modehelp">${hint}</div>` : nothing}
        ${card._stats(stats)}
        ${zones}
        ${sentence}
        ${levelRows.length ? html`<div class="rows" style="margin-top:6px">${levelRows}</div>` : nothing}
        ${rows.length ? html`<div class="rows" style="margin-top:6px">${rows}</div>` : nothing}
        ${moreRows.length ? card._more(html`<div class="rows">${moreRows}</div>`) : nothing}`;
}
