/**
 * (#1321) SEM Next: the Setup check and the Detected-hardware review, in
 * the new dashboard. Same reads and writes as the classic Setup card
 * (sem-config-card.js _renderOverview / _renderSourceCheck /
 * _renderDetectedHardware): get_config to read the options, set_option to
 * save a proposal, chargerAddPlan for "Add this charger", flip_*_sign for a
 * wrong direction. The System screen mounts it with kind 'check' or
 * 'hardware' and listens for 'sem-next-close' (detail.goto names the setup
 * item the user wants to set up next, when they picked one).
 *
 * Not a dashboard card: registered with customElements.define only.
 */
import { SEMNextBase, html, css, nothing, nextCss } from '../base/sem-next-base.js';
import { setupItems } from '../util/next-settings.js';
import { sourceCheckRows, fmtWatts } from '../util/source-check.js';
import {
    chargerAddPlan, detectRowLabelKey, nearMissAction, proposalWrite, watchOnlyHelpKey, writeIsSaved,
} from '../util/detect-rows.js';

const DOMAIN = 'solar_energy_management';
const REPORT = 'sensor.sem_diag_charger_control';

// ── pure model (node-tested) ──

/** The Setup check: the item list, its progress, and what SEM reads now. */
export function checkModel(states, options) {
    const items = setupItems(states || {}, options || {});
    const counted = items.filter((i) => !i.optional);
    const done = counted.filter((i) => i.done).length;
    const total = counted.length;
    const sources = sourceCheckRows((suffix) => (states || {})['sensor.sem_' + suffix]);
    return {
        items,
        done, total,
        pct: total ? Math.round((done / total) * 100) : 100,
        allDone: done === total,
        sources,
        hasBattery: sources.some((r) => r.key === 'battery'),
    };
}

/** Why a proposal offers no button: a key + fill values, or the backend's own text. */
export function whyNoButton(p) {
    switch (p && p.action) {
        case 'observe_only': return { key: 'config_proposed_observe_only' };
        case 'not_loaded': return { key: 'config_proposed_not_loaded' };
        case 'no_unit': return { key: 'config_proposed_no_unit', vars: { wanted: p.unit_wanted || '' } };
        case 'unit_mismatch': return { key: 'config_proposed_unit_mismatch', vars: { seen: p.unit_seen || '?', wanted: p.unit_wanted || '' } };
        case 'options_unmapped': return { key: 'config_proposed_options_unmapped',
            vars: { missing: (p.values_missing || []).join(', '), options: (p.options || []).join(', ') } };
        case 'pair_incomplete': return { key: 'config_proposed_pair_incomplete', vars: { missing: (p.missing_role || []).join(', ') } };
        case 'pair_blocked': return { key: 'config_proposed_pair_blocked', vars: { missing: (p.missing_role || []).join(', ') } };
        case 'per_charger': return { key: 'config_proposed_per_charger' };
        case 'set_option': return p.reason ? { text: p.reason } : null;
        default: return p && p.reason ? { text: p.reason } : null;
    }
}

/** One proposed role: what it names, what a click saves, and the runners-up. */
export function proposalModel(role, p, options) {
    const write = p.action === 'set_option' ? proposalWrite(p, p.entity, options) : null;
    const alts = (p.alternatives || []).filter((a) => a && a.entity).map((a) => {
        const ok = !a.action || a.action === 'set_option';
        const altWrite = p.action === 'set_option' && ok ? proposalWrite(p, a.entity, options) : null;
        return {
            entity: a.entity, matchedKey: a.matched_key || '',
            write: altWrite, saved: writeIsSaved(altWrite, options),
            why: p.action === 'set_option' && !ok ? whyNoButton(a) : null,
        };
    });
    const saved = writeIsSaved(write, options);
    return {
        role,
        what: p.entity || p.service || (p.candidates || []).join(' / ') || '',
        matchedKey: p.matched_key || '',
        write: write && !saved ? write : null,
        saved,
        why: whyNoButton(p),
        alts,
    };
}

/** A prefilled issue for hardware no role matched (classic _reportNearMissUrl). */
export function reportNearMissUrl(m) {
    if (nearMissAction(m) !== 'report') return '';
    const tick = String.fromCharCode(96);
    const code = (s) => tick + s + tick;
    const ents = (m.entities || []).map((e) => '- ' + code(e.entity) + ' (' + e.domain + (e.device_class ? '/' + e.device_class : '') + ')').join('\n');
    const name = m.roster?.name ? m.roster.name + ' (' + code(m.platform) + ')' : code(m.platform);
    const body = [
        '**Detected hardware — no role matched**', '',
        'Integration: ' + name,
        m.roster?.installs ? 'Installs (HA analytics): ' + m.roster.installs : '',
        '', 'Entities on this device:', ents, '',
        'What the device is and which entity does what:', '(please fill in)',
    ].filter(Boolean).join('\n');
    return 'https://github.com/traktore-org/sem-community/issues/new?labels=enhancement'
        + '&title=' + encodeURIComponent('Detected hardware: ' + m.platform + ' — no role matched')
        + '&body=' + encodeURIComponent(body);
}

/** The detection report as rows. `chargerIds` = every charger id SEM knows (options + runtime). */
export function hardwareModel(report, options, chargerIds) {
    if (!report) return null;
    const opts = options || {};
    const ids = chargerIds || [];
    const count = (opts.ev_chargers || []).length;
    const census = report.census || {};
    const named = census.unknown_energy_domains_named || [];
    const describe = (dom) => {
        const d = named.find((x) => x && x.domain === dom);
        return d && d.name ? { name: d.name, installs: d.installs || 0 } : { name: dom, installs: 0 };
    };
    const misses = (report.near_misses || []).map((m) => {
        const plan = m.suggested_charger?.id ? chargerAddPlan(m.suggested_charger, ids, count) : null;
        const action = m.suggested_charger?.id ? 'add' : nearMissAction(m);
        return {
            name: m.roster?.name || m.platform,
            labelKey: detectRowLabelKey(m),
            roles: (m.charger_roles || []).join(', '),
            entities: (m.entities || []).map((e) => e.entity),
            action,
            plan,
            suggested: m.suggested_charger || null,
            watchKey: action === 'watch' ? watchOnlyHelpKey(m) : '',
            reportUrl: action === 'report' ? reportNearMissUrl(m) : '',
            proposals: Object.entries(m.proposed_roles || {}).map(([role, p]) => proposalModel(role, p, opts)),
        };
    });
    const chargers = (report.chargers || []).map((c) => ({
        platform: c.platform, name: c.name || '', control: c.control || '', configured: !!c.configured,
        mapped: Object.entries(c.mapped || {}).map(([k, v]) => ({
            role: k, value: (v && (v.entity || v.value)) || '—',
            kind: v && v.device_class ? v.domain + '/' + v.device_class : '',
        })),
        unmapped: (c.unmapped || []).map((u) => u.entity),
    }));
    const roster = (report.roster_proposals || []).map((rp) => ({
        name: rp.roster?.name || rp.domain,
        proposals: Object.entries(rp.proposed_roles || {}).map(([role, p]) => proposalModel(role, p, opts)),
    }));
    const proberOnly = (report.disagreements || []).filter((d) => d.kind === 'prober_only').map((d) => d.platform);
    return {
        unknown: (census.unknown_energy_domains || []).map(describe),
        nomatch: census.rows_matched_nothing || [],
        chargers, misses, roster, proberOnly,
        empty: !chargers.length && !misses.length && !(report.prober_candidates || []).length,
    };
}

/** Every charger id SEM knows: the options list and the runtime number entities. */
export function knownChargerIds(states, options) {
    const out = new Set(((options || {}).ev_chargers || []).map((c) => c && c.id).filter(Boolean));
    for (const id of Object.keys(states || {})) {
        const m = id.match(/^number\.sem_charger_(.+)_minimum_current$/);
        if (m) out.add(m[1]);
    }
    return [...out];
}

// ── the element ──

const panelCss = css`
    :host { display: block; }
    .sheet { padding: 4px 0; }
    .top { display: flex; align-items: center; gap: 8px; margin: 0 0 10px; }
    .top h2 { flex: 1; margin: 0; font-size: 18px; font-weight: 600; }
    .mono { font-family: var(--code-font-family, monospace); font-size: 12px; word-break: break-all; }
    .warn { color: var(--n-warn); }
    .bad { color: var(--n-bad); }
    .ok { color: var(--n-ok); }
    .err { margin: 8px 0; padding: 8px 10px; border-radius: 10px; border-left: 4px solid var(--n-bad); background: var(--n-card2); font-size: 13px; }
    .msg { margin: 8px 0; font-size: 13px; color: var(--n-fg2); }
    .items { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
    .acts { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 6px 0 10px; }
    .bar { height: 6px; border-radius: 3px; background: var(--n-card2); overflow: hidden; margin: 6px 0; }
    .bar > i { display: block; height: 100%; background: var(--n-accent); }
    .bar > i.done { background: var(--n-ok); }
    .prop { padding: 6px 0; border-top: 1px solid var(--n-line); }
    .prop:first-child { border-top: 0; }
    .prop .k { font-weight: 500; font-size: 13px; }
`;

class SEMNextSetupPanel extends SEMNextBase {
    static get properties() {
        return {
            kind: { type: String },
            _options: { state: true }, _status: { state: true }, _err: { state: true },
            _msg: { state: true }, _busy: { state: true },
        };
    }
    static get styles() { return [nextCss, panelCss]; }

    constructor() {
        super();
        this.kind = 'check';
        this._options = null;
        this._entryId = '';
        this._status = {};
        this._err = '';
        this._msg = '';
        this._busy = false;
    }

    _watchIds() {
        return [...super._watchIds(), REPORT, 'sensor.sem_solar_power', 'sensor.sem_grid_import_power',
            'sensor.sem_grid_export_power', 'sensor.sem_battery_charge_power', 'sensor.sem_battery_discharge_power',
            'sensor.sem_home_consumption_power', 'sensor.sem_charging_state', 'binary_sensor.sem_heat_pump_registered'];
    }

    set hass(hass) {
        const first = !this._hass && hass;
        super.hass = hass;
        if (first) this._loadOptions();
    }
    get hass() { return this._hass; }

    async _loadOptions() {
        if (!this._hass) return;
        try {
            const resp = await this._hass.callService(DOMAIN, 'get_config', {}, undefined, false, true);
            const cfg = resp?.response?.config;
            if (cfg && typeof cfg === 'object') this._options = cfg;
            if (resp?.response?.entry_id) this._entryId = resp.response.entry_id;
        } catch (err) {
            this._fail(err);
        }
    }

    _fail(err) {
        this._err = (err && err.message) ? String(err.message) : String(err || this._t('next_apply_failed'));
    }

    async _save(write, field) {
        if (!this._hass || !write || this._status[field] === 'saving') return;
        this._err = '';
        this._status = { ...this._status, [field]: 'saving' };
        try {
            await this._hass.callService(DOMAIN, 'set_option',
                { options: { ...write }, ...(this._entryId ? { entry_id: this._entryId } : {}) }, undefined, false);
            this._status = { ...this._status, [field]: 'ok' };
            this._options = { ...(this._options || {}), ...write };
            await this._loadOptions();
        } catch (err) {
            this._status = { ...this._status, [field]: '' };
            this._fail(err);
        }
    }

    async _addCharger(suggested) {
        if (this._busy || !this._hass) return;
        const opts = this._options || {};
        const plan = chargerAddPlan(suggested, knownChargerIds(this._hass.states, opts), (opts.ev_chargers || []).length);
        if (plan.action !== 'add') return;
        this._busy = true;
        this._err = '';
        try {
            await this._hass.callService(DOMAIN, 'set_option',
                { options: { ev_chargers: [plan.charger] }, ...(this._entryId ? { entry_id: this._entryId } : {}) }, undefined, false);
            await this._loadOptions();
        } catch (err) {
            this._fail(err);
        } finally {
            this._busy = false;
        }
    }

    async _flip(which) {
        if (this._busy || !this._hass || this._obs()) return;
        this._busy = true;
        this._err = '';
        this._msg = '';
        try {
            const res = await this._hass.callService(DOMAIN, which === 'battery' ? 'flip_battery_sign' : 'flip_grid_sign',
                {}, undefined, false, true);
            const payload = res && res.response ? res.response : res;
            let copied = false;
            try { await navigator.clipboard.writeText(JSON.stringify(payload || {}, null, 2)); copied = true; } catch (_e) { copied = false; }
            this._msg = this._t(copied ? 'sign_flipped_copied' : 'sign_flipped');
        } catch (err) {
            this._fail(err);
        } finally {
            this._busy = false;
        }
    }

    _close(goto = '') {
        this.dispatchEvent(new CustomEvent('sem-next-close', { detail: goto ? { goto } : {}, bubbles: true, composed: true }));
    }

    _openHaSettings() { this._go('/config/integrations/integration/' + DOMAIN); }

    _say(o) {
        if (!o) return '';
        if (o.text) return o.text;
        return o.vars ? this._tf(o.key, o.vars) : this._t(o.key);
    }

    // ── render ──

    render() {
        if (!this._hass) return nothing;
        const t = (k) => this._t(k);
        const title = this.kind === 'hardware' ? t('config_section_detected_hardware') : t('next_setup_check');
        return html`<div class="app sheet">
            <div class="top">
                <h2>${title}</h2>
                ${this._btn(t('next_panel_close'), () => this._close(), { small: true, icon: 'mdi:close' })}
            </div>
            ${this._err ? html`<div class="err" role="alert">${this._err}</div>` : nothing}
            ${this._msg ? html`<div class="msg" role="status">${this._msg}</div>` : nothing}
            ${this.kind === 'hardware' ? this._hardware() : this._check()}
        </div>`;
    }

    _check() {
        const t = (k) => this._t(k);
        const m = checkModel(this._hass.states, this._options);
        const head = m.allDone ? t('config_setup_done') : this._tf('config_setup_progress', { done: m.done, total: m.total });
        const items = m.items.map((i) => this._row(i.done ? 'mdi:check-circle' : 'mdi:circle-outline', t(i.labelKey),
            i.done ? html`<span class="ok">✓</span>`
                : (i.optional ? t('config_setup_optional') : this._link(t('config_setup_action'), () => this._close(i.key))),
            ''));
        const reads = m.sources.map((r) => this._row('', t('config_check_' + r.key),
            (r.dir ? t('config_check_' + r.dir) + ' ' : '') + fmtWatts(r.w), ''));
        const obs = this._obs();
        return html`
            ${this._sec(head, html`<div class="bar"><i class=${m.allDone ? 'done' : ''} style=${'width:' + m.pct + '%'}></i></div>
                <div class="rows">${items}</div>
                <p class="help">${t('config_overview_help')}</p>
                <div class="acts">${this._btn(t('config_open_ha_settings'), () => this._openHaSettings(), { small: true, icon: 'mdi:cog-outline' })}</div>`)}
            ${this._sec(t('config_check_intro'), html`<div class="rows">${reads}</div>
                <p class="help">${t('config_check_question')}</p>
                <div class="acts">
                    ${this._btn(t('config_check_grid_wrong'), () => this._flip('grid'), { small: true, icon: 'mdi:swap-vertical-bold', disabled: this._busy || obs })}
                    ${m.hasBattery ? this._btn(t('config_check_battery_wrong'), () => this._flip('battery'), { small: true, icon: 'mdi:swap-vertical-bold', disabled: this._busy || obs }) : nothing}
                </div>
                <p class="help">${t('config_check_wrong_sensor')}</p>`)}`;
    }

    _useBtn(write, field) {
        const st = this._status[field];
        if (!write) return nothing;
        return html`${this._btn(st === 'saving' ? this._t('config_proposed_using') : this._t('config_proposed_use'),
            () => this._save(write, field), { small: true, primary: true, disabled: st === 'saving' || this._obs() })}${st === 'ok' ? html` <span class="ok">✓</span>` : nothing}`;
    }

    _proposal(p, field) {
        const t = (k) => this._t(k);
        return html`<div class="prop">
            <div class="k">${p.role}</div>
            <div class="mono">${p.what}${p.matchedKey ? html` <span class="dim">· ${p.matchedKey}</span>` : nothing}</div>
            <div class="acts">
                ${this._useBtn(p.write, field)}
                ${p.saved ? html`<span class="dim sm">${t('config_proposed_already')}</span>` : nothing}
                ${p.why ? html`<span class="dim sm">${this._say(p.why)}</span>` : nothing}
            </div>
            ${p.alts.map((a, i) => html`<div class="acts">
                <span class="dim sm">${t('config_proposed_or')}</span>
                <span class="mono">${a.entity}${a.matchedKey ? ' · ' + a.matchedKey : ''}</span>
                ${a.write && !a.saved ? this._useBtn(a.write, field + '_alt' + i) : nothing}
                ${a.why ? html`<span class="dim sm">${this._say(a.why)}</span>` : nothing}
            </div>`)}
        </div>`;
    }

    _hardware() {
        const t = (k) => this._t(k);
        const report = this._attrs(REPORT).detection_report || null;
        const m = hardwareModel(report, this._options, knownChargerIds(this._hass.states, this._options));
        if (!m) return html`<p class="help">${t('config_detect_none')}</p>`;
        const obs = this._obs();
        const gaps = [];
        if (m.unknown.length) {
            gaps.push(this._row('mdi:help-circle-outline', t('config_census_unknown'),
                '', m.unknown.map((u) => u.installs ? u.name + ' · ' + u.installs + ' ' + t('config_census_installs') : u.name).join(', '), { cls: 'warn' }));
        }
        if (m.nomatch.length) gaps.push(this._row('mdi:help-circle-outline', t('config_census_nomatch'), '', m.nomatch.join(', '), { cls: 'warn' }));
        const chargers = m.chargers.map((c) => this._sec(t('config_detect_charger') + ': ' + c.platform + (c.name ? ' · ' + c.name : ''), html`
            <div class="acts">${c.control ? this._pill(c.control) : nothing}${c.configured ? this._pill(t('config_detect_configured'), 'ok') : nothing}</div>
            <div class="rows">${c.mapped.map((r) => this._row('', r.role, html`<span class="mono">${r.value}</span>`, r.kind))}</div>
            ${c.unmapped.length ? html`<p class="help">${t('config_detect_unmapped')}: <span class="mono">${c.unmapped.join(', ')}</span></p>` : nothing}`));
        const misses = m.misses.map((x, mi) => this._sec('⚠ ' + x.name, html`
            <p class="help">${this._tf(x.labelKey, { roles: x.roles })}</p>
            <div class="mono">${x.entities.join(', ')}</div>
            <div class="acts">
                ${x.action === 'add' ? (x.plan && x.plan.action === 'add'
                    ? this._btn(t('config_near_miss_add'), () => this._addCharger(x.suggested), { small: true, primary: true, icon: 'mdi:ev-station', disabled: this._busy || obs })
                    : this._pill(t('config_detect_configured'), 'ok')) : nothing}
                ${x.action === 'watch' ? html`<span class="dim sm">${t(x.watchKey)}</span>` : nothing}
                ${x.action === 'report' && x.reportUrl ? html`<a class="btn sm" target="_blank" rel="noopener" href=${x.reportUrl}>${t('config_near_miss_report')}</a>` : nothing}
            </div>
            ${x.proposals.length ? html`<div class="acts"><b class="sm">${t('config_proposed_roles')}</b><span class="dim sm">${t('config_proposed_unconfirmed')}</span></div>
                ${x.proposals.map((p) => this._proposal(p, 'prop_' + mi + '_' + p.role))}
                <p class="help">${t('config_proposed_help')}</p>` : nothing}`, { cls: 'warn' }));
        const roster = m.roster.map((r, ri) => this._sec('🧩 ' + r.name, html`
            <div class="acts"><span class="dim sm">${t('config_proposed_unconfirmed')}</span></div>
            ${r.proposals.map((p) => this._proposal(p, 'roster_' + ri + '_' + p.role))}`));
        return html`
            <p class="help">${t('config_detect_intro')}</p>
            ${gaps.length ? html`<div class="rows">${gaps}</div>` : nothing}
            ${chargers}
            ${misses}
            ${roster}
            ${m.roster.length ? html`<p class="help">${t('config_proposed_help')}</p>` : nothing}
            ${m.proberOnly.map((p) => this._row('mdi:magnify', p, '', t('config_detect_prober_only')))}
            ${m.empty ? html`<p class="help">${t('config_detect_nothing')}</p>` : nothing}`;
    }
}

if (!customElements.get('sem-next-setup-panel')) customElements.define('sem-next-setup-panel', SEMNextSetupPanel);
