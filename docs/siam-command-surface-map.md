# Siam Command Surface Map (Discovery Pass)

This map is derived from real code and real CLI output from:
- `python -m src.siam_command.main --help`
- `python -m src.siam_command.main <subcommand> --help`
- text and JSON executions of each surface command

## Entrypoints inspected
- [src/siam_command/main.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\siam_command\main.py)
- [src/siam_command/control_layer.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\siam_command\control_layer.py)
- [src/siam_command/config.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\siam_command\config.py)
- [src/siam_command/serializers.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\siam_command\serializers.py)
- [src/siam_command/log_store.py](E:\claw-code-by-ultraworkers-main\claw-code-by-ultraworkers-main\src\siam_command\log_store.py)

## Global CLI options
- `--output {text,json}` (default `text`)

## Subcommands from real `--help`
- `status`: show control-layer health/status
- `list-commands`: list available claw commands
- `list-tools`: list available and allowed tools
- `list-subsystems`: list subsystem catalog
- `route <prompt>`: apply route policy only
- `execute <prompt> [--payload PAYLOAD]`: apply policy then execute
- `override {normal,block_all_tools,allow_only}`: set manual override mode
- `session`: show latest session summary
- `logs`: show structured execution logs
- `control-state`: show policy, whitelist, override, and persistence state

## Arguments by command
- `route`:
  - positional: `prompt`
- `execute`:
  - positional: `prompt`
  - optional: `--payload`
- `override`:
  - positional enum: `normal | block_all_tools | allow_only`
- all others:
  - no command-specific args

## Return surfaces (observed)
### `status`
- text: dict-like string
- json: object fields
  - `mode`
  - `policy_name`
  - `command_count`
  - `tool_count`
  - `allowed_tool_count`
  - `subsystem_count`
  - `override_mode`
  - `last_execution_at`

### `list-commands`
- text: one command name per line
- json:
  - `count`
  - `items` (array of command names)

### `list-tools`
- text:
  - `available:` section
  - `allowed:` section
- json:
  - `available_count`
  - `allowed_count`
  - `available` (array)
  - `allowed` (array)

### `list-subsystems`
- text: tab-separated `name owner role status`
- json: array of objects with
  - `name`
  - `owner`
  - `role`
  - `path`
  - `status`

### `route`
- text: dict-like string
- json:
  - `prompt`
  - `selected_command`
  - `selected_tool`
  - `candidate_commands`
  - `candidate_tools`
  - `blocked_commands`
  - `blocked_tools`
  - `reason`
  - `policy_name`
  - `decided_at`

### `execute`
- text: dict-like string
- json:
  - `execution_id`
  - `timestamp`
  - `prompt`
  - `selected_command`
  - `selected_tool`
  - `command_message`
  - `tool_message`
  - `stop_reason`
  - `blocked`
  - `policy_name`
  - `session_id`

### `session`
- text: dict-like string
- json:
  - `session_id`
  - `turn_count`
  - `total_input_tokens`
  - `total_output_tokens`
  - `last_stop_reason`
  - `latest_route`

### `logs`
- text:
  - in-memory log lines (JSONL strings)
  - persisted records printed as dict objects
- json:
  - `in_memory` (array of execution records)
  - `persisted` (array of execution records read from JSONL file)

### `control-state`
- text: dict-like string
- json:
  - `policy_name`
  - `whitelist_tools`
  - `manual_override`
  - `log_persistence`

## Data-source trace (dashboard-relevant)
- system status:
  - `SiamCommandControlLayer.health_status()`
  - built from registries + manual override + last execution timestamp
- command inventory:
  - `SiamCommandRegistry.from_claw()`
  - source `src.commands.get_commands()`
- tool inventory:
  - `SiamToolRegistry.from_claw()`
  - source `src.tools.get_tools()` + whitelist filter
- route decisions:
  - `SiamCommandControlLayer.apply_route_policy()`
  - sources `PortRuntime.route_prompt()` + `SiamRoutingPolicy.decide()`
- execution logs:
  - in-memory list in control layer
  - persisted JSONL via `ExecutionLogStore.append()/read_all()`
- session summaries:
  - `latest_session_summary()`
  - source `QueryEnginePort` usage/turn state + last route
- subsystem registry:
  - `SiamSubsystemRegistry.from_config_and_manifest()`
  - sources `build_port_manifest()` + `config/siam/subsystems.json`
- manual override state:
  - `manual_override_state()`
- whitelist/policy state:
  - whitelist from `config/siam/tool-whitelist.json`
  - policy from `config/siam/route-policy.json`
  - persistence config from `config/siam/observability.json`

