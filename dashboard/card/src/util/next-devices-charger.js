/**
 * (#1321) The Devices screen's charger body: mode, stats, the target bar,
 * plan and target values, the buttons and the sheet rows. A function of
 * the card so the card file stays readable; every read goes through the
 * card's entity helpers and every write through its service helpers.
 */

import { html, nothing } from '../base/sem-next-base.js';
import { resolveChargerSoc } from './charger-soc.js';
import { kwhOf } from './next-lead.js';
import { targetModel, weekdaySummary } from './next-devices.js';
import { monthTotals, rowsForMonth } from './sessions.js';

const SMART_DEFAULT = 'min_plus_solar';
const LATE = [0, 15, 30, 45, 60, 90, 120];
const FLOORS = [10, 20, 30, 40, 50, 60, 70, 80, 90];
const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

function thisMonth() {
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
}

/** The phase count the backend knows for this charger, or null. */
function phaseCount(card, cid) {
    const ph = (card._attrs('sensor.sem_charging_state').per_charger_phases || {})[cid] || {};
    const n = Number(ph.active_phases || ph.believed_phases);
    if (Number.isFinite(n) && n > 0) return n;
    const cfg = card._num('number.sem_charger_' + cid + '_ev_phases');
    return Number.isFinite(cfg) && cfg > 0 ? cfg : null;
}

/** Sun share of today's charge from the per-charger flow sensors, or null. */
function sunShareToday(card, cid) {
    const S = (s) => 'sensor.sem_charger_' + cid + '_flow_' + s + '_to_ev_energy';
    const sol = card._num(S('solar'));
    if (sol === null) return null;
    const tot = sol + (card._num(S('grid')) || 0) + (card._num(S('battery')) || 0);
    return tot > 0 ? (sol / tot) * 100 : null;
}

function phaseDots(n) {
    const dots = [];
    for (let i = 0; i < 3; i++) dots.push(html`<i class="${n !== null && i < n ? 'on' : ''}"></i>`);
    return html`<span class="ph">${dots}</span>`;
}

function phaseStatus(card, cid) {
    const ph = (card._attrs('sensor.sem_charging_state').per_charger_phases || {})[cid] || {};
    if (ph.switch_state === 'stopping') return card._t('phase_status_stopping');
    if (ph.switch_state === 'settling') return card._t('phase_status_settling');
    if (ph.active_phases) return card._tf('phase_status_measured', { n: ph.active_phases });
    if (ph.believed_phases) return card._tf('phase_status_believed', { n: ph.believed_phases });
    return card._t('phase_status_unknown');
}

export function chargerBody(card, row) {
    const cid = row.cid;
    const t = (k) => card._t(k);
    const tf = (k, p) => card._tf(k, p);
    const dis = card._obs();
    const S = (s) => 'sensor.sem_charger_' + cid + '_' + s;
    const ent = (dom, s) => card._chargerEntity(dom, cid, s);
    const cs = card._attrs('sensor.sem_charging_state');

    // ── mode ──
    const modeId = ent('select', 'charge_mode');
    const mode = modeId ? card._str(modeId) : '';
    const modeAttrs = modeId ? card._attrs(modeId) : {};
    const options = Array.isArray(modeAttrs.options) ? modeAttrs.options : [];
    const smartOpts = options.filter((o) => o !== 'off' && o !== 'always_max');
    const segKey = mode === 'off' ? 'off' : mode === 'always_max' ? 'always' : 'smart';
    const tariffOk = modeAttrs.tariff_available !== false;
    const needTariff = Array.isArray(modeAttrs.modes_needing_tariff) ? modeAttrs.modes_needing_tariff : [];
    const pickSmart = () => {
        const last = (card._smartLast || {})[cid];
        const first = smartOpts.includes(SMART_DEFAULT) ? SMART_DEFAULT : smartOpts[0];
        card._selectOption(modeId, smartOpts.includes(last) ? last : first);
    };
    const pickMode = (key) => {
        if (!modeId) return;
        if (key === 'off') card._selectOption(modeId, 'off');
        else if (key === 'always') card._selectOption(modeId, 'always_max');
        else pickSmart();
    };
    const segItems = [];
    if (options.includes('off')) segItems.push({ key: 'off', label: t('charge_mode_off') });
    if (smartOpts.length) segItems.push({ key: 'smart', label: t('next_smart'), icon: 'mdi:chevron-down' });
    if (options.includes('always_max')) segItems.push({ key: 'always', label: t('next_always') });
    const smartSeg = segKey === 'smart' && smartOpts.length > 1 ? card._seg(
        smartOpts.map((o) => ({ key: o, label: t('charge_mode_' + o) || o, disabled: !tariffOk && needTariff.includes(o) })),
        mode, (o) => { card._smartLast = { ...(card._smartLast || {}), [cid]: o }; card._selectOption(modeId, o); },
        { small: true, disabled: dis }) : nothing;
    const buffer = card._num('number.sem_battery_buffer_soc');
    const priority = card._num('number.sem_battery_priority_soc');
    const hint = mode ? tf('charge_mode_hint_' + mode + '_surplus', {
        buffer: buffer === null ? '—' : Math.round(buffer), priority: priority === null ? '—' : Math.round(priority) }) : '';
    const nextCheap = mode === 'solar_plus_cheap' && cs.ev_next_cheap_window ? card._hhmm(cs.ev_next_cheap_window) : '';
    const pausedUntil = mode === 'off' && modeAttrs.paused_until ? card._hhmm(modeAttrs.paused_until) : '';
    const resumeMode = modeAttrs.pause_resume_mode ? (t('charge_mode_' + modeAttrs.pause_resume_mode) || modeAttrs.pause_resume_mode) : '';

    // ── stats ──
    const powerW = card._powerW(S('power'));
    const amps = card._num(S('commanded_current'));
    const phases = phaseCount(card, cid);
    const daily = card._num(S('daily_energy'));
    const sunToday = sunShareToday(card, cid);
    const session = card._num(S('session_energy'));
    const sessionSun = card._num(S('session_solar_share'));
    const stats1 = [
        [t('next_power'), card._kw(powerW), html`${amps === null ? '' : Math.round(amps) + ' A'}${phaseDots(phases)}${phases === null ? '' : ' ' + tf('next_n_ph', { n: phases })}`],
        [t('next_today'), card._kwh(daily), sunToday === null ? '' : tf('next_sun_pct', { pct: Math.round(sunToday) })],
        [t('next_session_cap'), card._kwh(session), sessionSun === null ? '' : tf('next_sun_pct', { pct: Math.round(sessionSun) })],
    ];

    // ── target ──
    const typeId = ent('select', 'ev_target_type');
    const type = typeId ? (card._str(typeId) || 'kwh') : 'kwh';
    const typeOpts = typeId ? (card._attrs(typeId).options || ['kwh']) : ['kwh'];
    const isSoc = type === 'soc';
    const unit = isSoc ? '%' : 'kWh';
    const minId = isSoc ? ent('number', 'target_soc') : ent('number', 'daily_ev_target');
    const maxId = isSoc ? ent('number', 'target_soc_max') : ent('number', 'daily_ev_target_max');
    const min = minId ? card._num(minId) : null;
    const max = maxId ? card._num(maxId) : null;
    const { soc, isEstimate } = resolveChargerSoc(card._num(S('vehicle_soc')), card._num('sensor.sem_vehicle_soc'),
        card._num(S('estimated_soc')), card._chargers.length);
    const capacity = card._num('number.sem_charger_' + cid + '_ev_battery_capacity_kwh');
    const per100 = card._num('number.sem_charger_' + cid + '_ev_kwh_per_100km');
    const have = isSoc ? soc : daily;
    const tm = targetModel({ have, min, max, isSoc });
    const timeId = ent('time', 'target_time');
    const chargeBy = timeId ? card._hhmm(card._str(timeId)) : '';
    const fmtT = (v) => (v === null ? '—' : (isSoc ? Math.round(v) : card._fmt(v, 1)));
    const flag = tm.flagLeft === null ? nothing : html`<div class="flag" style="left:${tm.flagLeft}%">${chargeBy ? chargeBy + ' · ' : ''}${tf('next_at_least_x', { x: fmtT(min) + ' ' + unit })}</div>`;
    const target = html`<div class="target">
        <div class="soc" style="width:${tm.fill}%"></div>
        ${tm.bandLeft === null ? nothing : html`<div class="band" style="left:${tm.bandLeft}%;width:${tm.bandWidth}%"></div>`}
        ${flag}</div>`;

    // ── plan · target values ──
    const kmNow = soc !== null && capacity && per100 ? Math.round((soc / 100) * capacity / per100 * 100) : null;
    const gapKwh = have === null || min === null ? null : (isSoc ? Math.max(0, (min - soc) / 100 * (capacity || 0)) : Math.max(0, min - daily));
    const kmAdd = gapKwh !== null && per100 ? Math.round(gapKwh / per100 * 100) : null;
    const plan = card._attrs('sensor.sem_energy_plan');
    const plannedKwh = Array.isArray(plan.blocks) ? kwhOf(plan.blocks, (id) => id === 'ev:' + cid) : 0;
    const dep = ((cs.per_charger_departure || {})[cid]) || {};
    const own = dep.by_weekday || {};
    const hasOwnDays = Object.keys(own).length > 0;
    const depDefault = chargeBy || dep.default || '';
    const timeVal = timeId ? card._inline('time:' + cid, chargeBy || '—', () => card._timeEdit('time:' + cid, {
        value: chargeBy, onCommit: (v) => card._setTime(timeId, v) })) : html`${chargeBy || '—'}`;
    const daysVal = card._val(hasOwnDays ? t('ev_dep_most_days') : t('next_every_day'), () => card._toggleDep(cid), { disabled: dis });
    const targetText = fmtT(min) + ' – ' + fmtT(max) + ' ' + unit;
    const targetVal = minId && maxId ? card._inline('target:' + cid, targetText, () => card._pairEdit('target:' + cid, {
        a: { value: min, min: card._attrs(minId).min, max: card._attrs(minId).max, step: card._attrs(minId).step },
        b: { value: max, min: card._attrs(maxId).min, max: card._attrs(maxId).max, step: card._attrs(maxId).step },
        unit, onCommit: (a, b) => { if (a !== null) card._setNumber(minId, a); if (b !== null) card._setNumber(maxId, b); } })) : html`${targetText}`;
    const typeVal = typeOpts.length > 1
        ? card._val(isSoc ? t('next_soc') : 'kWh', () => card._selectOption(typeId, isSoc ? 'kwh' : 'soc'), { disabled: dis })
        : html`${isSoc ? t('next_soc') : 'kWh'}`;
    const stats2 = html`<div class="stats" style="margin-top:4px">
        <div><span class="lbl">${t('next_charge')}</span><div class="big num">${soc === null ? '—' : (isEstimate ? '~' : '') + Math.round(soc) + ' %'}</div>
            <div class="sub2">${soc === null ? t('next_no_soc') : html`${kmNow === null ? '' : tf('next_km', { km: kmNow }) + ' · '}${isEstimate ? t('next_estimate') : t('next_measured')}`}</div></div>
        <div><span class="lbl">${t('next_plan')}</span><div class="big num">${timeVal}</div>
            <div class="sub2">${daysVal}${plannedKwh > 0 ? ' · ' + tf('next_kwh_planned', { kwh: card._fmt(plannedKwh, 1) }) : ''}</div></div>
        <div><span class="lbl">${t('next_target')}</span><div class="big num">${targetVal}</div>
            <div class="sub2">${typeVal} ↔ ${isSoc ? 'kWh' : t('next_soc')}${kmAdd ? ' · ' + tf('next_plus_km', { km: kmAdd }) : ''}</div></div>
    </div>`;

    // ── buttons ──
    const btns = [];
    const pauseBtn = 'button.sem_charger_' + cid + '_pause_charging';
    if (card._has(pauseBtn)) {
        const durId = 'select.sem_pause_duration';
        const dur = card._has(durId) ? card._str(durId) : '';
        const durOpts = card._has(durId) ? (card._attrs(durId).options || []) : [];
        btns.push(card._btn(t('pause_charging'), () => card._pressButton(pauseBtn), { small: true, icon: 'mdi:pause', disabled: dis }));
        if (dur) btns.push(html`<span class="sm muted">${t('next_for')} ${card._inline('pausedur', t('pause_duration_' + dur) || dur, () => card._selEdit('pausedur', {
            value: dur, options: durOpts.map((o) => ({ key: o, label: t('pause_duration_' + o) || o })), onCommit: (v) => card._selectOption(durId, v) }))}</span>`);
    }
    if (card._has('sensor.sem_battery_soc')) {
        const boost = cs.battery_boost || null;
        const running = !!(boost && boost.active && boost.charger_id === cid);
        if (running) {
            btns.push(card._btn(t('next_stop_boost'), () => card._svc('stop_battery_boost', {}), { small: true, icon: 'mdi:stop', disabled: dis }));
            btns.push(html`<span class="sm muted">${tf('next_boost_left', { kwh: card._fmt(boost.remaining_kwh, 1), floor: Math.round(Number(boost.floor_soc) || 0) })}</span>`);
        } else if (dep.boost_allowed === false) {
            btns.push(card._pill(t('ev_boost_not_permitted'), 'warn', { icon: 'mdi:battery-lock' }));
        } else {
            const preview = cs.battery_boost_preview || {};
            const floor = (card._boostFloor || {})[cid] ?? Math.round(Number(preview.default_floor ?? 50));
            btns.push(card._btn(t('next_boost_to'), () => card._svc('start_battery_boost', { charger_id: cid, floor_soc: floor }), { small: true, icon: 'mdi:home-battery-outline', disabled: dis }));
            btns.push(html`<span class="sm muted">${card._inline('boost:' + cid, floor + ' %', () => card._selEdit('boost:' + cid, {
                value: String(floor), options: (FLOORS.includes(floor) ? FLOORS : [...FLOORS, floor].sort((a, b) => a - b)).map((f) => ({ key: String(f), label: f + ' %' })),
                onCommit: (v) => { card._boostFloor = { ...(card._boostFloor || {}), [cid]: Number(v) }; } }))}</span>`);
        }
    }
    btns.push(card._btn(t('next_sessions'), () => card._go('/sem-next/insights#car'), { small: true, icon: 'mdi:history' }));

    // ── sheet rows ──
    const runs = weekdaySummary(own, depDefault);
    const runText = runs.map((r) => (r.from === r.to ? card._dayName(r.from) : card._dayName(r.from) + ' – ' + card._dayName(r.to)) + ' ' + r.time).join(' · ');
    const nextDep = dep.next ? card._hhmm(dep.next) : '';
    const depEditor = card._depOpen && card._depOpen[cid] ? html`<div class="days">
        ${DAYS.map((d, i) => html`<label class="dayin"><span>${card._dayName(i)}</span>
            <input type="time" .value=${own[d] || ''} placeholder=${depDefault} ?disabled=${dis}
                @change=${(e) => { const map = { ...own }; const v = e.target.value; if (!v || v === depDefault) delete map[d]; else map[d] = v; card._svc('set_charger_departure', { charger_id: cid, by_weekday: map }); }}></label>`)}
        <div class="help">${tf('next_dep_help', { time: depDefault || '—' })}</div></div>` : nothing;
    const oneBlock = !!dep.one_block;
    const lateMin = Number(dep.late_min) || 0;
    const lateOpts = LATE.includes(lateMin) ? LATE : [...LATE, lateMin].sort((a, b) => a - b);
    const rows = [];
    rows.push(card._row('mdi:calendar-repeat', t('next_departures'), runText || depDefault || '—',
        nextDep ? tf('next_next_departure', { time: nextDep }) : (hasOwnDays ? t('ev_dep_most_days') : ''), { onClick: () => card._toggleDep(cid) }));
    if (depEditor !== nothing) rows.push(depEditor);
    rows.push(card._row('mdi:view-agenda', t('ev_dep_one_block'),
        card._val(oneBlock ? t('next_on') : t('next_off'), () => card._svc('set_charger_departure', { charger_id: cid, one_block: !oneBlock }), { disabled: dis }),
        html`${t('ev_dep_late_charge')}: ${card._inline('late:' + cid, lateMin ? tf('ev_dep_minutes', { n: lateMin }) : t('ev_dep_late_off'), () => card._selEdit('late:' + cid, {
            value: String(lateMin), options: lateOpts.map((m) => ({ key: String(m), label: m ? tf('ev_dep_minutes', { n: m }) : t('ev_dep_late_off') })),
            onCommit: (v) => card._svc('set_charger_departure', { charger_id: cid, late_charge_min: Number(v) }) }))}`));
    const phaseId = ent('select', 'phase_mode');
    if (phaseId || phases !== null) {
        const pm = phaseId ? card._str(phaseId) : '';
        const pOpts = phaseId ? (card._attrs(phaseId).options || ['auto', '1', '3']) : [];
        rows.push(card._row('mdi:sine-wave', t('next_phases'),
            phaseId ? card._seg(pOpts.map((o) => ({ key: o, label: t('phase_mode_' + o) || o })), pm, (o) => card._selectOption(phaseId, o), { small: true, disabled: dis })
                : phaseStatus(card, cid),
            phaseId ? phaseStatus(card, cid) : ''));
    }
    const once = [];
    const capId = 'number.sem_charger_' + cid + '_ev_battery_capacity_kwh';
    const minAId = 'number.sem_charger_' + cid + '_minimum_current';
    const maxAId = 'number.sem_charger_' + cid + '_maximum_current';
    const perId = 'number.sem_charger_' + cid + '_ev_kwh_per_100km';
    const phId = 'number.sem_charger_' + cid + '_ev_phases';
    if (card._has(capId)) once.push(card._val(card._kwh(card._num(capId), 0), () => card._moreInfo(capId)));
    if (card._has(minAId) || card._has(maxAId)) {
        const a = card._has(minAId) ? card._fmt(card._num(minAId), 0) : '—';
        const b = card._has(maxAId) ? card._fmt(card._num(maxAId), 0) : '—';
        once.push(card._val(a + ' – ' + b + ' A', () => card._moreInfo(card._has(minAId) ? minAId : maxAId)));
    }
    if (card._has(perId)) once.push(card._val(card._fmt(card._num(perId), 1) + ' kWh/100 km', () => card._moreInfo(perId)));
    if (once.length) {
        rows.push(card._row('mdi:tune', t('next_set_once'), html`${once.map((v, i) => html`${i ? ' · ' : ''}${v}`)}`,
            html`${t('next_set_once_sub')}${card._has(phId) ? html` · ${card._val(tf('next_n_phases', { n: card._fmt(card._num(phId), 0) }), () => card._moreInfo(phId))}` : ''}`, { more: true }));
    }
    if (card._has(S('estimated_soc'))) {
        const est = card._num(S('estimated_soc'));
        const ea = card._attrs(S('estimated_soc'));
        const lastAt = Date.parse(ea.vehicle_soc_last_at || '');
        const sub = Number.isFinite(lastAt) && ea.vehicle_soc_last != null
            ? tf('next_soc_est_sub', { soc: Math.round(Number(ea.vehicle_soc_last)), age: Math.round((Date.now() - lastAt) / 60000) })
            : t('next_soc_est_learning');
        rows.push(card._row('mdi:school-outline', t('next_soc_estimate'), est === null ? '—' : '~' + Math.round(est) + ' %', sub, { more: true, onClick: () => card._moreInfo(S('estimated_soc')) }));
    }
    const sess = (card._sess || {})[cid];
    if (sess && Array.isArray(sess.rows)) {
        const m = monthTotals(rowsForMonth(sess.rows, thisMonth()));
        rows.push(card._row('mdi:chart-bar', t('next_this_month'), tf('next_n_sessions', { n: m.count }) + ' · ' + card._kwh(m.kwh),
            html`${tf('next_sun_pct', { pct: m.solarPct })}${m.cost === null ? '' : ' · ' + card._money(m.cost)} · ${card._val(t('sessions_xlsx'), () => card._downloadXlsx(cid))}`, { more: true }));
    } else {
        rows.push(card._row('mdi:chart-bar', t('next_this_month'), '…', '', { more: true }));
    }
    if (card._chargers.length === 1 && card._has('sensor.sem_lifetime_ev_energy')) {
        const e = card._num('sensor.sem_lifetime_ev_energy'), c = card._num('sensor.sem_lifetime_ev_cost');
        const share = card._num('sensor.sem_lifetime_ev_solar_share'), n = card._num('sensor.sem_lifetime_ev_sessions');
        const parts = [];
        if (share !== null) parts.push(tf('next_sun_pct', { pct: Math.round(share) }));
        if (e && c !== null) parts.push(tf('next_per_kwh', { v: card._money(c / e) }));
        if (n !== null) parts.push(tf('next_n_sessions', { n: Math.round(n) }));
        rows.push(card._row('mdi:all-inclusive', t('next_lifetime'), card._kwh(e, 0) + (c === null ? '' : ' · ' + card._money(c)), parts.join(' · '), { more: true }));
    }

    return html`
        ${segItems.length ? card._seg(segItems, segKey, pickMode, { disabled: dis }) : nothing}
        ${smartSeg !== nothing ? html`<div style="margin-top:6px">${smartSeg}</div>` : nothing}
        ${hint || pausedUntil ? html`<div class="modehelp">${pausedUntil ? tf('next_paused_until', { time: pausedUntil, mode: resumeMode }) + ' ' : ''}${segKey === 'smart' ? html`${t('next_smart_is')} <b>${t('charge_mode_' + mode) || mode}</b> · ` : ''}${hint}${nextCheap ? ' · ' + tf('next_next_cheap', { time: nextCheap }) : ''}</div>` : nothing}
        ${card._stats(stats1)}
        ${target}
        ${stats2}
        <div class="btns" style="margin-top:6px">${btns}</div>
        <div class="sheet"><div class="rows">${rows}</div></div>`;
}
