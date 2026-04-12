# Siam Command Architecture (Repo-Mapped)

## Scope and intent
- This layer wraps Claw surfaces additively.
- Claw Core remains the execution engine.
- Siam Command adds control, policy, and observability contracts.
- No core runtime rewrite is introduced.

## What was inspected (real repo paths)
- Python control/execution mirror:
  - `src/main.py`
  - `src/runtime.py`
  - `src/commands.py`
  - `src/tools.py`
  - `src/execution_registry.py`
  - `src/query_engine.py`
  - `src/session_store.py`
  - `src/permissions.py`
  - `src/port_manifest.py`
- Rust core workspace:
  - `rust/Cargo.toml`
  - `rust/crates/runtime/src/lib.rs`
  - `rust/crates/claw-cli/src/main.rs`
  - `rust/crates/commands/src/lib.rs`
  - `rust/crates/tools/src/lib.rs`

## Claw Core map (observed)
### Python mirror surface
- Runtime/session routing:
  - `src/runtime.py`
  - `PortRuntime.route_prompt()` scores prompt tokens against command/tool metadata.
  - `PortRuntime.bootstrap_session()` ties context, setup, routing, command/tool execution messages, stream events, and persisted session path.
  - `PortRuntime.run_turn_loop()` runs bounded turn submissions.
- Command inventory and execution shims:
  - `src/commands.py`
  - loads snapshot from `src/reference_data/commands_snapshot.json`
  - `get_commands()`, `get_command()`, `execute_command()`
- Tool inventory and execution shims:
  - `src/tools.py`
  - loads snapshot from `src/reference_data/tools_snapshot.json`
  - `get_tools()`, `get_tool()`, `execute_tool()`
  - tool filtering already exists via `ToolPermissionContext` from `src/permissions.py`
- Command/tool executable lookup:
  - `src/execution_registry.py`
  - `build_execution_registry()` returns lookup-capable command/tool registries
- Session and transcript flow:
  - `src/query_engine.py`
  - `QueryEnginePort.submit_message()` updates turns, token usage, denials
  - `QueryEnginePort.persist_session()` flushes transcript and writes `.port_sessions/<session_id>.json`
  - storage implementation in `src/session_store.py`
- CLI orchestration:
  - `src/main.py`
  - routes subcommands to runtime/query/session/tool/command flows.

### Rust core workspace surface
- Workspace composition:
  - `rust/Cargo.toml` uses `members = ["crates/*"]`
- Runtime exports and core execution contracts:
  - `rust/crates/runtime/src/lib.rs` exports conversation runtime, permissions, session, prompt, MCP, hooks, and usage tracking.
- CLI layer:
  - `rust/crates/claw-cli/src/main.rs` parses actions and runs prompt/repl/login/init/resume flows.
- Command catalog and slash command structure:
  - `rust/crates/commands/src/lib.rs`
- Tool definitions/registry and execution:
  - `rust/crates/tools/src/lib.rs`

## Flow map (Python surface used by Siam layer)
1. prompt enters wrapper
2. wrapper calls `PortRuntime.route_prompt()` for candidate command/tool matches
3. wrapper filters tools by whitelist and manual override
4. wrapper applies route policy before execute
5. wrapper executes selected command/tool through `ExecutionRegistry`
6. wrapper submits turn to `QueryEnginePort.submit_message()`
7. wrapper logs structured execution records
8. wrapper provides health/status + session summary contracts

## Safe hook points (additive, non-destructive)
- Read-only inventories:
  - `get_commands()` and `get_tools()` for discovery
- Existing permission/filter primitive:
  - `ToolPermissionContext` and tool filtering path
- Existing routing primitive:
  - `PortRuntime.route_prompt()` for candidate generation
- Existing execution primitive:
  - `build_execution_registry()` for command/tool execution lookup
- Existing session primitive:
  - `QueryEnginePort` for turn accounting and session continuity

These hook points are stable for additive wrapping because they do not require replacing core implementations.

## Siam layer placement
- New package: `src/siam_command/`
- New configs: `config/siam/`
- New docs: `docs/`

### Responsibility split
- Claw Core:
  - runtime/commands/tools/session execution substrate
- Siam Command:
  - control layer, policy, manual override, status/log/session formatting
- Techin:
  - route decision policy authority (`config/siam/route-policy.json`, `src/siam_command/policy.py`)
- MusicGen:
  - deferred adapter contract only (`src/siam_command/musicgen.py`)

