/** Frontend feature flags (Vite inlines `import.meta.env.VITE_*` at build time). */

function parseEnvFlag(raw: string | undefined, defaultValue: boolean): boolean {
  if (raw === undefined || raw === "") return defaultValue;
  const normalized = raw.trim().toLowerCase();
  if (normalized === "true" || normalized === "1" || normalized === "yes") {
    return true;
  }
  if (normalized === "false" || normalized === "0" || normalized === "no") {
    return false;
  }
  return defaultValue;
}

/**
 * When false, hides the post-conversion Edit button and unregisters `/editor/*`.
 * Set `VITE_EDITOR_ENABLED=false` in `frontend/.env` (or BUILD_TIME env on deploy).
 * Default: enabled.
 */
export const EDITOR_ENABLED = parseEnvFlag(
  import.meta.env.VITE_EDITOR_ENABLED,
  true,
);
