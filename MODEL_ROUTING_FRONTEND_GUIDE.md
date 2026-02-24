# Frontend Guide: Video Model Tiers and Routing

The backend now exposes tier-based model routing to simplify model selection UX while preserving support for explicit model picks.

## Routing modes
- `fast` (default): `wan-video/wan2.6-i2v-flash`
- `premium`: `kwaivgi/kling-v2.6`
- `budget`: `bytedance/seedance-1-pro-fast`
- `legacyFallback`: `wan-video/wan-2.2-s2v`

## API contract updates
`GET /models` now includes `tier`, `capabilities`, and `routing_defaults` for each model response entry. Keep the fast tier first in UI and group options by tier order: **Fast**, **Premium**, **Budget**, **Legacy**.

## Backward compatibility behavior
If the frontend or stored data still sends an older slug, the backend normalizes it automatically before validation and job submission:
- `minimax/hailuo-02` → `minimax/hailuo-2.3`
- `kwaivgi/kling-v2.1` → `kwaivgi/kling-v2.6`
- `bytedance/seedance-1-lite` → `bytedance/seedance-1-pro-fast`
- `wan-video/wan-2.1` → `wan-video/wan2.6-i2v-flash`

Unknown slugs also safely fall back to the `fast` route default.
