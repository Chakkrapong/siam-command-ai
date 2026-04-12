# Siam Command Risk Register

## R-01 Snapshot drift
- Risk: Python wrapper uses mirrored command/tool snapshots, while Rust runtime evolves.
- Impact: policy decisions may drift from live runtime capabilities.
- Mitigation: keep policy names explicit and refresh snapshot-to-policy alignment in release checklist.

## R-02 Duplicate names in mirrored inventories
- Risk: command/tool snapshots include duplicate names.
- Impact: ambiguous selection if policy targets only by name.
- Mitigation: current wrapper preserves ordered candidates and uses first valid match; next phase should include source-hint pinning.

## R-03 Overblocking via manual override
- Risk: `block_all_tools` or restrictive allow-lists can block all execution.
- Impact: zero throughput when override is misconfigured.
- Mitigation: status surface exposes override mode and blocked routes; keep emergency reset path to `normal`.

## R-04 Policy misrouting
- Risk: keyword-based rules can pick suboptimal command/tool for ambiguous prompts.
- Impact: lower quality execution outcome.
- Mitigation: keep deterministic route decision record and reason string for audit/iteration.

## R-05 Session/log divergence
- Risk: `.port_sessions` tracks QueryEngine messages while Siam execution logs are in-memory for now.
- Impact: partial observability after process restart.
- Mitigation: planned persistent Siam log store in Phase 2.

## R-06 Future MusicGen coupling risk
- Risk: direct integration could leak domain assumptions into core policy engine.
- Impact: harder maintenance and policy complexity.
- Mitigation: keep strict adapter contract (`MusicGenAdapterContract`) and separate implementation file.

## R-07 Verification surface mismatch
- Risk: Rust verification can fail independently from Python wrapper changes.
- Impact: mixed pipeline signal.
- Mitigation: report Python and Rust verification results separately and transparently.

