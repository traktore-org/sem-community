/**
 * (#1321) The Devices screen's load body (a boiler, a heat pump, a pump,
 * any switched load): the four-way mode, stats, the runtime track and
 * the rows Goal · Min run / pause · Requires · Phase · Legionella ·
 * Comfort · Device tariff · SEM may switch it. Every write is one
 * update_device_config call (the properties the backend accepts).
 * (#1321) Up top: Normal · Smart · Boost. Boost is a one-off plan_override
 * force for 30/60/120 min; the four-way mode sits under All settings.
 */

import { html, nothing } from '../base/sem-next-base.js';
import { antiCyclePlaceholder, antiCycleBounds, antiCycleValue } from './load-sections.js';
import { goalPct, modeWrites, overnightSource, overnightWrites, isTemperature, statePill, modeHelpKey } from './next-devices.js';
import { plainReason } from './why-rows.js';
import { loadRunsBySem } from './settings-applies.js';
import { parseCopCurve, formatCopCurve, heatCostNow } from './heat-pump-cost.js';
import { heaterQuestions, heaterSub, sunMaxWrites, limitWrites, buyWrites, BUY_LABEL } from './heater-questions.js';

const MODES = [
    { key: 'off', label: 'off', help: 'help_mode_off' },
    { key: 'peak_only', label: 'peak_only', help: 'help_mode_peak_only' },
    // (#1349) a load's mode says who runs it; the buy question says whether power is bought
    { key: 'solar_only', label: 'load_mode_sem', help: 'load_mode_help_sem' },
    { key: 'solar_battery', label: 'load_mode_sem_battery', help: 'load_mode_help_sem_battery' },
];
const PHASES = ['unknown', 'L1', 'L2', 'L3', '3ph'];
const DOMAIN = 'solar_energy_management';
const BOOST_MINUTES = [30, 60, 120];

/** (#1354) ONE mode control: the four modes (who runs it), then the one-off
 *  line — while a Boost or a pause runs: until when, and Back; while SEM runs
 *  it: Boost for 30 / 60 / 120 min (one tap starts it); otherwise what the
 *  mode means. "Normal" used to sit beside these and wrote mode Off. */
function modeControl(card, row, dis, helpKey) {
    const t = (k) => card._t(k);
    const tf = (k, p) => card._tf(k, p);
    const id = row.id;
    const merged = row.mergedMode;
    const semRuns = merged === 'solar_only' || merged === 'solar_battery';
    const seg = card._seg(MODES.map((m) => ({ key: m.key, label: t(m.label) })), merged, async (key) => {
        if (key === merged) return;
        // a running one-off ends first, so the new mode is what happens next
        if (row.override && !await card._callService(DOMAIN, 'plan_override_clear', { device_id: id })) return;
        for (const w of modeWrites(row, key)) card._dev(id, w.property, w.value);
    }, { disabled: dis });
    let line;
    if (row.override) {
        const back = card._val(t('next_back'), () => card._callService(DOMAIN, 'plan_override_clear', { device_id: id }), { disabled: dis });
        const key = row.override.action === 'skip' ? 'next_load_paused_until' : 'next_boost_until';
        line = html`<div class="modehelp">${tf(key, { time: row.override.until || '—' })} · ${back}</div>`;
    } else if (semRuns) {
        const minSeg = card._seg(BOOST_MINUTES.map((m) => ({ key: m, label: tf('next_n_min', { n: m }) })), null,
            (m) => card._callService(DOMAIN, 'plan_override', { device_id: id, action: 'force', minutes: m }),
            { disabled: dis, small: true });
        line = html`<div class="modehelp">${helpKey ? html`${t(helpKey)} ` : nothing}${t('next_boost_for')} ${minSeg}</div>`;
    } else {
        line = helpKey ? html`<div class="modehelp">${t(helpKey)}</div>` : nothing;
    }
    return html`${seg}${line}`;
}

function hours(min) {
    const h = (Number(min) || 0) / 60;
    return h % 1 === 0 ? String(h) : h.toFixed(1);
}

function phaseLabel(card, p) {
    if (!p || p === 'unknown') return card._t('load_phase_unknown');
    return p === '3ph' ? card._t('load_phase_3ph') : p;
}

/** A thermometer reading in the user's unit (the payload is °C). */
function displayTemp(card, c) {
    if (c == null || !Number.isFinite(Number(c))) return null;
    const unit = card._hass?.config?.unit_system?.temperature || '°C';
    const v = unit === '°F' ? Number(c) * 9 / 5 + 32 : Number(c);
    return (Math.round(v * 10) / 10) + ' ' + unit;
}

export function loadBody(card, row) {
    const t = (k) => card._t(k);
    const tf = (k, p) => card._tf(k, p);
    const dis = card._obs();
    const id = row.id;
    const g = row.goals || {};
    const send = (property, value) => card._dev(id, property, value);
    const kind = row.kind;
    const merged = row.mergedMode;
    // No switch or control mapped: SEM can only measure it, so no mode, goal or permission to offer.
    const measureOnly = !row.hasControlHandle;
    const solar = !measureOnly && (merged === 'solar_only' || merged === 'solar_battery');

    // ── mode ── (#1354) one control: the four modes, then Boost or what the mode means
    const helpKey = modeHelpKey(merged, g) || (MODES.find((m) => m.key === merged) || {}).help;
    const simple = measureOnly ? nothing : modeControl(card, row, dis, helpKey);

    // ── stats ──
    const live = row.powerEntity ? card._powerW(row.powerEntity) : null;
    const on = row.isOn || (live !== null && live > 10) || (measureOnly && live !== null);
    const powerText = on && live !== null ? card._kw(live)
        : (row.rating > 0 ? (row.ratingMeasured ? html`<span class="dim">~${card._kw(row.rating)}</span>` : html`<span class="dim">${card._t('rating_not_measured')}</span>`)
            : (live === null ? '—' : card._kw(live)));
    const minMin = parseFloat(g.daily_min_runtime_min) || 0, maxMin = parseFloat(g.daily_max_runtime_min) || 0;
    // (#1349) with a thermometer the run-time goal asks nothing: Today shows the time run, no goal
    const thermoLeads = !measureOnly && heaterQuestions({ goals: g, comfort: row.comfort }).view === 'band';
    const today = row.progress ? Number(row.progress.runtime_today_min) : null;
    const todayText = today === null || !Number.isFinite(today) ? '—'
        : (solar && !thermoLeads && minMin > 0 ? tf('next_h_of', { h: hours(today), min: hours(minMin) }) : tf('next_h_today', { h: hours(today) }));
    const goalSub = solar && !thermoLeads && minMin > 0 ? tf('next_on_solar_goal', { min: hours(minMin), max: maxMin > 0 ? hours(maxMin) : t('uncapped') }) : '';
    // (#1349) four plain questions: a heater whose thermometer leads ('band'),
    // a load asked for its time ('time'), or a cooling band (earlier layout).
    // (#705) a unit that rides its own setpoint shows the lines SEM uses, in the user's unit
    const inF = (card._hass?.config?.unit_system?.temperature || '°C') === '°F';
    const q = measureOnly ? { view: 'none' } : heaterQuestions({ goals: g, comfort: row.comfort },
        { hasBattery: (card._rowsNow() || []).some((r) => r.type === 'battery'),
          toUnit: (c) => (inF ? Number(c) * 9 / 5 + 32 : Number(c)) });
    const band = q.view === 'band';
    const asked = band || q.view === 'time';
    let third = ['', '', ''];
    // a heat pump keeps its SG-Ready tile: the reading is in the top line
    if (band && kind !== 'heat_pump' && row.comfort && row.comfort.reading_c != null) {
        third = [t('next_comfort'), displayTemp(card, row.comfort.reading_c) || '—', ''];
    } else if (kind === 'hot_water') {
        const stop = g.stop_entity && card._has(g.stop_entity) ? g.stop_entity : null;
        const temp = stop ? card._num(stop) : null;
        const stopVal = card._inline('stop:' + id, String(g.stop_at ?? '—'), () => card._numEdit('stop:' + id, {
            value: g.stop_at, step: 1, onCommit: (v) => send('stop_at', String(v)) }));
        third = [t('next_water'), temp === null ? '—' : card._fmt(temp, 0) + ' ' + (card._unitOf(stop) || '°C'),
            html`${t('next_stop_at')} ${stopVal}`];
    } else if (kind === 'heat_pump') {
        const sg = card._str('sensor.sem_heat_pump_sg_ready_state');
        const boost = card._str('binary_sensor.sem_heat_pump_solar_boost') === 'on';
        third = [t('next_sg_ready'), card._valLabel('heat_pump_mode') || '—',
            (sg ? tf('next_state_n', { n: sg }) : '') + (boost ? ' · ' + t('boost') : '')];
    } else if (row.comfort && row.comfort.reading_c != null) {
        third = [t('next_comfort'), displayTemp(card, row.comfort.reading_c) || '—', ''];
    }
    const stats = card._stats([
        [t('next_power'), powerText, (on && live !== null ? t('next_live') : t('next_rated_lc')) + ' · ' + phaseLabel(card, row.phase)],
        [t('next_today'), todayText, goalSub],
        third,
    ]);
    // with a thermometer the daily run time asks nothing, so no run-time track
    const pct = solar && !band ? goalPct(row.goals, row.progress) : null;

    // ── rows ──
    const rows = [];
    const numVal = (key, text, o) => card._inline(key + ':' + id, text, () => card._numEdit(key + ':' + id, o));
    if (solar) {
        const minVal = numVal('min_h', minMin > 0 ? hours(minMin) + ' h' : t('no_target'), {
            value: minMin / 60, min: 0, max: 24, step: 0.5, unit: 'h', onCommit: (h) => send('daily_min_runtime_min', String(Math.round(h * 60))) });
        const maxVal = numVal('max_h', maxMin > 0 ? hours(maxMin) + ' h' : t('uncapped'), {
            value: maxMin > 0 ? maxMin / 60 : null, min: 0, max: 24, step: 0.5, unit: 'h', onCommit: (h) => send('daily_max_runtime_min', String(h > 0 ? Math.round(h * 60) : 0)) });
        const tUnit = card._hass?.config?.unit_system?.temperature || '°C';
        const buyRow = () => card._row('mdi:cash-check', t('hq_buy'),
            card._seg(q.buyChoices.map((k) => ({ key: k, label: t(BUY_LABEL[k]) })), q.buy,
                (k) => { for (const w of buyWrites(k)) send(w.property, w.value); }, { disabled: dis, small: true }),
            tf(q.buySubKey, { keep: band ? q.keep + ' ' + tUnit : '' })
                + (band && q.buySubBatteryKey ? ' ' + tf(q.buySubBatteryKey, { keep: q.keep + ' ' + tUnit }) : ''));
        if (band) {
            // On a hot-water tank the Configuration tab's Solar target also
            // stops the sun; keep it on the same value so both stops agree.
            const hotWater = !q.cooling && /^hot_water/.test(String(id));
            const solarTarget = hotWater && tUnit === '°C' && card._has('number.sem_hot_water_solar_target')
                ? card._attrs('number.sem_hot_water_solar_target') : null;
            const syncSolar = (v) => {
                if (!hotWater || !Number.isFinite(Number(v))) return;
                const c = tUnit === '°F' ? (Number(v) - 32) * 5 / 9 : Number(v);
                card._callService(DOMAIN, 'set_option', { options: { hot_water_solar_target: Math.round(c * 10) / 10 } });
            };
            const temp = (key, val, onCommit) => numVal(key, val === null || val === undefined ? '—' : val + ' ' + tUnit,
                { value: val, step: 0.5, unit: tUnit, onCommit });
            // Keep at of an anchored unit IS the unit's own setpoint: shown, not edited here
            rows.push(card._row('mdi:thermometer', t('hq_keep'),
                q.keepReadOnly ? html`<span>${q.keep + ' ' + tUnit}</span>`
                    : temp('comfort_target', q.keep, (v) => { send('comfort_target', String(v)); syncSolar(Number(v) + q.offset); }),
                t(q.keys.keepSub) + (q.season ? ' ' + t(q.season) + '.' : '')
                    + (q.keepNoteKey ? ' ' + t(q.keepNoteKey) : '')));
            // (#1349) a cooling band asks the same, turned round: its words
            // and the direction of "sun up to" come from the shared model
            rows.push(card._row(q.cooling ? 'mdi:thermometer-alert' : 'mdi:snowflake-alert', t(q.keys.floor),
                temp('comfort_limit', q.floor, (v) => { for (const w of limitWrites(q, v).writes) send(w.property, w.value); }), t(q.keys.floorSub)));
            rows.push(card._row('mdi:white-balance-sunny', t(q.keys.sunMax),
                temp('sun_max', q.sunMax, (v) => {
                    const res = sunMaxWrites({ id, keep: q.keep, cooling: q.cooling }, v, solarTarget);
                    if (res.error) { card._showError(new Error(tf(res.error, res.params))); return; }
                    for (const w of res.writes) send(w.property, w.value);
                    if (res.option) syncSolar(res.option.value);
                }), t(q.keys.sunMaxSub)));
            rows.push(buyRow());
        } else if (q.view === 'time') {
            rows.push(card._row('mdi:flag-outline', t('hq_run_each_day'),
                card._sentence(t('next_goal_value'), { min: minVal, max: maxVal }), t('hq_run_each_day_sub')));
            rows.push(buyRow());
        } else {
            const src = overnightSource(g);
            const srcVal = card._inline('ov:' + id, t('overnight_' + src), () => card._selEdit('ov:' + id, {
                value: src, options: ['off', 'battery', 'grid'].map((s) => ({ key: s, label: t('overnight_' + s) })),
                onCommit: (s) => { for (const w of overnightWrites(s)) send(w.property, w.value); } }));
            rows.push(card._row('mdi:flag-outline', t('next_goal'), card._sentence(t('next_goal_value'), { min: minVal, max: maxVal }),
                card._sentence(t('next_finish_overnight'), { src: srcVal })));
        }
        const bounds = antiCycleBounds(card._attrs('sensor.sem_controllable_devices_count'));
        const anti = (key, eff) => numVal(key, g[key] != null && g[key] !== '' ? String(g[key]) : antiCyclePlaceholder(g, eff), {
            value: g[key], min: bounds ? Math.max(1, bounds.min) : 1, max: bounds ? bounds.max : undefined, step: 1,
            onCommit: (v) => { const x = antiCycleValue(String(v), bounds); if (x != null) send(key, String(x)); } });
        rows.push(card._row('mdi:timer-outline', t('next_min_run_pause'),
            html`${anti('min_on_time_min', 'min_on_effective_min')} / ${anti('min_off_time_min', 'min_off_effective_min')} ${t('minutes_short')}`,
            t('next_anti_cycle_sub'), { more: asked }));
    }
    if (measureOnly) {
        const phaseOnly = card._inline('ph:' + id, phaseLabel(card, row.phase), () => card._selEdit('ph:' + id, {
            value: row.phase, options: PHASES.map((p) => ({ key: p, label: phaseLabel(card, p) })), onCommit: (p) => send('phase', p) }));
        rows.push(card._row('mdi:sine-wave', t('next_phase'), phaseOnly, t('next_phase_sub')));
        return html`
            <div class="modehelp">${t('next_measure_only')} ${card._val(t('configure'), () => card._showConfigureModal(id, row.name), { disabled: dis })}</div>
            ${stats}
            <div class="rows">${rows}</div>`;
    }
    const others = (card._rowsNow() || []).filter((r) => r.id !== id && r.type !== 'battery');
    const parent = row.dependsOn[0] || '';
    const parentRow = others.find((r) => r.id === parent);
    const reqVal = card._inline('dep:' + id, parentRow ? parentRow.name : (parent || t('action_none')), () => card._selEdit('dep:' + id, {
        value: parent, options: [{ key: '', label: t('action_none') }, ...others.map((r) => ({ key: r.id, label: r.name }))],
        onCommit: (v) => send('depends_on', v) }));
    const blocked = row.blockedBy ? (others.find((r) => r.id === row.blockedBy) || {}).name || row.blockedBy : '';
    rows.push(card._row('mdi:link-variant', t('requires'), reqVal, blocked ? tf('next_st_waiting_for', { parent: blocked }) : t('next_requires_sub'),
        { more: asked && !parent && !blocked }));
    const phaseVal = card._inline('ph:' + id, phaseLabel(card, row.phase), () => card._selEdit('ph:' + id, {
        value: row.phase, options: PHASES.map((p) => ({ key: p, label: phaseLabel(card, p) })), onCommit: (p) => send('phase', p) }));
    rows.push(card._row('mdi:sine-wave', t('next_phase'), phaseVal, t('next_phase_sub'), { more: asked }));
    // Stop condition: a sensor that ends the day's run once it reaches a value (water temperature, a car's %).
    const stopEnt = g.stop_entity || '';
    const stopPick = card._inline('stopent:' + id, stopEnt ? card._name(stopEnt) : t('action_none'), () => card._entEdit('stopent:' + id, {
        value: stopEnt, domains: ['sensor', 'input_number', 'number'], onCommit: (v) => send('stop_entity', v) }));
    const stopAt = stopEnt ? numVal('stopat', g.stop_at > 0 ? String(g.stop_at) + (card._unitOf(stopEnt) ? ' ' + card._unitOf(stopEnt) : '') : '—', {
        value: g.stop_at || null, step: 1, onCommit: (v) => send('stop_at', String(v)) }) : '';
    const stopNow = stopEnt && card._has(stopEnt) ? card._str(stopEnt) + (card._unitOf(stopEnt) ? ' ' + card._unitOf(stopEnt) : '') : '';
    // (#1354) in Off and Peak only SEM does not run the load: its stop, thermometer,
    // Legionella and comfort rows would change nothing, so they are not shown
    const runs = loadRunsBySem(merged);
    if (runs) rows.push(card._row('mdi:flag-checkered', t('next_stop_when'), stopPick,
        stopEnt ? html`${t('next_stop_at')} ${stopAt}${stopNow ? ' · ' + tf('next_now_value', { v: stopNow }) : ''}` : t('next_stop_when_sub'),
        { more: band || !stopEnt }));
    // Own thermometer for the comfort band; without one SEM reads the device's own temperature.
    const thermo = g.comfort_entity || '';
    if (runs) rows.push(card._row('mdi:thermometer-lines', t('next_own_thermometer'),
        card._inline('thermo:' + id, thermo ? card._name(thermo) : t('next_thermo_device'), () => card._entEdit('thermo:' + id, {
            value: thermo, domains: ['sensor'], filter: isTemperature, onCommit: (v) => send('comfort_entity', v) })),
        t('next_own_thermometer_sub'), { more: band || !thermo }));
    if (runs && kind === 'hot_water' && card._has('number.sem_legionella_target_temp')) {
        const lid = 'number.sem_legionella_target_temp', iid = 'number.sem_legionella_interval_hours';
        rows.push(card._row('mdi:bacteria-outline', t('next_legionella'),
            card._val(card._fmt(card._num(lid), 0) + ' ' + (card._unitOf(lid) || '°C'), () => card._moreInfo(lid)),
            card._has(iid) ? card._val(tf('next_every_h', { h: card._fmt(card._num(iid), 0) }), () => card._moreInfo(iid)) : '',
            { more: band }));
    }
    const target = parseFloat(g.comfort_target) || 0, offset = parseFloat(g.comfort_offset) || 0, limit = parseFloat(g.comfort_limit) || 0;
    const engaged = target > 0 && limit > 0;
    const tUnit = card._hass?.config?.unit_system?.temperature || '°C';
    const cNum = (key, val) => numVal(key, val ? val + ' ' + tUnit : '—', { value: val || null, step: 0.5, unit: tUnit, onCommit: (v) => send(key, String(v)) });
    // the four questions replace this row where they are shown
    if (runs && !(band && solar)) rows.push(card._row('mdi:thermometer', t('next_comfort'), displayTemp(card, row.comfort && row.comfort.reading_c) || '—',
        html`${card._sentence(t('next_keep_sentence'), { target: cNum('comfort_target', target), limit: cNum('comfort_limit', limit), offset: cNum('comfort_offset', offset) })}<div class="modehelp">${t(row.comfort && row.comfort.may_buy === false ? 'next_keep_sub_no_buy' : 'next_keep_sub')}</div>`,
        { more: q.view === 'time' || (!engaged && !(row.comfort && row.comfort.reading_c != null)) }));
    if (kind === 'heat_pump') {
        // (#1321) one visible line: what a kWh of heat costs now, and the next planned run
        const coh = card._has('sensor.sem_heat_pump_cost_of_heat') ? card._num('sensor.sem_heat_pump_cost_of_heat') : null;
        const nextAt = card._plannedAt('load:' + row.id, 'comfort:' + row.id);
        rows.push(card._row('mdi:heat-pump-outline', t('next_cost_of_heat'),
            coh === null ? '—' : tf('next_per_kwh_heat', { v: card._money(coh) }),
            nextAt ? tf('next_hp_next_run', { time: nextAt }) : t('next_nothing_planned')));
        // (#1081) the COP by outdoor temperature: what it is now, then the
        // 2–3 points as text "−7:2.5, 12:4.2"; empty = one fixed COP
        if (Object.prototype.hasOwnProperty.call(g, 'cop_curve')) {
            rows.push(copCurveRow(card, row, g, send));
        }
        const offId = 'number.sem_heat_pump_boost_offset';
        if (card._has(offId)) {
            rows.push(card._row('mdi:tune-vertical', t('next_relay_values'),
                card._val(tf('next_boost_offset', { v: '+' + card._fmt(card._num(offId), 1) + ' ' + (card._unitOf(offId) || '°C') }), () => card._moreInfo(offId)), '', { more: true }));
        }
    } else {
        const rate = parseFloat(g.tariff_rate) || 0;
        rows.push(card._row('mdi:cash-multiple', t('next_device_tariff'),
            numVal('rate', rate > 0 ? card._money(rate) : t('next_house_tariff'), { value: rate || null, min: 0, step: 0.001, onCommit: (v) => send('tariff_rate', String(v > 0 ? v : 0)) }),
            '', { more: true }));
    }
    rows.push(card._row('mdi:toggle-switch-outline', t('next_may_switch'),
        card._val(row.isControllable ? t('next_on') : t('next_off'), () => send('controllable', String(!row.isControllable)), { disabled: dis }),
        html`${t('critical')}: ${card._val(row.isCritical ? t('next_yes') : t('next_no'), () => send('critical', String(!row.isCritical)), { disabled: dis })}${row.controlEntity ? ' · ' + row.controlEntity : ''} · ${card._val(t('configure'), () => card._showConfigureModal(id, row.name))}`,
        { more: true }));

    return html`
        ${saysLine(card, row)}
        ${band && solar ? bandBar(card, q, row) : nothing}
        ${simple}
        ${stats}
        ${pct === null ? nothing : html`<div style="margin:6px 0 10px">${card._track(pct, 'var(--c)')}</div>`}
        <div class="rows">${rows}</div>`;
}

/** (#1081) The heat pump's COP row under More: the COP now (and the
 *  outdoor °C with a curve), then the curve as text to edit. A curve that
 *  cannot be read is not sent; an empty box clears it. */
export function copCurveRow(card, row, g, send) {
    const t = (k) => card._t(k);
    const tf = (k, p) => card._tf(k, p);
    const now = row.id === 'heat_pump'
        ? heatCostNow(card._hass?.states?.['sensor.sem_heat_pump_cost_of_heat']) : null;
    const nowText = !now ? ''
        : (now.outdoorC !== null
            ? tf('hp_cop_now_at', { cop: card._fmt(now.cop, 1), temp: card._fmt(now.outdoorC, 0) + ' °C' })
            : tf('hp_cop_now', { cop: card._fmt(now.cop, 1) }));
    const curve = parseCopCurve(g.cop_curve);
    const text = curve ? formatCopCurve(curve) : t('next_cop_fixed');
    const key = 'cop:' + row.id;
    const val = card._inline(key, text, () => card._textEdit(key, {
        value: curve ? formatCopCurve(curve) : '',
        placeholder: '-7:2.5, 2:3.2, 12:4.2',
        onCommit: (v) => {
            const raw = String(v || '').trim();
            if (raw === '') { send('cop_curve', ''); return; }
            const c = parseCopCurve(raw);
            if (c) send('cop_curve', formatCopCurve(c));
        },
    }));
    const sub = [nowText, t('hp_cop_curve_hint')].filter(Boolean).join(' · ');
    return card._row('mdi:thermometer-lines', t('hp_cop_curve_section'), val, sub, { more: true });
}

/**
 * (#1321) The first line of an open load: what it does now and what comes
 * next (the pill's words), then the engine's reason as a sentence when it
 * has one. Nothing for a load the engine has not decided yet.
 */
export function saysLine(card, row) {
    if (!row.intent && !(row.comfort && row.comfort.keep_c != null)) return nothing;
    const pill = statePill(row, card._live(row));
    const text = card._pillText(pill);
    const code = row.intent && row.intent.code;
    // The engine's sentence describes the last switch ("…so it turns off").
    // A line that already says what comes NEXT does not get it on top.
    const sentence = code && !pill.next ? plainReason({ reason_code: code }, (k) => card._t(k)) : null;
    // (#1349) the heater's own line under it: sun before a planned hour is
    // free; a load SEM buys nothing for says so
    const sub = heaterSub(pill, row, { fmtTemp: (c) => displayTemp(card, c) });
    const hint = sub ? card._tf(sub.key, sub.params) : '';
    const reading = row.comfort && row.comfort.keep_c != null && pill.key !== 'hq_st_warm' && pill.key !== 'hq_st_cool'
        ? displayTemp(card, row.comfort.reading_c) : null;
    const now = reading ? card._tf('hq_now', { reading }) + ' ' : '';
    const lead = now + text.charAt(0).toUpperCase() + text.slice(1) + '.';
    const tail = [sentence, hint].filter(Boolean).map((x) => ' ' + x).join('');
    return html`<p class="sent says"><span class="val">${lead}</span>${tail}</p>`;
}

/**
 * (#1349) One bar for the band: never colder than · keep it at · sun up to,
 * and a marker for now. A cooling band is the same bar turned round: the
 * limit on the warm side, the sun's range below Keep at. Temperatures in
 * the user's unit, as typed.
 */
export function bandBar(card, q, row) {
    const lo = Math.min(q.floor, q.keep, q.sunMax) - 3, hi = Math.max(q.floor, q.keep, q.sunMax) + 3;
    const pct = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
    const unit = card._hass?.config?.unit_system?.temperature || '°C';
    const c = row.comfort ? row.comfort.reading_c : null;
    const now = c == null ? null : (unit === '°F' ? Number(c) * 9 / 5 + 32 : Number(c));
    const tick = (v) => html`<span style="position:absolute;top:-4px;left:${pct(v)}%;width:2px;height:16px;background:var(--primary-text-color,#ddd)"></span>
        <span class="muted" style="position:absolute;top:15px;left:${pct(v)}%;transform:translateX(-50%);font-size:11px;white-space:nowrap">${v} ${unit}</span>`;
    return html`<div style="position:relative;height:8px;border-radius:5px;margin:14px 0 26px;background:var(--divider-color,#333)">
        ${q.cooling
        ? html`<span style="position:absolute;right:0;top:0;height:8px;border-radius:0 5px 5px 0;width:${100 - pct(q.floor)}%;background:#b23c3c"></span>`
        : html`<span style="position:absolute;left:0;top:0;height:8px;border-radius:5px 0 0 5px;width:${pct(q.floor)}%;background:#b23c3c"></span>`}
        <span style="position:absolute;top:0;height:8px;left:${pct(Math.min(q.keep, q.sunMax))}%;width:${Math.abs(pct(q.sunMax) - pct(q.keep))}%;background:#ff9800"></span>
        ${tick(q.floor)}${tick(q.keep)}${tick(q.sunMax)}
        ${now === null ? nothing : html`<span style="position:absolute;top:-11px;left:calc(${pct(now)}% - 6px);width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;border-top:9px solid var(--primary-text-color,#fff)"></span>`}
    </div>`;
}
