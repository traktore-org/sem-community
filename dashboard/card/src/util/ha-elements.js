/**
 * (#1321) Home Assistant's own elements, used when they exist.
 *
 * HA loads most of its form elements on demand (they belong to editors and
 * dialogs), so a custom card cannot count on them. A card asks
 * `haDefined(tag)` while it renders and draws the HA element when it is
 * there, a native one styled with HA's theme variables when it is not.
 * `ensureHaElements()` tries to get the lazy ones loaded (HA's card helpers
 * build a card whose editor pulls them in), waits for them with a timeout and
 * tells the card whether anything new arrived, so it can render again.
 */

/** Every HA element the SEM screens draw when available. */
export const HA_TAGS = [
    'ha-switch', 'ha-control-select', 'ha-button-toggle-group', 'ha-button',
    'ha-selector', 'ha-textfield', 'ha-dialog',
];

/** Is this HA element defined right now? Safe where there is no registry. */
export function haDefined(tag) {
    try { return !!(globalThis.customElements && globalThis.customElements.get(tag)); } catch (e) { return false; }
}

let helperTry = null;

/** Once per page: HA's card helpers build an entities card; its editor loads the form elements. */
function pullLazyElements() {
    if (helperTry) return helperTry;
    helperTry = (async () => {
        try {
            const helpers = await globalThis.window?.loadCardHelpers?.();
            if (helpers?.createCardElement) {
                const el = await helpers.createCardElement({ type: 'entities', entities: [] });
                await el.constructor?.getConfigElement?.();
            }
        } catch (e) { /* the native fallbacks stay */ }
    })();
    return helperTry;
}

function waitFor(tag, ms) {
    const reg = globalThis.customElements;
    if (haDefined(tag)) return Promise.resolve(true);
    if (!reg || typeof reg.whenDefined !== 'function') return Promise.resolve(false);
    return new Promise((resolve) => {
        const timer = setTimeout(() => resolve(false), ms);
        reg.whenDefined(tag).then(() => { clearTimeout(timer); resolve(true); }, () => { clearTimeout(timer); resolve(false); });
    });
}

/**
 * Try to get the HA elements defined. Resolves `{ tag: boolean }`; never
 * rejects. `timeout` bounds the wait for each tag that is still missing.
 */
export async function ensureHaElements(tags = HA_TAGS, timeout = 2500) {
    if (tags.some((t) => !haDefined(t))) await pullLazyElements();
    const found = await Promise.all(tags.map((t) => waitFor(t, timeout)));
    const out = {};
    tags.forEach((t, i) => { out[t] = found[i]; });
    return out;
}
