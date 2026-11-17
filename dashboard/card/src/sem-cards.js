/**
 * SEM Cards — Single bundled entry point
 *
 * All SEM custom cards are imported here and bundled by Rollup
 * into a single sem-cards.js file for Lovelace resource registration.
 */

// The SEM dashboard (#1321): five screens by question
import './cards/sem-next-now-card.js';
import './cards/sem-next-plan-card.js';
import './cards/sem-next-devices-card.js';
import './cards/sem-next-insights-card.js';
import './cards/sem-next-system-card.js';
import './cards/sem-setup-checklist-card.js';
import './cards/sem-simulation-card.js';

// Tags of removed cards: a small notice instead of a red error card
import './cards/sem-retired-card.js';

// Version info
console.info(
    '%c SEM Cards %c Lit Bundle ',
    'color: #4db6ac; font-weight: bold; background: #1e232d; padding: 2px 6px; border-radius: 4px 0 0 4px;',
    'color: #ff9800; background: #1e232d; padding: 2px 6px; border-radius: 0 4px 4px 0;'
);
