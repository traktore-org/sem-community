#!/usr/bin/env node
// tests/live/gui/test_915_install_without_energy_dashboard.js
//
// #915 — the install that used to be refused.
//
// An Energy Dashboard that was empty or missing solar/grid ENDED the
// installation: "set it up first, then start again." This suite creates that
// exact situation on the rig and asserts SEM asks the box instead — and,
// crucially, that the install it produces actually READS (the first version
// wrote config keys the reader never consumed, so a clean install reported
// 0 W from a live inverter).
//
//   B0  the Energy Dashboard really is missing its grid source
//   B1  the flow opens the sources step instead of aborting
//   B2  every field is pre-filled, and says which declared key matched
//   B3  submitting it completes the install
//   B4  SEM then reads each source's live value
//   B5  the rig is put back — dashboard restored AND SEM reinstalled
//
// WHY THE ASSERTIONS ARE NOT CLICKS. An earlier version drove the
// Add-integration dialog. It passed twice and then failed twice for a reason
// that had nothing to do with SEM: this change makes SEM offer itself when a
// supported inverter is present, so Home Assistant may put a DISCOVERY card
// on the page seconds after the uninstall — and a discovery flow in progress
// makes the manual route a dead end, while the card is not always there yet.
// Racing that decided whether the suite went green. The step's content is the
// same string either route renders, so it is asserted through the flow API,
// and the browser keeps the visual check as evidence rather than as a gate.
// tests/live/gui/test_915_detected_hardware.js is where clicks are asserted.

const L = require('./lib');
const OUT = process.env.SHOT_DIR || '/tmp';

const ws = (page, msg) => page.evaluate(
    m => document.querySelector('home-assistant').hass.callWS(m), msg);

const flow = (body, id) => L.api(
    id ? `config/config_entries/flow/${id}` : 'config/config_entries/flow',
    { method: 'POST', body: JSON.stringify(body) });

async function deleteSem() {
    const id = await L.entryId();
    if (id) await L.api(`config/config_entries/entry/${id}`, { method: 'DELETE' });
    return !!id;
}

(async () => {
    const { browser, page } = await L.openBrowser();
    let prefsBackup = null;
    try {
        await page.goto(`${L.HOST}/config/integrations`, { waitUntil: 'networkidle' });
        await page.waitForTimeout(4000);

        // ── B0 — a half-set-up house, made through HA's own API
        prefsBackup = await ws(page, { type: 'energy/get_prefs' });
        // Refuse to run on a rig whose dashboard is ALREADY broken: this
        // suite restores what it found, so starting from a broken state
        // would faithfully restore the breakage — and then the next run
        // would inherit it, which is exactly how .46 ended up without a grid
        // source for two runs.
        if (!(prefsBackup.energy_sources || []).some(s => s.type === 'grid')) {
            L.check('B00 the rig starts with a complete Energy Dashboard', false,
                    'no grid source before the test — restore it first, '
                    + 'this suite will not "restore" a broken dashboard');
            prefsBackup = null;
            throw new Error('rig precondition');
        }
        await ws(page, {
            type: 'energy/save_prefs', ...prefsBackup,
            energy_sources: (prefsBackup.energy_sources || [])
                .filter(s => s.type !== 'grid'),
        });
        const after = await ws(page, { type: 'energy/get_prefs' });
        L.check('B0 the Energy Dashboard now has no grid source',
                !(after.energy_sources || []).some(s => s.type === 'grid'));

        // HA writes energy prefs through a DELAYED store and SEM reads the
        // file. Without this settle the first run of this suite deleted the
        // grid source, immediately started the flow, got the ordinary
        // Energy-Dashboard path, and passed while testing nothing.
        await page.waitForTimeout(35000);

        L.check('B0b SEM was removed for a clean install', await deleteSem());
        await page.waitForTimeout(8000);

        // Home Assistant may already have started a DISCOVERY flow for SEM by
        // now — this change makes SEM offer itself when a supported inverter
        // is present. A second flow for the same unique id aborts with
        // `already_in_progress`, which made this suite fail on the run after
        // a run rather than on any change to SEM. Clear whatever is pending
        // and start from a known state.
        try {
            const pending = await ws(page, { type: 'config_entries/flow/progress' });
            for (const f of (pending || [])) {
                if (f.handler === 'solar_energy_management') {
                    await L.api(`config/config_entries/flow/${f.flow_id}`,
                                { method: 'DELETE' });
                }
            }
            await page.waitForTimeout(3000);
        } catch { /* nothing pending */ }

        // ── B1/B2 — the step and what it says
        const step = await flow({ handler: 'solar_energy_management',
                                  show_advanced_options: false });
        L.check('B1 an incomplete Energy Dashboard does not end the install',
                step.type !== 'abort', step.reason || step.type);
        L.check('B1b the sources step is shown', step.step_id === 'sources',
                step.step_id);
        const summary = (step.description_placeholders || {}).summary || '';
        L.check('B2 it says what it recognised, and why',
                summary.includes('declared as'), summary.slice(0, 90));
        for (const [what, key] of [['solar', 'input_power'],
                                   ['grid', 'meter_active_power'],
                                   ['battery', 'storage_charge_discharge_power'],
                                   ['battery charge', 'state_of_capacity']]) {
            L.check(`B2b the ${what} sensor is pre-filled from a declared key`,
                    summary.includes(key), key);
        }

        // the same form, rendered — evidence, not a gate
        try {
            await page.reload({ waitUntil: 'networkidle' });
            await page.waitForTimeout(3000);
            const seen = (await L.deepText(page)).includes('Solar Energy Management');
            console.log(`note: integrations page shows SEM: ${seen}`);
            await page.screenshot({ path: `${OUT}/915_B_integrations_page.png` });
        } catch { /* evidence only */ }

        // A meter with no combined sensor has to be able to finish too
        // (Growatt, Senec, Anker official publish two positive sensors and
        // no signed one). The pair is offered on the same step.
        const fields = (step.data_schema || []).map((f) => f.name);
        L.check('B2c the split pair is offered for meters with no signed sensor',
                fields.includes('grid_import_power_entity')
                && fields.includes('grid_export_power_entity'),
                fields.join(','));
        const halfPair = await flow({
            solar_power_sensor: 'sensor.inverter_eingangsleistung',
            grid_import_power_entity: 'sensor.power_meter_wirkleistung',
        }, step.flow_id);
        L.check('B2d half a split pair is refused',
                !!(halfPair.errors || {}).grid_export_power_entity,
                JSON.stringify(halfPair.errors || {}));

        // ── B3 — submit what it proposed
        const next = await flow({
            solar_power_sensor: 'sensor.inverter_eingangsleistung',
            grid_import_power_sensor: 'sensor.power_meter_wirkleistung',
            battery_power_sensor: 'sensor.batteries_lade_entladeleistung',
            battery_soc_sensor: 'sensor.batteries_batterieladung',
            observer_mode: true,
        }, step.flow_id);
        L.check('B3 the pre-filled form is accepted',
                !next.errors || !Object.keys(next.errors).length,
                JSON.stringify(next.errors || {}));
        // Walk the remaining steps rather than assuming one: how many there
        // are depends on what the rig has. Running this straight after the
        // near-miss suite (which adds and removes a charger) produced an
        // extra step, and submitting once left the flow open — reported as
        // "the install completes: form", which is a test that stopped early
        // rather than a product that failed.
        let done = next;
        for (let i = 0; i < 5 && done && done.type === 'form'; i++) {
            done = await flow({}, step.flow_id);
        }
        L.check('B3b the install completes', done.type === 'create_entry',
                `${done.type}${done.step_id ? ' @' + done.step_id : ''}`);
        await new Promise(r => setTimeout(r, 30000));

        // ── B4 — and it actually reads
        const cfg = await L.config();
        L.check('B4 the install stored the key the READER consumes',
                !!cfg.solar_production_sensor && !!cfg.grid_power_sensor,
                `solar=${cfg.solar_production_sensor} grid=${cfg.grid_power_sensor}`);
        for (const [semEntity, srcKey] of [
            ['sensor.sem_solar_power', 'solar_production_sensor'],
            ['sensor.sem_grid_power', 'grid_power_sensor'],
        ]) {
            // Sample the SOURCE either side of SEM's own reading and accept
            // anything inside that envelope. Comparing two entities sampled
            // at different instants is not a test of wiring on a rig whose
            // grid value moves every cycle — it is a test of how fast the
            // sun went behind a cloud, and it failed exactly that way.
            const agree = await L.until(async () => {
                const a = Number(await L.state(cfg[srcKey]));
                const sem = await L.state(semEntity);
                const b = Number(await L.state(cfg[srcKey]));
                if (sem === undefined || sem === 'unavailable' || sem === 'unknown') return null;
                const v = Number(sem);
                const lo = Math.min(a, b) - 250, hi = Math.max(a, b) + 250;
                return (v >= lo && v <= hi) ? { v, a, b } : null;
            });
            L.check(`B4b ${semEntity} reads its source`, !!agree,
                    agree ? `sem=${agree.v} source=${agree.a}..${agree.b} (${cfg[srcKey]})`
                          : `never inside the source's own range (${cfg[srcKey]})`);
        }
    } catch (err) {
        L.check('suite ran to completion', false, err.message);
    } finally {
        // ── B5 — put the rig back, whatever happened above. This suite
        // deletes the integration; a failure in the middle used to leave .46
        // with no SEM at all and every other suite failing for reasons that
        // had nothing to do with them.
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
        try {
            if (!(await L.entryId())) {
                const f = await flow({ handler: 'solar_energy_management',
                                       show_advanced_options: false });
                let st = f;
                for (let i = 0; i < 4 && st && st.type === 'form'; i++) {
                    st = await flow(st.step_id === 'sources' ? {
                        solar_power_sensor: 'sensor.inverter_eingangsleistung',
                        grid_import_power_sensor: 'sensor.power_meter_wirkleistung',
                        battery_power_sensor: 'sensor.batteries_lade_entladeleistung',
                        battery_soc_sensor: 'sensor.batteries_batterieladung',
                        observer_mode: true,
                    } : {}, f.flow_id);
                }
                await new Promise(r => setTimeout(r, 20000));
            }
            L.check('B5b the rig has SEM installed when this suite ends',
                    !!(await L.entryId()));
        } catch (e) {
            L.check('B5b the rig has SEM installed when this suite ends', false, e.message);
        }
        await browser.close();
    }
    process.exit(L.summary() ? 0 : 1);
})();
