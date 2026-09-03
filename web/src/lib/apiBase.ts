/**
 * Single shared origin for the public read API.
 *
 * In development a missing NEXT_PUBLIC_API_BASE_URL falls back to the local
 * FastAPI default so `pnpm dev` works out of the box. In production builds the
 * fallback is removed: API_BASE becomes null and every surface renders an
 * explicit configuration-error state instead of silently calling localhost.
 */
const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim()

export const API_BASE: string | null =
  configured && configured.length > 0
    ? configured.replace(/\/+$/, "")
    : process.env.NODE_ENV === "production"
      ? null
      : "http://localhost:8000"

export const API_BASE_CONFIGURED = API_BASE !== null

export const API_CONFIG_ERROR =
  "NEXT_PUBLIC_API_BASE_URL is not configured for this production build. Set it to the public read API origin and rebuild; no localhost fallback is used in production."
