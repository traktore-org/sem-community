/**
 * (#1419) Security devices are never loads. The server's rule lives in
 * features/load_device_discovery.py (security_role); this is its card twin,
 * so the Add a device picker never offers a camera, alarm panel or siren.
 * A device whose only evidence is a lock that Home Assistant does not mark
 * as a setting is a door lock for automatic listing, but the user may still
 * pick it here: they know whether it is an appliance.
 */
export const SECURITY_DOMAINS = ['camera', 'alarm_control_panel', 'siren'];
const SETTING_LOCK_WORDS = ['child_lock', 'childlock', 'child lock', 'key_lock', 'keylock', 'key lock',
    'button_lock', 'panel_lock', 'control_lock', 'kindersicherung', 'tastensperre'];

const domainOf = (id) => String(id || '').split('.')[0];

/** A lock HA marks as an appliance setting: by category, or the integration's own key. */
export function isSettingLock(e) {
    if (['config', 'diagnostic'].includes(String(e?.entity_category || '').toLowerCase())) return true;
    const declared = String(e?.translation_key || '').toLowerCase();
    return SETTING_LOCK_WORDS.some((w) => declared.includes(w));
}

/** 'security' (camera, alarm, siren), 'lock' (an unmarked lock) or ''. */
export function securityRole(hass, entityId) {
    if (!entityId) return '';
    const ents = hass?.entities || {};
    const own = ents[entityId];
    const dev = own?.device_id;
    const entries = dev ? Object.values(ents).filter((e) => e?.device_id === dev) : [own || { entity_id: entityId }];
    if (entries.some((e) => SECURITY_DOMAINS.includes(domainOf(e?.entity_id)))) return 'security';
    if (entries.some((e) => domainOf(e?.entity_id) === 'lock' && !isSettingLock(e))) return 'lock';
    return '';
}

/** Is this entity part of a security device? `chosen`: the user picks it themselves. */
export function isSecurityEntity(hass, entityId, { chosen = false } = {}) {
    const role = securityRole(hass, entityId);
    return role === 'security' || (role === 'lock' && !chosen);
}

/** The Add a device picker: the user chooses, so only camera, alarm and siren devices drop. */
export function withoutSecurity(hass, filter = null) {
    return (st) => !isSecurityEntity(hass, st?.entity_id, { chosen: true }) && (!filter || filter(st));
}
