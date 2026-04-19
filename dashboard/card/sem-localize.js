/**
 * SEM Localization — shared translation tables for all SEM dashboard cards
 *
 * Usage in cards:
 *   const _t = (key) => semLocalize(key, this._hass?.language);
 *   this.shadowRoot.querySelector('.label').textContent = _t('charging');
 */

const SEM_TRANSLATIONS = {
    en: {
        // Status
        charging: 'Charging', discharging: 'Discharging', idle: 'Idle',
        connected: 'Connected', disconnected: 'Disconnected',
        importing: 'Import', exporting: 'Export', grid: 'Grid',

        // Tab headers
        home: 'Home', energy: 'Energy', battery: 'Battery',
        ev_charging: 'EV Charging', control: 'Control', costs: 'Costs', system: 'System',

        // Tab subtitles
        home_sub: 'Energy overview', energy_sub: 'Production & consumption',
        battery_sub: 'Storage & health', ev_sub: 'Vehicle & sessions',
        control_sub: 'Devices & scheduling', costs_sub: 'Savings & tariffs',
        system_sub: 'Health & diagnostics',

        // Metric labels
        solar: 'Solar', autarky: 'Autarky', today: 'Today', soc: 'SOC',
        power: 'Power', health: 'Health', cycles: 'Cycles', temperature: 'Temperature',
        status: 'Status', session: 'Session', current: 'Current',
        solar_share: 'Solar share', strategy: 'Strategy', peak: 'Peak',
        devices: 'Devices', active: 'Active', cost: 'Cost', saved: 'Saved', net: 'Net',
        score: 'Score', co2: 'CO₂', self_use: 'Self-use',

        // Battery card
        charge_today: 'Charge today', discharge_today: 'Discharge today',
        savings_today: 'Savings today',

        // EV card
        session_cost: 'Session cost', no_vehicle: 'No vehicle connected',

        // Schedule card
        tariff: 'Tariff', night: 'Night', surplus: 'Surplus', ev: 'EV',
        ht: 'HT', nt: 'NT',

        // Device control modes
        mode: 'Mode', off: 'Off', peak_only: 'Peak Only',
        surplus_mode: 'Surplus', critical: 'Critical',

        // Units
        kwh: 'kWh', w: 'W', kw: 'kW',
    },
    de: {
        charging: 'Laden', discharging: 'Entladen', idle: 'Leerlauf',
        connected: 'Verbunden', disconnected: 'Getrennt',
        importing: 'Import', exporting: 'Export', grid: 'Netz',

        home: 'Übersicht', energy: 'Energie', battery: 'Batterie',
        ev_charging: 'EV-Laden', control: 'Steuerung', costs: 'Kosten', system: 'System',

        home_sub: 'Energieübersicht', energy_sub: 'Erzeugung & Verbrauch',
        battery_sub: 'Speicher & Gesundheit', ev_sub: 'Fahrzeug & Sitzungen',
        control_sub: 'Geräte & Planung', costs_sub: 'Ersparnis & Tarife',
        system_sub: 'Zustand & Diagnose',

        solar: 'Solar', autarky: 'Autarkie', today: 'Heute', soc: 'SOC',
        power: 'Leistung', health: 'Zustand', cycles: 'Zyklen', temperature: 'Temperatur',
        status: 'Status', session: 'Sitzung', current: 'Strom',
        solar_share: 'Solaranteil', strategy: 'Strategie', peak: 'Spitze',
        devices: 'Geräte', active: 'Aktiv', cost: 'Kosten', saved: 'Gespart', net: 'Netto',
        score: 'Bewertung', co2: 'CO₂', self_use: 'Eigenverbrauch',

        charge_today: 'Ladung heute', discharge_today: 'Entladung heute',
        savings_today: 'Ersparnis heute',

        session_cost: 'Sitzungskosten', no_vehicle: 'Kein Fahrzeug verbunden',

        tariff: 'Tarif', night: 'Nacht', surplus: 'Überschuss', ev: 'EV',
        ht: 'HT', nt: 'NT',

        mode: 'Modus', off: 'Aus', peak_only: 'Nur Spitze',
        surplus_mode: 'Überschuss', critical: 'Kritisch',

        kwh: 'kWh', w: 'W', kw: 'kW',
    },
    fr: {
        charging: 'En charge', discharging: 'Décharge', idle: 'Inactif',
        connected: 'Connecté', disconnected: 'Déconnecté',
        importing: 'Import', exporting: 'Export', grid: 'Réseau',

        home: 'Accueil', energy: 'Énergie', battery: 'Batterie',
        ev_charging: 'Charge VE', control: 'Contrôle', costs: 'Coûts', system: 'Système',

        home_sub: "Vue d'ensemble", energy_sub: 'Production & consommation',
        battery_sub: 'Stockage & santé', ev_sub: 'Véhicule & sessions',
        control_sub: 'Appareils & planification', costs_sub: 'Économies & tarifs',
        system_sub: 'Santé & diagnostic',

        solar: 'Solaire', autarky: 'Autarcie', today: "Aujourd'hui", soc: 'SOC',
        power: 'Puissance', health: 'Santé', cycles: 'Cycles', temperature: 'Température',
        status: 'État', session: 'Session', current: 'Courant',
        solar_share: 'Part solaire', strategy: 'Stratégie', peak: 'Pointe',
        devices: 'Appareils', active: 'Actifs', cost: 'Coût', saved: 'Économisé', net: 'Net',
        score: 'Score', co2: 'CO₂', self_use: 'Autoconsommation',

        charge_today: "Charge aujourd'hui", discharge_today: "Décharge aujourd'hui",
        savings_today: "Économies aujourd'hui",

        session_cost: 'Coût session', no_vehicle: 'Aucun véhicule connecté',

        tariff: 'Tarif', night: 'Nuit', surplus: 'Surplus', ev: 'VE',
        ht: 'HP', nt: 'HC',

        mode: 'Mode', off: 'Arrêt', peak_only: 'Pointe seule',
        surplus_mode: 'Surplus', critical: 'Critique',

        kwh: 'kWh', w: 'W', kw: 'kW',
    },
    es: {
        charging: 'Cargando', discharging: 'Descargando', idle: 'Inactivo',
        connected: 'Conectado', disconnected: 'Desconectado',
        importing: 'Importación', exporting: 'Exportación', grid: 'Red',

        home: 'Inicio', energy: 'Energía', battery: 'Batería',
        ev_charging: 'Carga VE', control: 'Control', costs: 'Costes', system: 'Sistema',

        home_sub: 'Vista general', energy_sub: 'Producción y consumo',
        battery_sub: 'Almacenamiento y salud', ev_sub: 'Vehículo y sesiones',
        control_sub: 'Dispositivos y planificación', costs_sub: 'Ahorro y tarifas',
        system_sub: 'Salud y diagnóstico',

        solar: 'Solar', autarky: 'Autarquía', today: 'Hoy', soc: 'SOC',
        power: 'Potencia', health: 'Salud', cycles: 'Ciclos', temperature: 'Temperatura',
        status: 'Estado', session: 'Sesión', current: 'Corriente',
        solar_share: 'Cuota solar', strategy: 'Estrategia', peak: 'Pico',
        devices: 'Dispositivos', active: 'Activos', cost: 'Coste', saved: 'Ahorrado', net: 'Neto',
        score: 'Puntuación', co2: 'CO₂', self_use: 'Autoconsumo',

        charge_today: 'Carga hoy', discharge_today: 'Descarga hoy',
        savings_today: 'Ahorro hoy',

        session_cost: 'Coste sesión', no_vehicle: 'Ningún vehículo conectado',

        tariff: 'Tarifa', night: 'Noche', surplus: 'Excedente', ev: 'VE',
        ht: 'HP', nt: 'HV',

        mode: 'Modo', off: 'Apagado', peak_only: 'Solo pico',
        surplus_mode: 'Excedente', critical: 'Crítico',

        kwh: 'kWh', w: 'W', kw: 'kW',
    },
    it: {
        charging: 'In carica', discharging: 'Scarica', idle: 'Inattivo',
        connected: 'Connesso', disconnected: 'Disconnesso',
        importing: 'Importazione', exporting: 'Esportazione', grid: 'Rete',

        home: 'Home', energy: 'Energia', battery: 'Batteria',
        ev_charging: 'Carica VE', control: 'Controllo', costs: 'Costi', system: 'Sistema',

        home_sub: "Panoramica energia", energy_sub: 'Produzione e consumo',
        battery_sub: 'Accumulo e salute', ev_sub: 'Veicolo e sessioni',
        control_sub: 'Dispositivi e pianificazione', costs_sub: 'Risparmio e tariffe',
        system_sub: 'Salute e diagnostica',

        solar: 'Solare', autarky: 'Autarchia', today: 'Oggi', soc: 'SOC',
        power: 'Potenza', health: 'Salute', cycles: 'Cicli', temperature: 'Temperatura',
        status: 'Stato', session: 'Sessione', current: 'Corrente',
        solar_share: 'Quota solare', strategy: 'Strategia', peak: 'Picco',
        devices: 'Dispositivi', active: 'Attivi', cost: 'Costo', saved: 'Risparmiato', net: 'Netto',
        score: 'Punteggio', co2: 'CO₂', self_use: 'Autoconsumo',

        charge_today: 'Carica oggi', discharge_today: 'Scarica oggi',
        savings_today: 'Risparmio oggi',

        session_cost: 'Costo sessione', no_vehicle: 'Nessun veicolo connesso',

        tariff: 'Tariffa', night: 'Notte', surplus: 'Eccedenza', ev: 'VE',
        ht: 'FP', nt: 'FV',

        mode: 'Modalità', off: 'Spento', peak_only: 'Solo picco',
        surplus_mode: 'Eccedenza', critical: 'Critico',

        kwh: 'kWh', w: 'W', kw: 'kW',
    },
    nl: {
        charging: 'Laden', discharging: 'Ontladen', idle: 'Inactief',
        connected: 'Verbonden', disconnected: 'Ontkoppeld',
        importing: 'Import', exporting: 'Export', grid: 'Net',

        home: 'Home', energy: 'Energie', battery: 'Batterij',
        ev_charging: 'EV laden', control: 'Bediening', costs: 'Kosten', system: 'Systeem',

        home_sub: 'Energieoverzicht', energy_sub: 'Productie & verbruik',
        battery_sub: 'Opslag & gezondheid', ev_sub: 'Voertuig & sessies',
        control_sub: 'Apparaten & planning', costs_sub: 'Besparing & tarieven',
        system_sub: 'Gezondheid & diagnose',

        solar: 'Zon', autarky: 'Autarkie', today: 'Vandaag', soc: 'SOC',
        power: 'Vermogen', health: 'Gezondheid', cycles: 'Cycli', temperature: 'Temperatuur',
        status: 'Status', session: 'Sessie', current: 'Stroom',
        solar_share: 'Zonneaandeel', strategy: 'Strategie', peak: 'Piek',
        devices: 'Apparaten', active: 'Actief', cost: 'Kosten', saved: 'Bespaard', net: 'Netto',
        score: 'Score', co2: 'CO₂', self_use: 'Eigenverbruik',

        charge_today: 'Laden vandaag', discharge_today: 'Ontladen vandaag',
        savings_today: 'Besparing vandaag',

        session_cost: 'Sessiekosten', no_vehicle: 'Geen voertuig verbonden',

        tariff: 'Tarief', night: 'Nacht', surplus: 'Overschot', ev: 'EV',
        ht: 'HT', nt: 'LT',

        mode: 'Modus', off: 'Uit', peak_only: 'Alleen piek',
        surplus_mode: 'Overschot', critical: 'Kritiek',

        kwh: 'kWh', w: 'W', kw: 'kW',
    },
};

/**
 * Get translated string for the given key and language.
 * Falls back to English if key not found in target language.
 */
function semLocalize(key, lang) {
    const t = SEM_TRANSLATIONS[lang] || SEM_TRANSLATIONS.en;
    return t[key] || SEM_TRANSLATIONS.en[key] || key;
}

// Export globally for all SEM cards
if (typeof window !== 'undefined') {
    window.SEM_TRANSLATIONS = SEM_TRANSLATIONS;
    window.semLocalize = semLocalize;
}
