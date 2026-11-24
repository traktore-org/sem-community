/**
 * (#1321) The Devices screen's charger body: mode, stats, the target bar,
 * plan and target values, the buttons and the sheet rows. A function of
 * the card so the card file stays readable; every read goes through the
 * card's entity helpers and every write through its service helpers.
 */

import { codeText } from './code-text.js';
import { chargerAmps } from './charger-amps.js';
import { html, nothing } from '../base/sem-next-base.js';
import { chargerRenameWrite } from './charger-name.js';
import { resolveChargerSoc } from './charger-soc.js';
import { effectivePlan, kwhAhead } from './plan-facts.js';
import { targetModel, weekdaySummary } from './next-devices.js';
import { monthTotals, rowsForMonth } from './sessions.js';
import { rowText } from './next-settings.js';
import { CHARGER_TEXT, CHARGE_MODES, NOW_ENDS, minutesUntil, chargeModeKey, targetEntities, upToShown, knownCapacity, capacityUnset } from './charger-questions.js';

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
    // (#1321) nothing measured yet: the phases the charger is set up with, in the one Phases row
    const set = card._num('number.sem_charger_' + cid + '_ev_phases');
    return Number.isFinite(set) && set > 0 ? card._tf('next_n_phases', { n: card._fmt(set, 0) }) : card._t('phase_status_unknown');
}

export function chargerBody(card, row) {
    const cid = row.cid;
    const t = (k) => card._t(k);
    const tf = (k, p) => card._tf(k, p);
    const dis = false;   // (#1321) charger settings are SEM's own: editable while watching
    const S = (s) => 'sensor.sem_charger_' + cid + '_' + s;
    const ent = (dom, s) => card._chargerEntity(dom, cid, s);
    const cs = card._attrs('sensor.sem_charging_state');

    // ── mode ──
    const modeId = ent('select', 'charge_mode');
    const mode = modeId ? card._str(modeId) : '';
    const modeAttrs = modeId ? card._attrs(modeId) : {};
    const options = Array.isArray(modeAttrs.options) ? modeAttrs.options : [];
    const segKey = mode;
    // (#1381) the engine's own strategy speaks the hints; the user sees four modes
    const strat = modeAttrs.strategy || mode;
    const helpOn = modeAttrs.battery_help !== false;
    const nowUntil = mode === 'now' && modeAttrs.now_until ? card._hhmm(modeAttrs.now_until) : '';
    const tariffOk = modeAttrs.tariff_available !== false;
    const needTariff = Array.isArray(modeAttrs.modes_needing_tariff) ? modeAttrs.modes_needing_tariff : [];
    const pickMode = (key) => { if (modeId && key !== mode) card._selectOption(modeId, key); };
    // (#1381) Now's end: the plan's next block (what picking Now does), a time, or full
    const nowEnd = (key) => {
        if (key === 'block') card._selectOption(modeId, 'now');
        else if (key === 'full') card._selectOption(modeId, 'always_max');
        else card._editDialog({ title: t('next_now_end_time'), ...card._timeEdit('nowend:' + cid, { value: nowUntil,
            onCommit: (v) => { const mins = minutesUntil(v); if (mins) card._callService('solar_energy_management', 'plan_override', { device_id: cid, action: 'force', minutes: mins, user_now: true, fixed_end: true }); } }) });
    };
    const nowEndKey = mode !== 'now' ? '' : (nowUntil ? 'time' : 'full');
    // (#1321) ONE control for the mode, as the battery has: Off first, then the modes in the shared order
    const segItems = ['off', ...CHARGE_MODES.filter((m) => m !== 'off')].filter((m) => options.includes(m))
        .map((m) => ({ key: m, label: t(chargeModeKey(m)) || m, disabled: !tariffOk && needTariff.includes(m) }));
    const buffer = card._num('number.sem_battery_buffer_soc');
    const priority = card._num('number.sem_battery_priority_soc');
    const hintP = { buffer: buffer === null ? '—' : Math.round(buffer), priority: priority === null ? '—' : Math.round(priority) };
    // Day and night: a mode that "never imports grid" by day may still charge from the grid at night.
    const hintNight = strat ? tf('charge_mode_hint_' + strat + '_overnight', hintP) : '';
    const floorType = (ent('select', 'ev_target_type') && card._str(ent('select', 'ev_target_type'))) || 'kwh';
    const floorId = floorType === 'soc' ? ent('number', 'target_soc') : ent('number', 'daily_ev_target');
    const floorVal = floorId ? card._num(floorId) : null;
    const floorGrid = strat === 'solar_plus_battery' && floorVal !== null && floorVal > 0
        ? tf('next_floor_uses_grid', { value: floorType === 'soc' ? Math.round(floorVal) + ' %' : card._kwh(floorVal) }) : '';
    // (#1381 D35) One sentence per mode the user sees, the same for every
    // stored strategy behind it: Sun + tariff is one rule, the battery switch
    // only says whether the house battery helps.
    const userHint = {
        sun: t('mode_hint_sun'),
        sun_tariff: t('mode_hint_sun_tariff'),
        now: tf('mode_hint_now', { end: nowUntil || t('mode_hint_now_full') }),
        off: t('charge_mode_hint_off_surplus'),
    }[mode];
    const hint = userHint || (strat ? [tf('charge_mode_hint_' + strat + '_surplus', hintP),
        floorGrid || (hintNight && !hintNight.startsWith('charge_mode_hint_') ? hintNight : '')].filter(Boolean).join(' ') : '');
    const nextCheap = strat === 'solar_plus_cheap' && cs.ev_next_cheap_window ? card._hhmm(cs.ev_next_cheap_window) : '';
    const pausedUntil = mode === 'off' && modeAttrs.paused_until ? card._hhmm(modeAttrs.paused_until) : '';
    const resumeMode = modeAttrs.pause_resume_mode ? codeText(t, 'charge_mode_', modeAttrs.pause_resume_mode) : '';

    // ── stats ──
    const powerW = card._powerW(S('power'));
    // (#1407) the charger's own current first; SEM's command only while it sends one
    const amps = chargerAmps(card, cid);
    const phases = phaseCount(card, cid);
    const daily = card._num(S('daily_energy'));
    const sunToday = sunShareToday(card, cid);
    // The charger's own counter runs plug-in to plug-out; SEM's ends when charging stops.
    const sessionExt = card._num(S('session_energy_external'));
    const session = sessionExt !== null && sessionExt > 0 ? sessionExt : card._num(S('session_energy'));
    const sessionSun = card._num(S('session_solar_share'));
    const noCarNow = card._str('binary_sensor.sem_charger_' + cid + '_connected') === 'off';
    const stats1 = [
        [t('next_power'), card._kw(powerW), html`${amps === null ? '' : Math.round(amps) + ' A'}${phaseDots(phases)}${phases === null ? '' : ' ' + tf('next_n_ph', { n: phases })}`],
        [t('next_today'), card._kwh(daily), sunToday === null ? '' : tf('next_sun_pct', { pct: Math.round(sunToday) })],
        [t(noCarNow ? 'next_last_session' : 'next_session_cap'), card._kwh(session), sessionSun === null ? '' : tf('next_sun_pct', { pct: Math.round(sessionSun) })],
    ];

    // ── target ──
    const typeId = ent('select', 'ev_target_type');
    const type = typeId ? (card._str(typeId) || 'kwh') : 'kwh';
    const typeOpts = typeId ? (card._attrs(typeId).options || ['kwh']) : ['kwh'];
    const isSoc = type === 'soc';
    const unit = isSoc ? '%' : 'kWh';
    // (#1354) the target pair from the shared model: "At least / Up to", kWh or SOC
    const te = targetEntities(cid, type);
    const minId = card._has(te.atLeast) ? te.atLeast : null;
    const maxId = card._has(te.upTo) ? te.upTo : null;
    const min = minId ? card._num(minId) : null;
    const max = maxId ? card._num(maxId) : null;
    const resolved = resolveChargerSoc(card._num(S('vehicle_soc')), card._num('sensor.sem_vehicle_soc'),
        card._num(S('estimated_soc')), card._chargers.length);
    // (#1321) no car plugged in: the last level is an old reading, so show none
    const noCar = card._str('binary_sensor.sem_charger_' + cid + '_connected') === 'off';
    const soc = noCar ? null : resolved.soc;
    const isEstimate = noCar ? false : resolved.isEstimate;
    const capKey = 'number.sem_charger_' + cid + '_ev_battery_capacity_kwh';
    const capacity = knownCapacity(card._num(capKey), card._attrs(capKey));
    const per100 = card._num('number.sem_charger_' + cid + '_ev_kwh_per_100km');
    const have = isSoc ? soc : daily;
    const tm = targetModel({ have, min, max, isSoc });
    const timeId = ent('time', 'target_time');
    const chargeBy = timeId ? card._hhmm(card._str(timeId)) : '';
    const fmtT = (v) => (v === null ? '—' : (isSoc ? Math.round(v) : card._fmt(v, 1)));
    // (#1321) near an edge the label grows inward, so it never leaves the card
    const edge = tm.flagLeft === null ? '' : (tm.flagLeft < 15 ? 'start' : (tm.flagLeft > 85 ? 'end' : ''));
    const flag = tm.flagLeft === null ? nothing : html`<div class="flag ${edge}" style="left:${tm.flagLeft}%">${tf('next_at_least_x', { x: fmtT(min) + ' ' + unit })}</div>`;
    const target = html`<div class="target">
        <div class="soc" style="width:${tm.fill}%"></div>
        ${tm.bandLeft === null ? nothing : html`<div class="band" style="left:${tm.bandLeft}%;width:${tm.bandWidth}%"></div>`}
        ${flag}</div>`;

    // ── plan · target values ──
    const kmNow = soc !== null && capacity && per100 ? Math.round((soc / 100) * capacity / per100 * 100) : null;
    const gapKwh = have === null || min === null ? null : (isSoc ? Math.max(0, (min - soc) / 100 * (capacity || 0)) : Math.max(0, min - daily));
    const kmAdd = gapKwh !== null && per100 ? Math.round(gapKwh / per100 * 100) : null;
    const plan = effectivePlan(card._attrs('sensor.sem_energy_plan'));
    const plannedKwh = Array.isArray(plan.blocks) ? kwhAhead(plan, (id) => id === 'ev:' + cid, Date.now()) : 0;
    const dep = ((cs.per_charger_departure || {})[cid]) || {};
    const own = dep.by_weekday || {};
    const hasOwnDays = Object.keys(own).length > 0;
    const depDefault = chargeBy || dep.default || '';
    const timeVal = html`${chargeBy || '—'}`;
    const runs = weekdaySummary(own, depDefault);
    const runText = runs.map((r) => (r.from === r.to ? card._dayName(r.from) : card._dayName(r.from) + ' – ' + card._dayName(r.to)) + ' ' + r.time).join(' · ');
    const daysVal = card._val(hasOwnDays ? (runText || t('ev_dep_most_days')) : t('next_every_day'), () => card._toggleDep(cid), { disabled: dis });
    // (#1321) never "up to 100 kWh" on a 40 kWh car; unknown car and the setting's ceiling: "full"
    const upTo = upToShown({ max, capacity, bound: maxId ? Number(card._attrs(maxId).max) : null, isSoc, unset: capacityUnset(card._attrs(capKey)) });
    const targetText = upTo.full ? `${t(CHARGER_TEXT.atLeast)} ${fmtT(min)} ${unit} · ${t('next_up_to_full')}`
        : `${t(CHARGER_TEXT.atLeast)} ${fmtT(min)} · ${t(CHARGER_TEXT.upTo)} ${fmtT(upTo.max)} ${unit}`;
    const targetVal = html`${targetText}`;
    const typeVal = html`${isSoc ? t('next_soc') : 'kWh'}`;
    const stats2 = html`<div class="stats" style="margin-top:4px">
        <div><span class="lbl">${t('next_charge')}</span><div class="big num">${soc === null ? '—' : (isEstimate ? '~' : '') + Math.round(soc) + ' %'}</div>
            <div class="sub2">${soc === null ? t('next_no_soc') : [kmNow === null ? '' : tf('next_km', { km: kmNow }), isEstimate ? t('next_estimate') : t('next_measured')].filter(Boolean).join(' · ')}</div></div>
    </div>`;

    // ── buttons ──
    const btns = [];
    const boostBtns = [];
    let boostFloor = null;
    const pauseBtn = 'button.sem_charger_' + cid + '_pause_charging';
    if (card._has(pauseBtn)) {
        btns.push(card._btn(t('pause_charging'), () => card._askFirst(t('pause_charging'), () => card._pressButton(pauseBtn), { body: t('next_confirm_pause') }), { small: true, primary: true, icon: 'mdi:pause', disabled: card._devOff(pauseBtn, 'button') }));
    }
    if (card._has('sensor.sem_battery_soc')) {
        const boost = cs.battery_boost || null;
        const running = !!(boost && boost.active && boost.charger_id === cid);
        if (running) {
            boostBtns.push(card._btn(t('next_stop_boost'), () => card._svc('stop_battery_boost', {}), { small: true, ghost: true, icon: 'mdi:stop', disabled: card._obs() }));
            boostBtns.push(html`<span class="sm muted">${tf('next_boost_left', { kwh: card._fmt(boost.remaining_kwh, 1), floor: Math.round(Number(boost.floor_soc) || 0) })}</span>`);
        } else if (dep.boost_allowed === false) {
            boostBtns.push(card._pill(t('ev_boost_not_permitted'), 'warn', { icon: 'mdi:battery-lock' }));
        } else {
            const preview = cs.battery_boost_preview || {};
            const floor = (card._boostFloor || {})[cid] ?? Math.round(Number(preview.default_floor ?? 50));
            boostBtns.push(card._btn(t('next_boost_go'), () => card._askFirst(t('next_boost_go'), () => card._svc('start_battery_boost', { charger_id: cid, floor_soc: floor }), { body: t('next_confirm_boost') }), { small: true, ghost: true, icon: 'mdi:home-battery-outline', disabled: card._obs() }));
            boostFloor = floor;
        }
    }
    btns.push(card._btn(t('next_sessions'), () => card._go(card._screen('insights') + '#car'), { small: true, ghost: true, icon: 'mdi:history' }));

    // ── sheet rows ──
    const depEditor = card._depOpen && card._depOpen[cid] ? html`<div class="days" data-plan=${cid}>
        ${DAYS.map((d, i) => html`<label class="dayin"><span>${card._dayName(i)}</span>
            ${card._input({ type: 'time', value: own[d] || '', placeholder: depDefault, disabled: dis, label: card._dayName(i),
                onChange: (e) => { const map = { ...own }; const v = e.target.value; if (!v || v === depDefault) delete map[d]; else map[d] = v; card._svc('set_charger_departure', { charger_id: cid, by_weekday: map }); } })}</label>`)}
        <div class="help">${tf('next_dep_help', { time: depDefault || '—' })}</div></div>` : nothing;
    const oneBlock = !!dep.one_block;
    const lateMin = Number(dep.late_min) || 0;
    const lateOpts = LATE.includes(lateMin) ? LATE : [...LATE, lateMin].sort((a, b) => a - b);
    const rows = [];
    const moreRows = [];
    // (#1321) the weekly schedule is on the tile above once; its day editor opens from there
    if (depEditor !== nothing) rows.push(depEditor);
    const send = (data) => card._svc('set_charger_departure', { charger_id: cid, ...data });
    const lateLabel = (m) => (m ? tf('ev_dep_minutes', { n: m }) : t('ev_dep_late_off'));
    // (#1321) every setting of this charger is a row: tap it, a dialog opens; a boolean is a switch
    const setRows = [];
    // (#1321) a pause length with no text reads "2 hours", never "2_hours"
    const pauseLabel = (o) => { const k = 'pause_duration_' + o; const v = t(k); return v && v !== k ? v : String(o || '').replace(/_/g, ' '); };
    // (#1386) the name: a SEM setting, so it stays open in watch-only mode
    // (#1321) "Name in SEM", as the device settings call it: the charger's own name stays
    setRows.push(card._setRow({ label: t('cfg_own_name'), value: row.name || '—',
        onTap: () => card._editDialog({ title: t('cfg_own_name'), ...card._textEdit('name:' + cid, { value: row.name, onCommit: (v) => {
            const w = chargerRenameWrite(cid, v);
            if (w && w.ev_chargers[0].name !== row.name) card._svc('set_option', { options: w });
        } }) }) }));
    // (#1381) one switch: may the battery help this car? (Now and Off remember it)
    if (modeId && (mode === 'sun' || mode === 'sun_tariff')) {
        setRows.push(card._setRow({ label: t('next_battery_help'), help: t(helpOn ? 'next_battery_help_on' : 'next_battery_help_off'), disabled: dis,
            toggle: { on: helpOn, onChange: (v) => card._svc('set_option', { options: { ev_chargers: [{ id: cid, ev_battery_help: !!v }] } }) } }));
    }
    const srow = (label, value, spec, o = {}) => card._setRow({ label, value, disabled: dis || !!o.disabled, help: o.help || '', more: !!o.more,
        onTap: () => card._editDialog({ title: label, ...spec }) });
    if (timeId) {
        // (#1321) the schedule is shown once, here: the time, its weekdays, the next departure and the planned kWh
        const more = [dep.next && card._hhmm(dep.next) !== chargeBy ? tf('next_next_departure', { time: card._hhmm(dep.next) }) : '',
            plannedKwh > 0 ? tf('next_kwh_planned', { kwh: card._fmt(plannedKwh, 1) }) : ''].filter(Boolean).join(' · ');
        setRows.push(srow(t(CHARGER_TEXT.departure), chargeBy || '—', card._timeEdit('time:' + cid, { value: chargeBy, onCommit: (v) => card._setTime(timeId, v) }), { help: more }));
        setRows.push(card._setRow({ label: card._lbl('next_days'), value: daysVal, disabled: dis }));
    }
    if (minId && maxId) {
        // the dialog's ceiling is the car's battery too, when it is known
        const cap = (id) => { const m = Number(card._attrs(id).max); return !isSoc && capacity > 0 && Number.isFinite(m) ? Math.min(m, capacity) : card._attrs(id).max; };
        const at = (id) => ({ value: card._num(id), min: card._attrs(id).min, max: cap(id), step: card._attrs(id).step });
        setRows.push(srow(t(CHARGER_TEXT.target), targetText, card._pairEdit('target:' + cid, { a: at(minId), b: at(maxId), unit,
            onCommit: (a, b) => { if (a !== null) card._setNumber(minId, a); if (b !== null) card._setNumber(maxId, b); } })));
    }
    if (typeOpts.length > 1) {
        setRows.push(srow(card._lbl('next_goal_unit'), isSoc ? t('next_soc') : 'kWh', card._selEdit('type:' + cid, {
            value: type, options: typeOpts.map((o) => ({ key: o, label: o === 'soc' ? t('next_soc') : 'kWh' })), onCommit: (v) => card._selectOption(typeId, v) })));
    }
    if (boostFloor !== null) {
        const fl = FLOORS.includes(boostFloor) ? FLOORS : [...FLOORS, boostFloor].sort((a, b) => a - b);
        moreRows.push(srow(card._lbl('next_boost_to'), boostFloor + ' %', card._selEdit('boost:' + cid, {
            value: String(boostFloor), options: fl.map((f) => ({ key: String(f), label: f + ' %' })),
            onCommit: (v) => { card._boostFloor = { ...(card._boostFloor || {}), [cid]: Number(v) }; card._tick++; } })));
    }
    const durId = 'select.sem_pause_duration';
    if (card._has(pauseBtn) && card._has(durId) && card._str(durId)) {
        const dur = card._str(durId);
        setRows.push(srow(rowText(t('pause_charging') + ' ' + t('next_for')), pauseLabel(dur), card._selEdit('pausedur', {
            value: dur, options: (card._attrs(durId).options || []).map((o) => ({ key: o, label: pauseLabel(o) })), onCommit: (v) => card._selectOption(durId, v) })));
    }
    moreRows.push(card._setRow({ label: card._lbl('ev_dep_one_block'), disabled: dis, toggle: { on: oneBlock, onChange: (v) => send({ one_block: v }) } }));
    moreRows.push(srow(card._lbl('ev_dep_late_charge'), lateLabel(lateMin), card._selEdit('late:' + cid, {
        value: String(lateMin), options: lateOpts.map((m) => ({ key: String(m), label: lateLabel(m) })),
        onCommit: (v) => send({ late_charge_min: Number(v) }) })));
    const phaseId = ent('select', 'phase_mode');
    if (phaseId || phases !== null) {
        const pm = phaseId ? card._str(phaseId) : '';
        const pOpts = phaseId ? (card._attrs(phaseId).options || ['auto', '1', '3']) : [];
        moreRows.push(card._row('mdi:sine-wave', t('next_phases'),
            phaseId ? card._seg(pOpts.map((o) => ({ key: o, label: codeText(t, 'phase_mode_', o) })), pm, (o) => card._selectOption(phaseId, o), { small: true, disabled: dis })
                : phaseStatus(card, cid),
            phaseId ? phaseStatus(card, cid) : ''));
    }
    const capId = 'number.sem_charger_' + cid + '_ev_battery_capacity_kwh';
    const minAId = 'number.sem_charger_' + cid + '_minimum_current';
    const maxAId = 'number.sem_charger_' + cid + '_maximum_current';
    const perId = 'number.sem_charger_' + cid + '_ev_kwh_per_100km';
    // (#1321) set once: the car's battery and the charger's current range, each its own row
    const numSet = (id, label, text, unit) => {
        if (!card._has(id)) return;
        const a = card._attrs(id);
        moreRows.push(srow(label, text, { kind: 'number', value: card._num(id), min: a.min, max: a.max, step: a.step, unit,
            onCommit: (x) => card._setNumber(id, x) }));
    };
    numSet(capId, card._lbl('next_more_capacity'), capacityUnset(card._attrs(capId)) ? t('next_not_set') : card._kwh(card._num(capId), 0), 'kWh');
    numSet(minAId, card._lbl('next_row_min_current'), card._fmt(card._num(minAId), 0) + ' A', 'A');
    numSet(maxAId, card._lbl('next_row_max_current'), card._fmt(card._num(maxAId), 0) + ' A', 'A');
    numSet(perId, card._lbl('next_more_use'), card._fmt(card._num(perId), 1) + ' kWh/100 km', 'kWh/100 km');
    // (#1321) the phases are one row above; the setting itself is on System
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

    rows.unshift(...setRows);
    return html`
        ${segItems.length ? card._seg(segItems, segKey, pickMode, { disabled: dis }) : nothing}
        ${mode === 'now' ? html`<div class="modehelp">${nowUntil ? tf('next_now_until', { time: nowUntil }) : t('next_now_until_full')}</div>
            ${card._seg(NOW_ENDS.map((k) => ({ key: k, label: t('next_now_end_' + k) })), nowEndKey, nowEnd, { small: true, disabled: dis })}` : nothing}
        ${mode !== 'now' && (hint || pausedUntil) ? html`<div class="modehelp">${pausedUntil ? tf('next_paused_until', { time: pausedUntil, mode: resumeMode }) + ' ' : ''}${hint}${nextCheap ? ' · ' + tf('next_next_cheap', { time: nextCheap }) : ''}</div>` : nothing}
        ${card._stats(stats1)}
        ${target}
        ${stats2}
        <div class="btns" style="margin-top:6px">${btns}</div>
        <div class="sheet"><div class="rows">${rows}</div>
            ${card._more(html`${boostBtns.length ? html`<div class="btns" style="margin:8px 0">${boostBtns}</div>` : nothing}<div class="rows">${moreRows}</div>`)}</div>`;
}
