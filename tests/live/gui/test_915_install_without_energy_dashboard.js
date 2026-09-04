#!/usr/bin/env node
// tests/live/gui/test_915_install_without_energy_dashboard.js
//
// #915 — the install that used to be refused.
//
// Until this change, an Energy Dashboard that was empty or missing solar/grid
// ENDED the installation: "set it up first, then start again." This suite
// drives that exact situation through the real UI and asserts SEM asks the
// box instead — and, crucially, that the install it produces actually READS
// (the first version wrote config keys the reader never consumed, so a clean
// install reported 0 W from a live inverter).
//
//   B1  a broken Energy Dashboard opens the sources step, not an abort
//   B2  every field is pre-filled, and says which declared key matched
//   B3  the install completes through the UI
//   B4  SEM then reads each source's live value
//   B5  the rig is left exactly as it was found
//
// Mutates the rig: it removes the grid source from the Energy Dashboard and
// reinstalls SEM. Both are restored in the `finally` block.

const L = require('./lib');
const OUT = process.env.SHOT_DIR || '/tmp';
const SEM = 'Solar Energy Management';

const ws = (page, msg) => page.evaluate(
    m => document.querySelector('home-assistant').hass.callWS(m), msg);

async function deleteSem() {
    const id = await L.entryId();
    if (id) await L.api(`config/config_entries/entry/${id}`, { method: 'DELETE' });
}

(async () => {
    const { browser, page } = await L.openBrowser();
    let prefsBackup = null;
    try {
        await page.goto(`${L.HOST}/config/integrations`, { waitUntil: 'networkidle' });
        await page.waitForTimeout(4000);

        // ── B0 — break the Energy Dashboard the way a half-set-up house is
        prefsBackup = await ws(page, { type: 'energy/get_prefs' });
        const withoutGrid = {
            ...prefsBackup,
            energy_sources: (prefsBackup.energy_sources || [])
                .filter(s => s.type !== 'grid'),
        };
        await ws(page, { type: 'energy/save_prefs', ...withoutGrid });
        const after = await ws(page, { type: 'energy/get_prefs' });
        L.check('B0 the Energy Dashboard now has no grid source',
                !(after.energy_sources || []).some(s => s.type === 'grid'));

        // HA writes energy prefs through a DELAYED store, and SEM reads the
        // file rather than the in-memory prefs. Without this settle the first
        // run of this suite deleted the grid source, immediately started the
        // flow, and got the ordinary Energy-Dashboard path — a green-looking
        // run that had tested nothing.
        await page.waitForTimeout(35000);

        await deleteSem();
        await page.waitForTimeout(8000);

        // ── B1/B2 — the flow through the real dialog
        //
        // Which dialog depends on something this change caused: SEM now
        // offers itself when a supported inverter is present, so seconds
        // after the entry is deleted Home Assistant puts a DISCOVERED card on
        // the Integrations page — and a discovery flow in progress makes the
        // manual "Add integration" route a dead end. A user would click
        // Configure on that card, so that is what this does, falling back to
        // the manual route when nothing was discovered.
        await page.reload({ waitUntil: 'networkidle' });
        await page.waitForTimeout(4000);
        const discovered = await page.evaluate(() =>
            document.querySelector('home-assistant').hass
                .callWS({ type: 'config_entries/flow/progress' })
                .then(f => (f || []).some(x => x.handler === 'solar_energy_management'))
                .catch(() => false));
        // NOT an assertion: Home Assistant decides when to re-run discovery,
        // so whether a card is waiting seconds after an uninstall is timing,
        // not behaviour. The behaviour — discovery no longer standing down
        // because a different page is unconfigured — is pinned where it can
        // be pinned honestly, in tests/test_config_flow.py.
        console.log(`route: ${discovered ? 'discovery card' : 'Add integration'}`);
        if (discovered) {
            await page.getByRole('button', { name: /configure|konfigurieren|einrichten/i })
                .first().click();
        } else {
            await page.getByText('Add integration').first().click();
            await page.waitForTimeout(2500);
            await page.keyboard.type(SEM);
            await page.waitForTimeout(2500);
            await page.keyboard.press('Enter');
        }
        await page.waitForTimeout(7000);

        const dialogText = () => L.deepText(page);
        const step = await dialogText();

        L.check('B1 an incomplete Energy Dashboard does not end the install',
                !/start this installation again|Energy Dashboard is not configured/i.test(step),
                step.slice(0, 120));
        L.check('B1b the sources step is shown',
                /Name your energy sensors|energy sensors/i.test(step), step.slice(0, 140));
        L.check('B2 it says what it recognised, and why',
                /declared as/i.test(step));
        for (const [label, key] of [['solar', 'input_power'],
                                    ['grid', 'meter_active_power'],
                                    ['battery', 'storage_charge_discharge_power']]) {
            L.check(`B2b the ${label} sensor is pre-filled from a declared key`,
                    step.includes(key), key);
        }
        await page.screenshot({ path: `${OUT}/915_B_sources_step.png` });

        // ── B3 — submit the pre-filled form, then the hardware step
        await page.getByRole('button', { name: /submit|next|weiter/i }).first().click();
        await page.waitForTimeout(6000);
        const step2 = await dialogText();
        L.check('B3 the pre-filled form is accepted',
                !/required|invalid/i.test(step2), step2.slice(0, 120));
        try {
            await page.getByRole('button', { name: /submit|next|finish|weiter/i })
                .first().click({ timeout: 8000 });
        } catch { /* single-step flows finish above */ }
        await page.waitForTimeout(15000);

        const entry = await L.entryId();
        L.check('B3b the config entry exists', !!entry, String(entry));

        // ── B4 — and it actually reads
        await new Promise(r => setTimeout(r, 25000));
        const cfg = await L.config();
        L.check('B4 the install stored the key the READER consumes',
                !!cfg.solar_production_sensor && !!cfg.grid_power_sensor,
                `solar=${cfg.solar_production_sensor} grid=${cfg.grid_power_sensor}`);
        for (const [semEntity, srcKey] of [
            ['sensor.sem_solar_power', 'solar_production_sensor'],
            ['sensor.sem_grid_power', 'grid_power_sensor'],
        ]) {
            const semVal = await L.state(semEntity);
            const srcVal = await L.state(cfg[srcKey]);
            L.check(`B4b ${semEntity} reads its source`,
                    semVal !== undefined && srcVal !== undefined
                    && Math.abs(Number(semVal) - Number(srcVal)) < 250,
                    `sem=${semVal} source=${srcVal} (${cfg[srcKey]})`);
        }
    } catch (err) {
        L.check('suite ran to completion', false, err.message);
    } finally {
        // ── B5 — put the rig back
        try {
            if (prefsBackup) {
                await ws(page, { type: 'energy/save_prefs', ...prefsBackup });
                const back = await ws(page, { type: 'energy/get_prefs' });
                L.check('B5 the Energy Dashboard is restored',
                        (back.energy_sources || []).some(s => s.type === 'grid'));
            }
        } catch (e) {
            L.check('B5 the Energy Dashboard is restored', false, e.message);
        }
        await browser.close();
    }
    process.exit(L.summary() ? 0 : 1);
})();
