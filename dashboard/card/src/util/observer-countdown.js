const OBSERVATION_TARGET_SECONDS = 72 * 60 * 60;

/** Format a compact, non-localized observer countdown value. */
export function formatObserverCountdown(value) {
    let seconds = Number(value);
    if (!Number.isFinite(seconds)) seconds = OBSERVATION_TARGET_SECONDS;
    seconds = Math.max(0, Math.ceil(seconds));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}
