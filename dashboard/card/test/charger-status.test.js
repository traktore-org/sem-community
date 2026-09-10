/**
 * (#944) A stop-war stand-down must not pass for an ordinary charge.
 */
import { test } from 'node:test';
import assert from 'node:assert';
import { chargerStatusKey } from '../src/util/charger-status.js';

test('a stand-down with the car drawing says so', () => {
    assert.equal(chargerStatusKey({
        isCharging: true, isConnected: true,
        standDown: { standing_down: true, remaining_s: 1200, power_w: 4100 },
    }), 'charger_status_stood_down');
});

test('an ordinary charge is still "charging"', () => {
    assert.equal(chargerStatusKey({
        isCharging: true, isConnected: true, standDown: { standing_down: false },
    }), 'charging');
    assert.equal(chargerStatusKey({ isCharging: true, isConnected: true }), 'charging');
});

test('no draw is never a stand-down, whatever the attribute says', () => {
    // The backend clears it the moment the draw stops; a stale attribute on
    // an idle box must not make the tile claim a charge.
    assert.equal(chargerStatusKey({
        isCharging: false, isConnected: true, standDown: { standing_down: true },
    }), 'connected');
    assert.equal(chargerStatusKey({ isCharging: false, isConnected: false }), 'idle');
});

test('a truthy non-boolean is not a stand-down', () => {
    assert.equal(chargerStatusKey({
        isCharging: true, isConnected: true, standDown: { standing_down: 'false' },
    }), 'charging');
});
