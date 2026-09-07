// tests/live/gui/lib.js — shared helpers for the browser-driven live tests
// (#915). The fourth layer of SEM's test pyramid: a real Home Assistant, the
// real dashboard, a real browser, and a real click.
//
// Why this layer exists. Every layer below it passed while the install read
// 0 W from a live inverter (#915: the config-flow step wrote keys the reader
// never read), and while the card told a user "unconfirmed" with no way to
// confirm. Unit tests check that a function returns the right dict; this
// checks that a person can finish the job.
//
// Never point it at PROD. `assertNotProd` refuses.

const { chromium } = require(process.env.PLAYWRIGHT || '/tmp/node_modules/playwright');

const HOST = process.env.HA_URL || 'http://10.10.20.46:8123';
const TOKEN = process.env.HA_TOKEN || process.env.HA_TEST_TOKEN;

function assertNotProd() {
    if (HOST.includes('10.10.20.150')) {
        throw new Error('refusing to drive PROD — these tests click buttons');
    }
    if (!TOKEN) throw new Error('HA_TOKEN / HA_TEST_TOKEN not set');
}

async function api(path, opts = {}) {
    const res = await fetch(`${HOST}/api/${path}`, {
        ...opts,
        headers: {
            Authorization: `Bearer ${TOKEN}`,
            'Content-Type': 'application/json',
            ...(opts.headers || {}),
        },
    });
    const text = await res.text();
    try { return JSON.parse(text); } catch { return text; }
}

async function state(entityId) {
    const s = await api(`states/${entityId}`);
    return s && s.state;
}

async function entryId() {
    const entries = await api('config/config_entries/entry');
    const sem = (entries || []).find(e => e.domain === 'solar_energy_management');
    return sem ? sem.entry_id : null;
}

/**
 * The install's effective config.
 *
 * NOT from `/config/config_entries/entry` — that endpoint returns the entry's
 * metadata and no `data`/`options` at all, so reading a written key there
 * always looks like "nothing happened". (It made the first run of this suite
 * report a failure against code that had in fact written the value.) SEM's
 * own diagnostics download carries the merged config, redacting only the
 * secret keys, so entity ids survive.
 */
async function config() {
    const id = await entryId();
    if (!id) return {};
    const diag = await api(`diagnostics/config_entry/${id}`);
    const ce = ((diag && diag.data) || diag || {}).config_entry || {};
    return { ...(ce.data || {}), ...(ce.options || {}) };
}

async function openBrowser() {
    assertNotProd();
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({
        viewport: { width: 1100, height: 2200 }, deviceScaleFactor: 2,
    });
    await ctx.addInitScript(([t, h]) => {
        localStorage.setItem('hassTokens', JSON.stringify({
            access_token: t, token_type: 'Bearer', expires_in: 315360000,
            hassUrl: h, clientId: null, refresh_token: '',
            expires: Date.now() + 315360000000,
        }));
        localStorage.selectedLanguage = '"en"';
    }, [TOKEN, HOST]);
    const page = await ctx.newPage();
    page.__errors = [];
    page.on('console', m => { if (m.type() === 'error') page.__errors.push(m.text().slice(0, 200)); });
    return { browser, page };
}

/** Walk every shadow root and run `fn(cardElement)` in the page. */
const CARD_FINDER = `(() => {
    const hit = [];
    const rec = (r) => { for (const el of r.querySelectorAll('*')) {
        if (el.tagName && el.tagName.toLowerCase() === 'sem-config-card') hit.push(el);
        if (el.shadowRoot) rec(el.shadowRoot); } };
    rec(document); return hit[0] || null;
})()`;

async function openConfigCard(page) {
    await page.goto(`${HOST}/sem-dashboard/config`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(7000);
    const opened = await page.evaluate(`(() => {
        const c = ${CARD_FINDER};
        if (!c) return 'no-card';
        if (typeof c._openSection !== 'function') return 'no-open';
        c._openSection('detected_hardware');
        return 'ok';
    })()`);
    if (opened !== 'ok') throw new Error(`config card not usable: ${opened}`);
    await page.waitForTimeout(3000);
}

async function cardText(page) {
    return page.evaluate(`(() => {
        const c = ${CARD_FINDER};
        return c ? (c.shadowRoot.textContent || '').replace(/\\s+/g, ' ') : '';
    })()`);
}

/** Click the Nth button whose label matches `label` inside the card. */
async function clickCardButton(page, label, nth = 0) {
    return page.evaluate(`(() => {
        const c = ${CARD_FINDER};
        if (!c) return 'no-card';
        const btns = [...c.shadowRoot.querySelectorAll('button, a.sem-btn')]
            .filter(b => (b.textContent || '').trim().includes(${JSON.stringify(label)}));
        if (btns.length <= ${nth}) return 'not-found:' + btns.length;
        btns[${nth}].click();
        return 'clicked';
    })()`);
}

/**
 * All text on the page, across every shadow root.
 *
 * Two traps, both hit while writing this: `textContent` stops at a shadow
 * boundary (scraping the dialog container returned "Name your energy sensors
 * Submit" and nothing else), and collecting only childless elements drops
 * every paragraph that contains an inline `<code>` — which is exactly the
 * shape of the step description under test. So: walk TEXT NODES, across
 * shadow roots, skipping script and style.
 */
/** Poll until `fn()` is truthy, or give up. SEM publishes on a 10 s cycle
 * and a fresh entry warms for a few of them, so a value read the instant an
 * install finishes is a coin toss — one suite failed on it only when another
 * suite had touched the rig first. */
async function until(fn, { timeoutMs = 90000, everyMs = 5000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
        const v = await fn();
        if (v) return v;
        if (Date.now() > deadline) return null;
        await new Promise(r => setTimeout(r, everyMs));
    }
}

async function deepText(page) {
    return page.evaluate(`(() => {
        const out = [];
        const walk = (node, depth) => {
            if (depth > 30 || !node) return;
            for (const child of node.childNodes || []) {
                if (child.nodeType === 3) {            // a text node
                    const t = child.textContent.trim();
                    if (t) out.push(t);
                } else if (child.nodeType === 1) {     // an element
                    const tag = child.tagName;
                    if (tag === 'SCRIPT' || tag === 'STYLE') continue;
                    if (child.shadowRoot) walk(child.shadowRoot, depth + 1);
                    walk(child, depth + 1);
                }
            }
        };
        walk(document.body, 0);
        return out.join(' ').replace(/\\s+/g, ' ');
    })()`);
}

async function shot(page, path) {
    const box = await page.evaluate(`(() => {
        const c = ${CARD_FINDER};
        if (!c) return null;
        let b = null;
        for (const el of c.shadowRoot.querySelectorAll('*')) {
            const r = el.getBoundingClientRect();
            if ((el.textContent || '').includes('Detected hardware')
                && r.height > 80 && r.height < 2100) {
                b = { x: Math.max(0, r.x - 8), y: Math.max(0, r.y - 8),
                      width: Math.min(1084, r.width + 16),
                      height: Math.min(2180, r.height + 16) };
            }
        }
        return b;
    })()`);
    if (!box) return false;
    await page.evaluate(y => window.scrollTo(0, Math.max(0, y - 40)), box.y);
    await page.waitForTimeout(900);
    const b2 = await page.evaluate(`(() => {
        const c = ${CARD_FINDER};
        let b = null;
        for (const el of c.shadowRoot.querySelectorAll('*')) {
            const r = el.getBoundingClientRect();
            if ((el.textContent || '').includes('Detected hardware')
                && r.height > 80 && r.height < 2100) {
                b = { x: Math.max(0, r.x - 8), y: Math.max(0, r.y - 8),
                      width: Math.min(1084, r.width + 16),
                      height: Math.min(2180, r.height + 16) };
            }
        }
        return b;
    })()`);
    if (!b2 || b2.height < 40) return false;
    await page.screenshot({ path, clip: b2 });
    return true;
}

// ── the tiniest assertion harness that still prints usefully ──
const results = [];
function check(name, ok, detail = '') {
    results.push({ name, ok: !!ok, detail });
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
    return !!ok;
}
function summary() {
    const bad = results.filter(r => !r.ok);
    console.log(`\n${results.length - bad.length}/${results.length} passed`);
    if (bad.length) { console.log('failed:'); bad.forEach(b => console.log('  ' + b.name)); }
    return bad.length === 0;
}

module.exports = { HOST, TOKEN, api, state, config, entryId, openBrowser, openConfigCard,
                   deepText, until,
                   cardText, clickCardButton, shot, check, summary, assertNotProd };
