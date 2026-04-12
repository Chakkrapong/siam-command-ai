# Siam De-Claw Migration Status (Safe Increment)

## Dependency map (current)
- `src.siam_command.control_layer`
  - runtime route: `src.siam_core.compat.build_runtime_port()`
  - session: `src.siam_core.compat.build_session_port()`
  - execution registry: `src.siam_core.compat.build_execution_registry_port()`
  - command catalog: `src.siam_core.compat.build_command_catalog_port()`
  - tool catalog: `src.siam_core.compat.build_tool_catalog_port()`
  - subsystem catalog: `src.siam_core.compat.build_subsystem_catalog_port()`
- `src.siam_command.registry`
  - uses interface ports (`CommandCatalogPort`, `ToolCatalogPort`, `SubsystemCatalogPort`)
  - legacy constructors (`from_claw`) now route through compatibility adapters
- `src.siam_dashboard.adapters`
  - command/tool metadata now fetched from siam-native compatibility ports, not direct `src.commands`/`src.tools` imports

## De-coupled in this pass
- Introduced Siam-native interface contracts:
  - `RuntimeRoutePort`
  - `CommandCatalogPort`
  - `ToolCatalogPort`
  - `SessionPort`
  - `ExecutionRegistryPort`
  - `SubsystemCatalogPort`
- Added compatibility layer wrapping existing Claw-derived modules:
  - `src/siam_core/compat.py`
- Switched Siam command/dashboard call sites to consume interfaces first.
- Added `runtime_v2` adapter layer (separate from current compat implementation).
- Added feature flag gate: `USE_RUNTIME_V2` (default false) in `src.siam_core.compat`.
- Added feature flag gate: `USE_RUNTIME_V2_SHADOW` (default false) in `src.siam_core.compat`.
- Added command shadow helper:
  - `src.siam_core.runtime_shadow.should_shadow_command`
  - `src.siam_core.runtime_shadow.execute_shadow_for_command`
  - `src.siam_core.runtime_shadow.compare_legacy_vs_v2`
- Added read-only command allowlist for shadow execution (currently conservative).
- Added shadow event fields to execution logs:
  - `shadow_event`: `shadow_match` | `shadow_diff` | `shadow_error` | `shadow_skipped`
  - `shadow_meta`: concise structured metadata for operator debugging

## Phase 2 status: shadow-only execution
- Legacy runtime remains the only source of truth for command output and routing.
- When enabled, runtime v2 runs only in post-response shadow mode for allowlisted read-only commands.
- Shadow output is never returned to caller and does not affect route selection.
- Shadow exceptions are swallowed and logged as `shadow_error`.
- No production routing change in this phase.

## Still coupled (by design, temporary)
- Compatibility adapters still source data/behavior from:
  - `src.runtime.PortRuntime`
  - `src.query_engine.QueryEnginePort`
  - `src.execution_registry.build_execution_registry`
  - `src.commands.get_commands`
  - `src.tools.get_tools`
  - `src.port_manifest.build_port_manifest`
- This keeps behavior stable while reducing direct dependency spread.

## Safety notes
- No runtime flow rewrite.
- No deletion of legacy Claw-derived modules.
- Siam CLI JSON/read-only dashboard contracts preserved.
- Execution log persistence hardened for Windows-safe behavior:
  - append retry on transient file lock
  - permission-safe read fallback
  - corrupt/partial JSONL line skip
- `USE_RUNTIME_V2` only changes adapter selection in compat layer; default remains legacy compat path.
- `USE_RUNTIME_V2_SHADOW` only enables shadow evaluation/logging; default remains disabled.

## Deferred to Phase 3
- Any partial routing / selective production handoff to runtime v2.
- Any use of runtime v2 output as user-visible/source-of-truth response.

## Phase 3a — Narrow Partial Routing
- runtime_v2 may serve as primary only for explicit read-only allowlisted commands, with legacy contract verification and immediate fallback to legacy on error or mismatch.
- Added `USE_RUNTIME_V2_PARTIAL` (default false).
- Partial routing allowlist is intentionally narrow (first 1-2 read-only commands):
  - `review`
  - `UltrareviewOverageDialog`
- For allowlisted commands only:
  - runtime_v2 executes as primary candidate
  - contract is validated against legacy output
  - on `runtime_v2` error or contract mismatch, system falls back to legacy immediately
- New execution-log routing fields:
  - `runtime_v2_route_event`: `routed_v2` | `fallback_legacy` | `v2_error` | `legacy_default`
  - `runtime_v2_route_meta`: concise reason + comparison/error context
- No expansion to mutating commands.
- No broad global switch introduced in this phase.

## Phase 3c: progressive rollout (stable bucketing)
- Added `RUNTIME_V2_ROLLOUT_PERCENT` (default `0`) as percentage gate for partial routing.
- Added deterministic stable bucketing (`0-99`) for rollout assignment.
- runtime_v2 primary routing now requires all:
  - partial enabled
  - command allowlisted
  - request/session key in rollout bucket
- `RUNTIME_V2_ROLLOUT_PERCENT=0` keeps all traffic on legacy.
- Validation/fallback flow and route events remain unchanged.

## Phase 3c — Progressive Rollout Active
- runtime_v2 routing is now gated by partial enablement, narrow allowlist, and deterministic rollout bucketing, while validation/fallback behavior remains unchanged.
