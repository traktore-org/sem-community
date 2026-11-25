/**
 * (#1381) Is this card older than the SEM the server runs?
 *
 * The server registers the bundle as `.../sem-cards.js?v=<version>-<hash>`
 * and publishes the same token on `sensor.sem_diag_version` (attribute
 * `card`). A phone app that kept the previous bundle in its cache runs the
 * old card against the new server; on 25.11 that drew one mode button and a
 * tap on it stopped a night charge. The card reads its own token from the
 * URL it was loaded from and asks for a reload when the two differ.
 */
let own = (() => {
    try { return new URL(import.meta.url).searchParams.get('v') || ''; } catch (e) { return ''; }
})();

/** The token this bundle was loaded with ('' when it carries none, e.g. in tests). */
export function ownCardVersion() { return own; }

/** Tests only: pretend the bundle was loaded with this token. */
export function setOwnCardVersion(v) { own = String(v || ''); }

/** Stale only when both tokens are known and differ: an unknown never nags. */
export function staleCard(mine, server) {
    return !!mine && !!server && String(mine) !== String(server);
}
