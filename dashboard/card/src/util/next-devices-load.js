/**
 * (#1321) The Devices screen's load body (a boiler, a heat pump, a pump,
 * any switched load): the four-way mode, stats, the runtime track and
 * the rows Goal · Min run / pause · Requires · Phase · Legionella ·
 * Comfort · Device tariff · SEM may switch it. Every write is one
 * update_device_config call (the properties the backend accepts).
 */

import { html, nothing } from '../base/sem-next-base.js';
import { antiCyclePlaceholder, antiCycleBounds, antiCycleValue } from './load-sections.js';
import { goalPct, modeWrites, overnightSource, overnightWrites } from './next-devices.js';

const MODES = [
    { key: 'off', label: 'off', help: 'help_mode_off' },
    { key: 'peak_only', label: 'peak_only', help: 'help_mode_peak_only' },
    { key: 'solar_only', label: 'mode_solar_only', help: 'help_mode_surplus' },
    { key: 'solar_battery', label: 'mode_solar_battery', help: 'battery_overnight_hint' },
];
const PHASES = ['unknown', 'L1', 'L2', 'L3', '3ph'];

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

    // ── mode ──
    const seg = card._seg(MODES.map((m) => ({ key: m.key, label: t(m.label) })), merged,
        (key) => { for (const w of modeWrites(row, key)) send(w.property, w.value); }, { disabled: dis });
    const helpKey = (MODES.find((m) => m.key === merged) || {}).help;

    // ── stats ──
    const live = row.powerEntity ? card._powerW(row.powerEntity) : null;
    const on = row.isOn || (live !== null && live > 10) || (measureOnly && live !== null);
    const powerText = on && live !== null ? card._kw(live)
        : (row.rating > 0 ? (row.ratingMeasured ? html`<span class="dim">~${card._kw(row.rating)}</span>` : html`<span class="dim">${card._t('rating_not_measured')}</span>`)
            : (live === null ? '—' : card._kw(live)));
    const minMin = parseFloat(g.daily_min_runtime_min) || 0, maxMin = parseFloat(g.daily_max_runtime_min) || 0;
    const today = row.progress ? Number(row.progress.runtime_today_min) : null;
    const todayText = today === null || !Number.isFinite(today) ? '—'
        : (solar && minMin > 0 ? tf('next_h_of', { h: hours(today), min: hours(minMin) }) : tf('next_h_today', { h: hours(today) }));
    const goalSub = solar && minMin > 0 ? tf('next_on_solar_goal', { min: hours(minMin), max: maxMin > 0 ? hours(maxMin) : t('uncapped') }) : '';
    let third = ['', '', ''];
    if (kind === 'hot_water') {
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
    const pct = solar ? goalPct(row.goals, row.progress) : null;

    // ── rows ──
    const rows = [];
    const numVal = (key, text, o) => card._inline(key + ':' + id, text, () => card._numEdit(key + ':' + id, o));
    if (solar) {
        const minVal = numVal('min_h', minMin > 0 ? hours(minMin) + ' h' : t('no_target'), {
            value: minMin / 60, min: 0, max: 24, step: 0.5, unit: 'h', onCommit: (h) => send('daily_min_runtime_min', String(Math.round(h * 60))) });
        const maxVal = numVal('max_h', maxMin > 0 ? hours(maxMin) + ' h' : t('uncapped'), {
            value: maxMin > 0 ? maxMin / 60 : null, min: 0, max: 24, step: 0.5, unit: 'h', onCommit: (h) => send('daily_max_runtime_min', String(h > 0 ? Math.round(h * 60) : 0)) });
        const src = overnightSource(g);
        const srcVal = card._inline('ov:' + id, t('overnight_' + src), () => card._selEdit('ov:' + id, {
            value: src, options: ['off', 'battery', 'grid'].map((s) => ({ key: s, label: t('overnight_' + s) })),
            onCommit: (s) => { for (const w of overnightWrites(s)) send(w.property, w.value); } }));
        rows.push(card._row('mdi:flag-outline', t('next_goal'), card._sentence(t('next_goal_value'), { min: minVal, max: maxVal }),
            card._sentence(t('next_finish_overnight'), { src: srcVal })));
        const bounds = antiCycleBounds(card._attrs('sensor.sem_controllable_devices_count'));
        const anti = (key, eff) => numVal(key, g[key] != null && g[key] !== '' ? String(g[key]) : antiCyclePlaceholder(g, eff), {
            value: g[key], min: bounds ? Math.max(1, bounds.min) : 1, max: bounds ? bounds.max : undefined, step: 1,
            onCommit: (v) => { const x = antiCycleValue(String(v), bounds); if (x != null) send(key, String(x)); } });
        rows.push(card._row('mdi:timer-outline', t('next_min_run_pause'),
            html`${anti('min_on_time_min', 'min_on_effective_min')} / ${anti('min_off_time_min', 'min_off_effective_min')} ${t('minutes_short')}`,
            t('next_anti_cycle_sub')));
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
    rows.push(card._row('mdi:link-variant', t('requires'), reqVal, blocked ? tf('next_st_waiting_for', { parent: blocked }) : t('next_requires_sub')));
    const phaseVal = card._inline('ph:' + id, phaseLabel(card, row.phase), () => card._selEdit('ph:' + id, {
        value: row.phase, options: PHASES.map((p) => ({ key: p, label: phaseLabel(card, p) })), onCommit: (p) => send('phase', p) }));
    rows.push(card._row('mdi:sine-wave', t('next_phase'), phaseVal, t('next_phase_sub')));
    if (kind === 'hot_water' && card._has('number.sem_legionella_target_temp')) {
        const lid = 'number.sem_legionella_target_temp', iid = 'number.sem_legionella_interval_hours';
        rows.push(card._row('mdi:bacteria-outline', t('next_legionella'),
            card._val(card._fmt(card._num(lid), 0) + ' ' + (card._unitOf(lid) || '°C'), () => card._moreInfo(lid)),
            card._has(iid) ? card._val(tf('next_every_h', { h: card._fmt(card._num(iid), 0) }), () => card._moreInfo(iid)) : ''));
    }
    const target = parseFloat(g.comfort_target) || 0, offset = parseFloat(g.comfort_offset) || 0, limit = parseFloat(g.comfort_limit) || 0;
    const engaged = target > 0 && limit > 0;
    const tUnit = card._hass?.config?.unit_system?.temperature || '°C';
    const cNum = (key, val) => numVal(key, val ? val + ' ' + tUnit : '—', { value: val || null, step: 0.5, unit: tUnit, onCommit: (v) => send(key, String(v)) });
    rows.push(card._row('mdi:thermometer', t('next_comfort'), displayTemp(card, row.comfort && row.comfort.reading_c) || '—',
        card._sentence(t('next_keep_limit_pre'), { target: cNum('comfort_target', target), limit: cNum('comfort_limit', limit), offset: cNum('comfort_offset', offset) }),
        { more: !engaged && !(row.comfort && row.comfort.reading_c != null) }));
    if (kind === 'heat_pump') {
        rows.push(card._row('mdi:cash-multiple', t('next_device_tariff'), card._has('sensor.sem_heat_pump_cost_of_heat') ? card._money(card._num('sensor.sem_heat_pump_cost_of_heat')) : '—', t('device_tariff_heat_pump'), { more: true }));
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
        ${seg}
        ${helpKey ? html`<div class="modehelp">${t(helpKey)}</div>` : nothing}
        ${stats}
        ${pct === null ? nothing : html`<div style="margin:6px 0 10px">${card._track(pct, 'var(--c)')}</div>`}
        <div class="rows">${rows}</div>`;
}
