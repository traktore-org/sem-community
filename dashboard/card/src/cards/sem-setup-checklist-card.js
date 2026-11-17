/**
 * SEM Setup Checklist (#1379)
 *
 * Top of the Home screen of both dashboards. While SEM only watches it says
 * so, with one button to let SEM take control (an inline confirm first).
 * Below it, a short checklist: hardware found, charger, forecast, price,
 * things to check. Each row opens the place that fixes it. Once SEM is in
 * control and nothing must be done, only a small chip stays; the chip
 * reopens the list. "Hide" folds the list for this browser.
 *
 * Reads the setup_checklist attribute of sensor.sem_diag_charger_control,
 * the same facts the AI setup tool uses.
 */

import { SEMLitBase, html, css, nothing } from '../base/sem-lit-base.js';
import { semDefineCard } from '../base/sem-shared.js';
import {
    CHECKLIST_ENTITY, OBSERVER_SWITCH, readChecklist, isWatchOnly, viewModel,
    brandLabel, rowTarget, readHidden, writeHidden,
} from '../util/setup-checklist.js';

const ICON_OK = 'mdi:check-circle';
const ICON_TODO = 'mdi:circle-outline';

class SEMSetupChecklistCard extends SEMLitBase {
    static get watchedEntities() { return [CHECKLIST_ENTITY, OBSERVER_SWITCH]; }
    static get watchedAttributes() { return { [CHECKLIST_ENTITY]: ['setup_checklist'] }; }

    static get properties() {
        return {
            ...super.properties,
            layout: { type: String },
            _hidden: { state: true },
            _reopened: { state: true },
            _confirming: { state: true },
        };
    }

    constructor() {
        super();
        this.layout = 'classic';
        this._hidden = readHidden();
        this._reopened = false;
        this._confirming = false;
    }

    setConfig(config) {
        super.setConfig(config);
        if (config.layout === 'next') this.layout = 'next';
    }

    _hide() { this._reopened = false; this._hidden = true; writeHidden(true); }
    _reopen() { this._hidden = false; this._reopened = true; writeHidden(false); }

    // Only after the inline confirm: this is the one call that makes SEM move hardware.
    _takeControl() {
        this._confirming = false;
        this._callService('switch', 'turn_off', { entity_id: OBSERVER_SWITCH });
    }

    _go(key) {
        const target = rowTarget(key, this.layout, window.location.pathname);
        try { if (target.store) window.sessionStorage.setItem(target.store[0], target.store[1]); } catch (e) { /* the page still opens */ }
        window.history.pushState(null, '', target.path);
        window.dispatchEvent(new CustomEvent('location-changed', { bubbles: true, composed: true }));
    }

    _fill(key, vars) {
        return Object.entries(vars).reduce((t, [k, v]) => t.split('{' + k + '}').join(v), this._t(key));
    }

    _banner() {
        if (this._confirming) {
            return html`<section class="banner" aria-label=${this._t('setup_watch_title')}>
                <div class="txt"><strong>${this._t('setup_confirm_text')}</strong></div>
                <div class="btns">
                    <button type="button" class="btn primary" @click=${() => this._takeControl()}>${this._t('setup_confirm_yes')}</button>
                    <button type="button" class="btn ghost" @click=${() => { this._confirming = false; }}>${this._t('setup_confirm_no')}</button>
                </div></section>`;
        }
        return html`<section class="banner" aria-label=${this._t('setup_watch_title')}>
            <div class="head"><ha-icon icon="mdi:eye-outline"></ha-icon>
                <div class="txt"><strong>${this._t('setup_watch_title')}</strong>
                    <span>${this._t('setup_watch_body')}</span></div></div>
            <button type="button" class="btn primary" @click=${() => { this._confirming = true; }}>${this._t('setup_take_control')}</button>
        </section>`;
    }

    _row(done, title, sub, action) {
        return html`<div class="row">
            <ha-icon class=${done ? 'ok' : 'todo'} icon=${done ? ICON_OK : ICON_TODO}></ha-icon>
            <div class="txt"><span class="t">${title}</span>${sub ? html`<span class="s">${sub}</span>` : nothing}</div>
            ${action ? html`<button type="button" class="btn small" @click=${action.fn}>${action.label}</button>` : nothing}
        </div>`;
    }

    _itemRow(item) {
        const opt = html` <span class="s">· ${this._t('setup_optional')}</span>`;
        switch (item.key) {
            case 'hardware': return this._row(item.done,
                this._t(item.done ? 'setup_hw_found' : 'setup_hw_missing'),
                (item.brands || []).map(brandLabel).join(' · '));
            case 'dashboard': return this._row(true, this._t('setup_dashboard_ready'), this._t('setup_dashboard_sub'));
            case 'charger': return this._chargerRow(item);
            case 'forecast': return this._row(item.done,
                html`${this._t('setup_forecast_title')}${opt}`,
                this._t(item.done ? 'setup_forecast_set' : 'setup_forecast_sub'),
                item.done ? null : { label: this._t('setup_btn_how'), fn: () => this._go('forecast') });
            default: return this._row(item.done,
                html`${this._t('setup_price_title')}${opt}`,
                this._t(item.done ? 'setup_price_done' : 'setup_price_sub'),
                item.done ? null : { label: this._t('setup_btn_add'), fn: () => this._go('price') });
        }
    }

    _chargerRow(item) {
        if (item.done) return this._row(true, this._t('setup_charger_done'), '');
        const found = !!item.detected;
        return this._row(false, this._t('setup_charger_title'),
            found ? this._fill('setup_charger_found', { name: item.detected }) : this._t('setup_charger_none'),
            { label: this._t(found ? 'setup_btn_use' : 'setup_btn_add'), fn: () => this._go('charger') });
    }

    _repairsRow(repairs) {
        if (!repairs.count) return nothing;
        const title = repairs.count === 1 ? this._t('setup_check_one')
            : this._fill('setup_check_n', { n: repairs.count });
        return this._row(false, title, repairs.first || '',
            { label: this._t('setup_btn_open'), fn: () => this._go('repairs') });
    }

    _list(c, vm) {
        return html`<section class="list" aria-label=${this._t('setup_list_title')}>
            <div class="lhead">
                <span class="cap">${this._t('setup_list_title')} · ${this._fill('setup_of', { done: vm.done, total: vm.total })}</span>
                <button type="button" class="link" @click=${() => this._hide()}>${this._t('setup_hide')}</button>
            </div>
            <div class="bar" role="progressbar" aria-valuenow=${vm.pct} aria-valuemin="0" aria-valuemax="100"
                aria-label=${this._t('setup_list_title')}><div class="fill" style="width:${vm.pct}%"></div></div>
            ${c.items.map((i) => this._itemRow(i))}
            ${this._repairsRow(vm.repairs)}
            <div class="hint">${this._t('setup_ai_hint')}</div>
        </section>`;
    }

    _chip(vm, watchOnly) {
        return html`<div class="chip-row">
            ${watchOnly ? nothing : html`<span class="chip ok"><ha-icon icon=${ICON_OK}></ha-icon>${this._t('setup_chip_control')}</span>`}
            <button type="button" class="chip link" @click=${() => this._reopen()}>
                ${this._fill('setup_chip_setup', { done: vm.done, total: vm.total })}</button>
        </div>`;
    }

    render() {
        const c = readChecklist(this._hass?.states);
        if (!c) return nothing;
        const watchOnly = isWatchOnly(this._hass.states, c);
        const vm = viewModel(c, watchOnly, this._hidden, this._reopened);
        return html`${vm.banner ? this._banner() : nothing}
            ${vm.list ? this._list(c, vm) : this._chip(vm, watchOnly)}`;
    }

    getCardSize() { return 3; }
    static getStubConfig() { return {}; }

    static get styles() {
        return css`
            :host { display: block; font-family: 'Segoe UI','Roboto',sans-serif; color: var(--primary-text-color); }
            .banner { border: 1px solid #5BC8D873; background: #5BC8D81A; border-radius: 14px; padding: 14px;
                display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; }
            .head { display: flex; gap: 10px; align-items: flex-start; }
            .head ha-icon { color: #5BC8D8; --mdc-icon-size: 22px; flex: none; }
            .txt { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
            .txt strong { font-size: 15px; }
            .txt span { font-size: 13px; line-height: 1.45; color: var(--secondary-text-color); }
            .btns { display: flex; gap: 8px; flex-wrap: wrap; }
            .btn { min-height: 44px; border-radius: 10px; padding: 0 16px; font-size: 14px; font-weight: 600; font-family: inherit;
                cursor: pointer; border: 1px solid transparent; }
            .btn.primary { background: #5BC8D8; color: #0c1214; }
            .btn.ghost { background: transparent; color: var(--primary-text-color); border-color: var(--divider-color); }
            .btn.small { min-width: 72px; border-radius: 8px; font-size: 13px; background: transparent;
                color: #8DC892; border-color: #8DC89299; flex: none; }
            .list { border: 1px solid var(--divider-color); border-radius: 12px; padding: 12px 14px; margin-bottom: 12px;
                background: var(--card-background-color); }
            .lhead { display: flex; justify-content: space-between; align-items: center; padding-bottom: 8px; }
            .cap { font-size: 11px; letter-spacing: .05em; text-transform: uppercase; color: var(--secondary-text-color); font-weight: 600; }
            .link { background: none; border: none; color: var(--secondary-text-color); font-size: 12px; font-family: inherit;
                cursor: pointer; min-height: 44px; padding: 0 8px; }
            .bar { height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; margin-bottom: 6px; }
            .fill { height: 6px; background: #8DC892; }
            .row { display: flex; gap: 10px; align-items: center; min-height: 52px; border-top: 1px solid var(--divider-color); }
            .row ha-icon { --mdc-icon-size: 20px; flex: none; }
            .row .ok { color: #8DC892; }
            .row .todo { color: var(--secondary-text-color); }
            .row .t { font-size: 14px; color: var(--primary-text-color); }
            .row .s { font-size: 12px; color: var(--secondary-text-color); }
            .hint { font-size: 12px; color: var(--secondary-text-color); padding-top: 10px; border-top: 1px solid var(--divider-color); }
            .chip-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
            .chip { display: inline-flex; align-items: center; gap: 6px; min-height: 44px; padding: 0 12px; border-radius: 22px;
                font-size: 13px; font-weight: 600; font-family: inherit; border: 1px solid var(--divider-color); background: transparent; }
            .chip.ok { color: #8DC892; border-color: #8DC89266; }
            .chip.link { color: var(--secondary-text-color); cursor: pointer; }
            .chip ha-icon { --mdc-icon-size: 18px; }
        `;
    }
}

semDefineCard('sem-setup-checklist-card', SEMSetupChecklistCard, {
    type: 'sem-setup-checklist-card',
    name: 'SEM Setup Checklist',
    description: 'First-run banner and checklist: says when SEM only watches, lets you take control, and links each open step',
    documentationURL:
        'https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-setup-checklist-card',
    preview: false,
});
