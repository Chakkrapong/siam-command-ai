# Siam Dashboard Handoff

## Objective of this pass
- Provide real, machine-readable output contracts from live Siam/Claw surfaces.
- Avoid UI parsing of ad-hoc text.
- Keep changes additive and reversible.

## Data sources
- Claw command inventory:
  - [src/commands.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\commands.py)
- Claw tool inventory:
  - [src/tools.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\tools.py)
- Claw route candidate engine:
  - [src/runtime.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\runtime.py)
- Claw session accounting:
  - [src/query_engine.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\query_engine.py)
- Siam control registry/policy/state:
  - [src/siam_command/control_layer.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\siam_command\control_layer.py)
  - [src/siam_command/registry.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\siam_command\registry.py)
  - [src/siam_command/policy.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\siam_command\policy.py)
- Serializer contracts:
  - [src/siam_command/serializers.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\siam_command\serializers.py)
- Persistence:
  - [src/siam_command/log_store.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\siam_command\log_store.py)
  - [config/siam/observability.json](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\config\siam\observability.json)

## Output contracts (JSON mode)
- `status` contract:
  - mode, policy_name, command_count, tool_count, allowed_tool_count, subsystem_count, override_mode, last_execution_at
- `list-commands` contract:
  - count, items[]
- `list-tools` contract:
  - available_count, allowed_count, available[], allowed[]
- `list-subsystems` contract:
  - [{name, owner, role, path, status}]
- `route` contract:
  - prompt, selected_command, selected_tool, candidate_commands[], candidate_tools[], blocked_commands[], blocked_tools[], reason, policy_name, decided_at
- `execute` contract:
  - execution_id, timestamp, prompt, selected_command, selected_tool, command_message, tool_message, stop_reason, blocked, policy_name, session_id
- `session` contract:
  - session_id, turn_count, total_input_tokens, total_output_tokens, last_stop_reason, latest_route
- `logs` contract:
  - in_memory[], persisted[]
- `control-state` contract:
  - policy_name, whitelist_tools[], manual_override{}, log_persistence{}

## Suggested API/CLI bridge for dashboard
- Short term:
  - Dashboard shell adapter invokes CLI with `--output json`
  - Parse only JSON outputs from:
    - `status`
    - `list-commands`
    - `list-tools`
    - `list-subsystems`
    - `route`
    - `session`
    - `logs`
    - `control-state`
- Suggested polling split:
  - fast poll: `status`, `session`, `logs`
  - slow poll: `list-commands`, `list-tools`, `list-subsystems`, `control-state`
- For action flow:
  - inspect: `route <prompt>`
  - execute: `execute <prompt> --payload ...`
  - override updates: `override <mode>`

## Risks
- Duplicate names in mirrored command/tool snapshots can require UI disambiguation.
- New control layer instances are process-scoped; in-memory logs/session are not shared across processes.
- Persisted logs are append-only JSONL and can grow without rotation.

## Ready vs not ready
- Ready:
  - JSON output contracts for all dashboard-critical surfaces
  - central serializer contract
  - route decision and execution record surfacing
  - minimal persisted execution logs (JSONL) with config switch
- Not ready:
  - HTTP API server
  - auth/multi-tenant controls for dashboard
  - log rotation/retention policy
  - real MusicGen runtime integration (contract only)

