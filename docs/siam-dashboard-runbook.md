# Siam Dashboard Runbook

## Purpose
- Provide a hardened, read-first Siam control dashboard backed by machine-readable Siam command outputs.
- Keep runtime behavior unchanged; dashboard runs as a separate entrypoint.

## Run dashboard
1. From repository root:
   - `python -m src.siam_dashboard.main serve --host 127.0.0.1 --port 8765`
2. Open:
   - `http://127.0.0.1:8765`
3. Use the **Refresh** button for manual refresh.
4. Use the route/filter form fields for read-only inspection:
   - `route_prompt`
   - `commands_q`
   - `commands_sort`, `commands_order`, `commands_page`, `commands_limit`
   - `tools_q`
   - `tools_sort`, `tools_order`, `tools_page`, `tools_limit`
   - `subsystems_q`
   - `subsystems_sort`, `subsystems_order`, `subsystems_page`, `subsystems_limit`
   - `logs_state`, `logs_source`, `logs_type`, `logs_limit`

## Panel source map
- **System Status**
  - Source command: `python -m src.siam_command.main --output json status`
  - Contract fields: `mode`, `policy_name`, `command_count`, `tool_count`, `allowed_tool_count`, `subsystem_count`, `override_mode`, `last_execution_at`
- **Route / Control State**
  - Route source: `python -m src.siam_command.main --output json route "<prompt>"`
  - Control source: `python -m src.siam_command.main --output json control-state`
  - UI allows route inspect prompt via `route_prompt` query/form value.
  - Control-state fields used:
    - `policy_name`
    - `whitelist_tools`
    - `manual_override`
    - `log_persistence`
- **Execution Logs**
  - Source command: `python -m src.siam_command.main --output json logs`
  - Contract fields used:
    - `in_memory`
    - `persisted`
- **Session Summary**
  - Source command: `python -m src.siam_command.main --output json session`
  - Contract fields used:
    - `session_id`
    - `turn_count`
    - `total_input_tokens`
    - `total_output_tokens`
    - `last_stop_reason`
    - `latest_route`
- **Navigation / Lists**
  - Commands source: `python -m src.siam_command.main --output json list-commands`
  - Tools source: `python -m src.siam_command.main --output json list-tools`
  - Subsystems source: `python -m src.siam_command.main --output json list-subsystems`
- **Command/tool metadata enrichment (read-only)**
  - Commands metadata: `src.siam_core.compat.build_command_catalog_port().list_items()`
  - Tools metadata: `src.siam_core.compat.build_tool_catalog_port().list_items()`
  - Used only to render description/source columns; primary inventory membership remains from Siam JSON contracts.

## State visibility
- Current state reads exposed in the dashboard:
  - whitelist state: `control-state.whitelist_tools`
  - override state: `control-state.manual_override`
  - persistence state: `control-state.log_persistence`
  - route policy summary: `control-state.policy_name` plus `session.latest_route`
  - route decision state: `route` command response for the current inspect prompt

## Readability/hardening in this pass
- Commands/tools/subsystems rendered as structured tables:
  - columns: name, owner, description, source_path
  - count + filter + sort + pagination + dedupe (by lowercased name)
- Route and logs rendered as pretty JSON (`<details>` + `<pre>`).
- Route/log state badges:
  - `success`
  - `blocked`
  - `error`
- Logs view operational controls:
  - filter by `state`
  - filter by `source` (`in_memory`/`persisted`)
  - filter by `type` (`command`/`tool`/`blocked`/`other`)
  - recent N limit
  - summary counters (`success`/`blocked`/`error`)
  - safe redaction/truncation for long text fields
- Overview cards:
  - command count
  - tool count
  - subsystem count
  - persistence enabled/disabled
  - last refresh time
- Per-panel updated timestamps shown in UI.
- Panel-level fault isolation:
  - each panel can fail independently
  - errors shown inline with fallback message
  - whole page still renders
- Session improvements:
  - clearer summary JSON panel
  - read-only recent session history derived from available logs
  - limitation text shown when broader history source is unavailable

## Known limitations
- No realtime streaming; refresh is manual.
- No auth/multi-user controls.
- No write actions in this pass (read-only dashboard surface).
- In-memory session/log state can differ between processes by Siam design.
- Persisted log file growth is append-only (no rotation in this pass).
- Session history is currently derived from available log snapshots; no dedicated historical session store yet.

## I/O safety notes
- Execution log persistence uses best-effort append with retry for transient Windows lock contention.
- If log file read/append is denied, panel falls back safely and dashboard remains available.

## Runtime adapter flag
- Compat layer runtime adapter selection is controlled by `USE_RUNTIME_V2`.
- Default is disabled (`USE_RUNTIME_V2` unset or `0`), preserving current behavior.
- This dashboard phase remains read-only and contract-compatible regardless of flag state.

## Shadow mode (Phase 2)
- Shadow mode is controlled by `USE_RUNTIME_V2_SHADOW`.
- Default is disabled (`USE_RUNTIME_V2_SHADOW` unset or `0`).
- Shadow mode is observational only:
  - legacy runtime remains source of truth
  - runtime v2 result is never returned to caller
  - no routing decision changes
- Scope is limited to allowlisted safe/read-only commands.
- Partial routing is not part of this phase (deferred to Phase 3).

## Operator controls
1. Keep shadow mode disabled (default):
   - `USE_RUNTIME_V2_SHADOW=0`
2. Enable shadow mode for canary observation:
   - `USE_RUNTIME_V2_SHADOW=1`
3. Disable immediately if noise or instability appears:
   - `USE_RUNTIME_V2_SHADOW=0`
4. Optional full runtime-v2 adapter switch remains separate:
   - `USE_RUNTIME_V2=1` changes compat adapter selection (not required for shadow-only validation)

## How to read shadow logs
- Use:
  - `python -m src.siam_command.main --output json logs`
- Inspect each log item fields:
  - `shadow_event`
    - `shadow_match`: legacy/v2 comparable shape/key status matched
    - `shadow_diff`: comparison mismatch detected
    - `shadow_error`: v2 shadow execution raised or failed
    - `shadow_skipped`: shadow did not run (disabled, non-allowlisted, no command, etc.)
  - `shadow_meta`
    - includes concise context such as `reason`, mismatch categories, shape and status indicators, and error class/message

## Partial routing mode (Phase 3)
- Partial routing is controlled by `USE_RUNTIME_V2_PARTIAL`.
- Default is disabled (`USE_RUNTIME_V2_PARTIAL` unset or `0`).
- Rollout percentage is controlled by `RUNTIME_V2_ROLLOUT_PERCENT` (default `0`).
- Scope remains narrow and read-only:
  - only first allowlisted safe commands (`review`, `UltrareviewOverageDialog`)
  - no mutating command rollout in this phase
  - no broad system-wide routing switch
- Behavior for allowlisted commands when partial mode is enabled:
  - runtime_v2 runs first
  - request must be in deterministic rollout bucket (`0-99`) under configured percentage
  - request must pass runtime risk gate
  - runtime_v2 must not be auto-disabled by guardrail
  - contract is validated against legacy output
  - on runtime_v2 error or contract mismatch, fallback to legacy immediately

## Guardrail thresholds (soft-disable only)
- `RUNTIME_V2_GUARDRAIL_MIN_SAMPLE_SIZE=50`
- `RUNTIME_V2_GUARDRAIL_MAX_FALLBACK_RATE=0.05`
- `RUNTIME_V2_GUARDRAIL_MAX_VALIDATION_FAIL_RATE=0.02`
- `RUNTIME_V2_GUARDRAIL_MAX_EXCEPTION_RATE=0.02`
- When unhealthy, routing policy serves legacy (`legacy_default`) with reason `auto_disabled_due_to_guardrail`.

## Safe rollout steps (1% → 5% → 10%)
1. Enable partial mode and start at 1%:
   - `USE_RUNTIME_V2_PARTIAL=1`
   - `RUNTIME_V2_ROLLOUT_PERCENT=1`
2. Observe routing/fallback logs, then increase to 5%:
   - `RUNTIME_V2_ROLLOUT_PERCENT=5`
   - ensure guardrail reason remains `insufficient_sample` or `healthy`
3. If stable, increase to 10%:
   - `RUNTIME_V2_ROLLOUT_PERCENT=10`
   - ensure `v2_error` and `fallback_legacy` rates stay under guardrail limits
4. Emergency rollback:
   - set `RUNTIME_V2_ROLLOUT_PERCENT=0` (keeps partial framework on, serves legacy only)
   - or set `USE_RUNTIME_V2_PARTIAL=0` (fully disable partial routing)

## How to read partial-routing logs
- Use:
  - `python -m src.siam_command.main --output json logs`
- Inspect:
  - `runtime_v2_route_event`
    - `routed_v2`: v2 selected as primary output
    - `fallback_legacy`: v2 not used due to missing command or contract mismatch
    - `v2_error`: v2 raised; legacy fallback used
    - `legacy_default`: partial routing not active for this turn
  - `runtime_v2_route_meta`
    - `reason` plus comparison/error details for operators
    - `runtime_decision.rollout_bucket`, `runtime_decision.rollout_percent`, `runtime_decision.in_rollout`
    - `runtime_decision.risk_level`, `runtime_decision.risk_reason`, `runtime_decision.auto_disabled`
    - `runtime_guardrail.auto_disabled`, `runtime_guardrail.reason`, rates and sample size

## Observation-window gate report
- Build a clean-window report from a fixed open timestamp:
  - `python -m src.siam_command.main --output json observation-window-report --window-open-timestamp <ISO8601>`
- Optional explicit log file path:
  - `--log-path <path-to-jsonl>`
- Decision output is explicit:
  - `MOVE`: rollout-readiness threshold and all gates pass
  - `HOLD`: evidence/sample is insufficient
  - `BLOCK`: review drift, mismatch, unknown errors, rollback activation, or dashboard instance count mismatch
- Current gate set in this command includes:
  - Admin sample thresholds:
    - trend-only: `admin_total_requests >= 20` and `admin_sampled_v2_requests >= 5`
    - rollout-readiness: `admin_total_requests >= 40` and `admin_sampled_v2_requests >= 10`
    - preferred confidence: `admin_total_requests >= 100` and `admin_sampled_v2_requests >= 20`
  - Latency gates:
    - requires `legacy_avg_ms`, `legacy_p95_ms`, `v2_avg_ms`, `v2_p95_ms`
    - `v2_avg_ms <= legacy_avg_ms * 1.10`
    - `v2_p95_ms <= legacy_p95_ms * 1.10`
    - `v2_p95_ms - legacy_p95_ms <= 150`
  - Admin quality gates:
    - `admin_v2_error_count = 0`
    - `admin_unknown_error_kind_count = 0`
    - `admin_shape_mismatch_count = 0`
    - `admin_key_field_mismatch_count = 0`
    - `admin_fallback_rate <= 5%`
    - `unknown_fallback_reason_count = 0`
  - Review integrity gates:
    - `review_other_state_count = 0`
    - `review_sampled_v2_count = 0`
    - `review_default_policy_count = 0`
    - allowed review governance sources only: `route_override`, `conservative_default`
  - Global safety gates:
    - `instance_count = 1`
    - `rollback_active = false`

## Next steps (control center hardening)
- Add client-side table sorting/pagination.
- Add stronger log redaction/privacy controls for large payloads.
- Add retention/rotation controls and filters for persisted logs.
- Add optional HTTP API layer once contracts are stabilized.
