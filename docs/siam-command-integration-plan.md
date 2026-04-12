# Siam Command Integration Plan

## Integration constraints
- Additive only.
- Do not replace Claw runtime/command/tool/session implementations.
- Use isolated wrapper mode first.
- Keep all policy in external config files.

## Phase 1 (implemented in this change)
1. Create `src/siam_command` control package.
2. Load policy/whitelist/subsystems from `config/siam/`.
3. Build command/tool/subsystem registries on top of existing Claw surfaces.
4. Add routing policy stage before execution.
5. Add manual override stage before execution.
6. Add structured execution log model and formatter.
7. Add session summary model and formatter.
8. Add health/status surface.
9. Add deferred MusicGen adapter contract.

## Control layer interfaces (dashboard-ready contracts)
- `SubsystemModel`
- `HealthStatusModel`
- `RouteDecisionModel`
- `ExecutionLogModel`
- `SessionSummaryModel`
- `ManualOverrideModel`
- `MusicGenAdapterContract`

## Wrapper call sequence
1. `SiamCommandControlLayer.apply_route_policy(prompt)`
2. `SiamCommandControlLayer.execute_with_control(prompt, payload)`
3. `SiamCommandControlLayer.execution_logs()`
4. `SiamCommandControlLayer.latest_session_summary()`
5. `SiamCommandControlLayer.health_status()`

## Feature isolation strategy
- Layer is exposed by `python -m src.siam_command.main ...`
- Existing `python -m src.main ...` behavior remains untouched.
- Manual override defaults to `normal`.

## Phase 2 (next step)
1. Add API/HTTP surface for dashboard to consume models.
2. Persist Siam execution logs to dedicated storage (separate from `.port_sessions`).
3. Add multi-policy profile support (Techin profile switching).
4. Add real-time event stream surface for route + execute lifecycle.

## Phase 3 (MusicGen mount)
1. Implement concrete adapter that satisfies `MusicGenAdapterContract`.
2. Register MusicGen as subsystem and tool through control layer registry extension.
3. Keep adapter implementation isolated from policy engine.
4. Add integration tests for tool mount and route-policy interaction.

