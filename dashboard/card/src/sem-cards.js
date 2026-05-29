/**
 * SEM Cards — Single bundled entry point
 *
 * All SEM custom cards are imported here and bundled by Rollup
 * into a single sem-cards.js file for Lovelace resource registration.
 */

// Display cards
import './cards/sem-title-card.js';
import './cards/sem-tab-header.js';
import './cards/sem-weather-card.js';
import './cards/sem-period-selector-card.js';
import './cards/sem-energy-impact-card.js';
import './cards/sem-ev-progress-card.js';
import './cards/sem-gauge-card.js';

// Hero / SVG cards
import './cards/sem-solar-card.js';
import './cards/sem-solar-summary-card.js';
import './cards/sem-battery-card.js';
import './cards/sem-grid-card.js';
import './cards/sem-schedule-card.js';

// Interactive cards
import './cards/sem-battery-zones-card.js';
import './cards/sem-costs-card.js';
import './cards/sem-costs-detail-card.js';
import './cards/sem-charger-status-card.js';
import './cards/sem-ev-status-card.js';
import './cards/sem-home-status-card.js';
import './cards/sem-price-card.js';
import './cards/sem-system-card.js';
import './cards/sem-today-plan-card.js';

// Complex cards (observers, animations, external libs)
import './cards/sem-flow-card.js';
import './cards/sem-system-diagram-card.js';
import './cards/sem-chart-card.js';
import './cards/sem-load-priority-card.js';
import './cards/sem-control-card.js';

// Version info
console.info(
    '%c SEM Cards %c Lit Bundle ',
    'color: #4db6ac; font-weight: bold; background: #1e232d; padding: 2px 6px; border-radius: 4px 0 0 4px;',
    'color: #ff9800; background: #1e232d; padding: 2px 6px; border-radius: 0 4px 4px 0;'
);
