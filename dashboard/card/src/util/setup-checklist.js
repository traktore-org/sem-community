/**
 * (#1379) The first-run checklist: pure model + routes (node-tested).
 *
 * The data is the setup_checklist attribute on sensor.sem_diag_charger_control,
 * built by the same facts as the AI setup tool (setup_status.py).
 */

export const CHECKLIST_ENTITY = 'sensor.sem_diag_charger_control';
export const OBSERVER_SWITCH = 'switch.sem_observer_mode';
export const HIDE_KEY = 'sem-setup-checklist-hidden-v1';
/** sessionStorage: the panel the SEM Next System screen opens. */
export const OPEN_PANEL_KEY = 'sem-next-open-panel';

/** The checklist the backend published, or null. */
export function readChecklist(states) {
    const c = states && states[CHECKLIST_ENTITY]?.attributes?.setup_checklist;
    return c && Array.isArray(c.items) ? c : null;
}

const REPAIR_DOMAIN = 'solar_energy_management';

/**
 * (#1321) Every open thing to check, in plain words. `listed` is HA's own repairs
 * list (repairs/list_issues), `localize` turns a key into HA's text. When the
 * titles cannot all be read, SEM's single published title stands and the rest
 * are counted: `more(n)` words that count. → [string]
 */
export function repairNames(rep, listed, localize, more) {
    const n = Number(rep?.count) || 0;
    if (!n) return [];
    // (#1321) SEM publishes every title itself: HA's localize has none for these
    const own = (Array.isArray(rep.titles) ? rep.titles : []).filter((t) => typeof t === 'string' && t);
    if (own.length === n) return own;
    const titles = (Array.isArray(listed) ? listed : [])
        .filter((i) => i && i.domain === REPAIR_DOMAIN && !i.ignored)
        .map((i) => localize(`component.${REPAIR_DOMAIN}.issues.${i.translation_key}.title`)).filter(Boolean);
    if (titles.length === n) return titles;
    const first = rep.first ? [rep.first] : [];
    return n > first.length && first.length ? [...first, more(n - first.length)] : first;
}

/** Whether SEM only watches: the switch is live, the attribute is the fallback. */
export function isWatchOnly(states, checklist) {
    const sw = states && states[OBSERVER_SWITCH];
    if (sw && (sw.state === 'on' || sw.state === 'off')) return sw.state === 'on';
    return !!(checklist && checklist.watch_only);
}

/** What to draw: banner, list, chip; the numbers for the chip and the bar. */
export function viewModel(checklist, watchOnly, hidden, reopened) {
    const must = !!checklist.must_open;
    const list = !!reopened || ((watchOnly || must) && !hidden);
    return {
        banner: watchOnly,
        list,
        chip: !list,
        done: checklist.done, total: checklist.total,
        // (#1321) every required step done: the list folds to one line
        complete: checklist.total > 0 && checklist.done >= checklist.total,
        pct: checklist.total ? Math.round((checklist.done / checklist.total) * 100) : 100,
        repairs: checklist.repairs || { count: 0, first: null },
    };
}

/** A raw integration domain as words ("some_domain" -> "Some Domain"). */
export function brandLabel(domain) {
    return String(domain).split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

/** The sibling screen of the page we are on: the dashboard URL is never assumed (#1321). */
export function sibling(pathname, view) {
    const parts = String(pathname || '').split('/').filter(Boolean);
    if (parts.length) parts[parts.length - 1] = view; else parts.push(view);
    return '/' + parts.join('/');
}

/**
 * Where a row's button goes: the Devices screen for a charger, the System
 * screen's setup panel for forecast and price. Things to check: HA's Repairs page.
 */
export function rowTarget(key, pathname) {
    if (key === 'repairs') return { path: '/config/repairs' };
    if (key === 'charger') return { path: sibling(pathname, 'devices') };
    return { path: sibling(pathname, 'system'), store: [OPEN_PANEL_KEY, 'setup'] };
}

export function readHidden() {
    try { return localStorage.getItem(HIDE_KEY) === '1'; } catch (e) { return false; }
}
export function writeHidden(on) {
    try { localStorage.setItem(HIDE_KEY, on ? '1' : '0'); } catch (e) { /* the choice lasts this page only */ }
}

/** Read a one-shot route hint left by the checklist, and clear it. */
export function takeStored(key) {
    try {
        const v = window.sessionStorage.getItem(key);
        if (v) window.sessionStorage.removeItem(key);
        return v || '';
    } catch (e) { return ''; }
}
