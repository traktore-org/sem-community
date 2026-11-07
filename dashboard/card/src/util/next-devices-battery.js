/**
 * (#1321) The Devices screen's battery body: mode, stats, the zone bar
 * with its sentence, and the rows Tonight · Charge pacing · Sell window ·
 * per battery · Evidence · Health. A function of the card; every row
 * exists only when its entity does.
 */

import { html, nothing } from '../base/sem-next-base.js';
import { providerName } from './forecast-evidence.js';
import { zonesModel } from './next-devices.js';

const AUTO_MODES = ['auto', 'self_consumption', 'allow_arbitrage'];
const SPEND = 'sensor.sem_battery_spendable_kwh';

function segKeyOf(mode) {
    if (mode === 'off') return 'off';
    if (mode === 'force_charge') return 'charge';
    if (mode === 'force_discharge') return 'discharge';
    return 'auto';
}

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
    const dis = card._obs();
    const num = card._num.bind(card);

    // ── mode ──
    const modeId = card._has('select.sem_battery_mode') ? 'select.sem_battery_mode' : null;
    const mode = modeId ? card._str(modeId) : '';
    const options = modeId ? (card._attrs(modeId).options || []) : [];
    const autoOpts = options.filter((o) => AUTO_MODES.includes(o));
    const segKey = segKeyOf(mode);
    const segItems = [];
    if (options.includes('off')) segItems.push({ key: 'off', label: t('charge_mode_off') });
    if (autoOpts.length) segItems.push({ key: 'auto', label: t('battery_mode_auto'), icon: autoOpts.length > 1 ? 'mdi:chevron-down' : undefined });
    if (options.includes('force_charge')) segItems.push({ key: 'charge', label: t('next_charge') });
    if (options.includes('force_discharge')) segItems.push({ key: 'discharge', label: t('next_discharge') });
    const pick = (key) => {
        if (!modeId) return;
        const map = { off: 'off', charge: 'force_charge', discharge: 'force_discharge' };
        if (map[key]) card._selectOption(modeId, map[key]);
        else card._selectOption(modeId, autoOpts.includes(card._autoLast) ? card._autoLast : autoOpts[0]);
    };
    const autoSeg = segKey === 'auto' && autoOpts.length > 1 ? card._seg(
        autoOpts.map((o) => ({ key: o, label: t('battery_mode_' + o) || o })), mode,
        (o) => { card._autoLast = o; card._selectOption(modeId, o); }, { small: true, disabled: dis }) : nothing;
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
    const ids = { priority: 'number.sem_battery_priority_soc', buffer: 'number.sem_battery_buffer_soc',
        auto: 'number.sem_battery_auto_start_soc', tonight: 'sensor.sem_battery_dynamic_floor_pct' };
    const z = zonesModel({ soc, priority: num(ids.priority), buffer: num(ids.buffer), autoStart: num(ids.auto), floor: num(ids.tonight) });
    // Two marks closer than 14 % would overprint: the second goes under the bar.
    let lastPct = -99, lastLo = false, anyLo = false;
    const marks = z.marks.map((m) => {
        const lo = (m.pct - lastPct) < 14 && !lastLo;
        lastPct = m.pct; lastLo = lo; anyLo = anyLo || lo;
        return { ...m, lo };
    });
    const zones = z.marks.length || z.cur !== null ? html`<div class="zones ${anyLo ? 'two' : ''}" style="--z1:${z.z1}%;--z2:${z.z2}%">
        ${marks.map((m) => html`<span class="z ${m.lo ? 'lo' : ''}" style="left:${m.pct}%">${t('next_zone_' + m.key)} ${m.value}</span>`)}
        ${z.cur === null ? nothing : html`<span class="cur" style="left:${z.cur}%"></span>`}</div>` : nothing;
    const v = (id, text) => card._val(text, () => card._moreInfo(id));
    const parts = [];
    if (card._has(ids.priority)) parts.push(card._sentence(t('next_bat_sent_fill'), { priority: v(ids.priority, Math.round(num(ids.priority)) + ' %') }));
    const assistId = card._has('switch.sem_battery_may_assist_ev') ? 'switch.sem_battery_may_assist_ev' : null;
    const maxId = card._has('number.sem_battery_assist_max_power') ? 'number.sem_battery_assist_max_power' : null;
    const gateId = card._has('number.sem_battery_assist_min_surplus') ? 'number.sem_battery_assist_min_surplus' : null;
    if (assistId || maxId || gateId) {
        const assistOn = assistId ? card._str(assistId) === 'on' : true;
        const assistVal = assistId ? card._val(assistOn ? t('next_on') : t('next_off'), () => card._toggleSwitch(assistId), { disabled: dis }) : html`${t('next_on')}`;
        parts.push(assistOn
            ? card._sentence(t('next_bat_sent_assist'), {
                max: maxId ? v(maxId, card._kw(num(maxId))) : html`—`,
                gate: gateId ? v(gateId, card._fmt(num(gateId), 0) + ' W') : html`—`,
                assist: assistVal })
            : card._sentence(t('next_bat_sent_no_assist'), { assist: assistVal }));
    }
    if (card._has(ids.tonight)) parts.push(card._sentence(t('next_bat_sent_floor'), { floor: v(ids.tonight, Math.round(num(ids.tonight)) + ' %') }));
    const sentence = parts.length ? html`<p class="sent">${parts.map((p, i) => html`${i ? ' ' : ''}${p}`)}</p>` : nothing;

    // ── rows ──
    const rows = [];
    const sa = card._attrs(SPEND);
    if (card._has(SPEND) && sa.phase) {
        const need = Number(sa.overnight_need_kwh), refill = Number(sa.expected_refill_kwh);
        const nights = Number(sa.nights_sealed), spend = num(SPEND);
        const subs = [];
        if (Number.isFinite(refill)) subs.push(tf('next_refill', { kwh: card._fmt(refill, 1) }));
        if (spend !== null) subs.push(tf('next_spendable_kwh', { kwh: card._fmt(spend, 1) }));
        if (Number.isFinite(nights)) subs.push(tf('next_nights_learned', { n: nights }));
        const rebuild = card._val(t('rebuild_nights'), () => card._svc('backfill_battery_nights', { days: 365 }), { disabled: dis });
        rows.push(card._row('mdi:weather-night', t('tonight'),
            (t('planning_phase_' + sa.phase) || sa.phase) + (Number.isFinite(need) ? ' · ' + tf('next_needs_kwh', { kwh: card._fmt(need, 1) }) : ''),
            html`${subs.join(' · ')}${sa.phase === 'learning' ? html`${subs.length ? ' · ' : ''}${rebuild}` : ''}`));
    }
    const paceId = 'sensor.sem_battery_charge_pacing';
    const paceSw = card._has('switch.sem_battery_charge_pacing_enabled') ? 'switch.sem_battery_charge_pacing_enabled' : null;
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
        const sw = paceSw ? card._val(card._str(paceSw) === 'on' ? t('next_on') : t('next_off'), () => card._toggleSwitch(paceSw), { disabled: dis }) : '';
        rows.push(card._row('mdi:speedometer', t('charge_pacing'), value, html`${capText}${capText && sw ? ' · ' : ''}${sw}`));
    }
    const sellSw = card._has('switch.sem_battery_may_export') ? 'switch.sem_battery_may_export' : null;
    const st = sa.battery_sell_state && sa.battery_sell_state !== 'none' ? sa.battery_sell_state : '';
    if (sellSw || st) {
        const until = sa.battery_sell_until ? card._hhmm(sa.battery_sell_until) : '';
        const value = st === 'selling' ? t('spend_selling') + (until ? ' · ' + t('spend_until') + ' ' + until : '')
            : st === 'scheduled' ? t('spend_sell_planned') + (until ? ' · ' + until : '') : t('next_none');
        const rate = num('sensor.sem_tariff_current_export_rate');
        const sw = sellSw ? html`${t('next_may_export')}: ${card._val(card._str(sellSw) === 'on' ? t('next_on') : t('next_off'), () => card._toggleSwitch(sellSw), { disabled: dis })}` : '';
        rows.push(card._row('mdi:transmission-tower-export', t('next_sell_window'), value,
            html`${rate === null ? '' : tf('next_export_rate', { rate: card._fmt(rate, 2) })}${rate !== null && sellSw ? ' · ' : ''}${sw}`));
    }
    const bats = card._batteries || [];
    if (bats.length) {
        const vals = bats.map((bid, i) => {
            const id = 'select.sem_battery_' + bid + '_mode';
            const m = card._str(id);
            return card._inline('bmode:' + bid, t('battery_mode_' + m) || m || '—', () => card._selEdit('bmode:' + bid, {
                value: m, options: (card._attrs(id).options || []).map((o) => ({ key: o, label: t('battery_mode_' + o) || o })),
                onCommit: (o) => card._selectOption(id, o) }));
        });
        const reserves = bats.map((bid) => {
            const id = 'number.sem_battery_' + bid + '_reserve_soc';
            return card._has(id) ? card._val(card._fmt(num(id), 0) + ' %', () => card._moreInfo(id)) : null;
        }).filter(Boolean);
        rows.push(card._row('mdi:swap-vertical', bats.map((_, i) => tf('next_battery_n', { n: i + 1 })).join(' · '),
            html`${vals.map((x, i) => html`${i ? ' · ' : ''}${x}`)}`,
            reserves.length ? html`${t('next_reserve')} ${reserves.map((x, i) => html`${i ? ' · ' : ''}${x}`)}` : ''));
    }
    const src = card._str('sensor.sem_forecast_source');
    const d1 = card._has('sensor.sem_forecast_trust_d1') ? num('sensor.sem_forecast_trust_d1') : (Number.isFinite(Number(sa.forecast_trust_d1)) ? Number(sa.forecast_trust_d1) * 100 : null);
    const d2 = card._has('sensor.sem_forecast_trust_d2') ? num('sensor.sem_forecast_trust_d2') : (Number.isFinite(Number(sa.forecast_trust_d2)) ? Number(sa.forecast_trust_d2) * 100 : null);
    if (src || d1 !== null || d2 !== null) {
        const pct = (x) => (x === null ? t('learning') : Math.round(x) + ' %');
        rows.push(card._row('mdi:check-decagram-outline', t('next_evidence'),
            (providerName(src) || t('next_src_forecast')) + ' · ' + pct(d1) + ' / ' + pct(d2),
            html`${t('next_trusted_sub')}${card._has(SPEND) ? html` · ${card._val(t('rebuild_nights'), () => card._svc('backfill_battery_nights', { days: 365 }), { disabled: dis })}` : ''}`, { more: true }));
    }
    const health = num('sensor.sem_battery_health_score'), cycles = num('sensor.sem_battery_cycles_estimated');
    const temp = num('sensor.sem_battery_temperature');
    const measured = num('sensor.sem_battery_measured_capacity_kwh'), nameplate = num('sensor.sem_diag_battery_capacity');
    const drift = num('sensor.sem_battery_capacity_drift_pct');
    if ([health, cycles, temp, measured, drift].some((x) => x !== null)) {
        const top = [];
        if (health !== null) top.push(Math.round(health) + ' %');
        if (cycles !== null) top.push(tf('next_cycles', { n: Math.round(cycles) }));
        const sub = [];
        if (temp !== null) sub.push(card._fmt(temp, 0) + ' ' + (card._unitOf('sensor.sem_battery_temperature') || '°C'));
        if (measured !== null) sub.push(nameplate ? tf('next_measured_of', { cap: card._fmt(measured, 1), nameplate: card._fmt(nameplate, 1) }) : card._kwh(measured));
        if (drift !== null) sub.push(tf('next_drift', { pct: (drift > 0 ? '+' : '') + card._fmt(drift, 0) }));
        rows.push(card._row('mdi:heart-pulse', t('health'), top.join(' · ') || '—', sub.join(' · '), { more: true }));
    }

    return html`
        ${segItems.length ? card._seg(segItems, segKey, pick, { disabled: dis }) : nothing}
        ${autoSeg !== nothing ? html`<div style="margin-top:6px">${autoSeg}</div>` : nothing}
        ${hint ? html`<div class="modehelp">${hint}</div>` : nothing}
        ${card._stats(stats)}
        ${zones}
        ${sentence}
        ${rows.length ? html`<div class="rows" style="margin-top:6px">${rows}</div>` : nothing}`;
}
