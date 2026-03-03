# Known Gaps / Follow-ups

## High-priority follow-ups
1. **Add explicit validation bounds for `seconds`, `fps`, and `resolution` in request models**
   - Why: payloads are normalized downstream, but early request validation would provide faster and clearer user-facing errors.
   - Suggested action: add constrained Pydantic fields (e.g., allowed range for seconds/fps and enum-like validation for resolution).

2. **Add focused tests for invalid camelCase payload permutations**
   - Why: current tests assert happy-path camelCase support, but do not exhaust malformed/mixed input edge cases.
   - Suggested action: add negative tests for wrong types and incompatible combinations of `model_override` and `modelParams`.

3. **Document `/resolve_model` response contract in API docs**
   - Why: frontend relies on metadata keys (`resolved_defaults`, `meta.tunable_params`, `plan_tier`) that should be explicitly versioned/documented.
   - Suggested action: add a dedicated section to `README.md` with request/response examples and compatibility notes.

## Medium-priority follow-ups
4. **Add structured request correlation for model-routing logs**
   - Why: troubleshooting routing mismatches across providers is easier with consistent request IDs in routing logs.
   - Suggested action: thread `request_id` through `/resolve_model` and log model selection decisions at INFO level (without user PII).

5. **Add regression test for plan-tier fallbacks when Supabase profile lookup fails**
   - Why: plan resolution is critical for gating; edge-case behavior should remain deterministic under datastore failures.
   - Suggested action: patch lookup failure paths and assert fallback tier behavior.
