from __future__ import annotations

from dataclasses import dataclass

from .config import RoutePolicyConfig
from .models import ManualOverrideModel, RouteDecisionModel


@dataclass(frozen=True)
class SiamRoutingPolicy:
    config: RoutePolicyConfig

    def decide(
        self,
        prompt: str,
        candidate_commands: tuple[str, ...],
        candidate_tools: tuple[str, ...],
        manual_override: ManualOverrideModel,
    ) -> RouteDecisionModel:
        blocked_commands = tuple(
            name for name in candidate_commands if not manual_override.allows_command(name)
        )
        blocked_tools = tuple(
            name for name in candidate_tools if not manual_override.allows_tool(name)
        )
        allowed_commands = tuple(
            name for name in candidate_commands if name not in blocked_commands
        )
        allowed_tools = tuple(name for name in candidate_tools if name not in blocked_tools)
        selected_command = self._select_command(prompt, allowed_commands)
        selected_tool = self._select_tool(prompt, allowed_tools)
        reason = self._build_reason(
            prompt=prompt,
            selected_command=selected_command,
            selected_tool=selected_tool,
            blocked_commands=blocked_commands,
            blocked_tools=blocked_tools,
            override_mode=manual_override.mode,
        )
        return RouteDecisionModel(
            prompt=prompt,
            selected_command=selected_command,
            selected_tool=selected_tool,
            candidate_commands=candidate_commands,
            candidate_tools=candidate_tools,
            blocked_commands=blocked_commands,
            blocked_tools=blocked_tools,
            reason=reason,
            policy_name=self.config.policy_name,
        )

    def _select_command(self, prompt: str, command_names: tuple[str, ...]) -> str | None:
        keyword_match = self._keyword_preferred_command(prompt, command_names)
        if keyword_match is not None:
            return keyword_match
        if not command_names:
            return None
        return command_names[0]

    def _select_tool(self, prompt: str, tool_names: tuple[str, ...]) -> str | None:
        keyword_match = self._keyword_preferred_tool(prompt, tool_names)
        if keyword_match is not None:
            return keyword_match
        if not tool_names:
            return None
        return tool_names[0]

    def _keyword_preferred_command(self, prompt: str, command_names: tuple[str, ...]) -> str | None:
        prompt_lower = prompt.lower()
        for rule in self.config.keyword_rules:
            if any(token.lower() in prompt_lower for token in rule.contains):
                preferred = {name.lower() for name in rule.prefer_commands}
                for name in command_names:
                    if name.lower() in preferred:
                        return name
        fallback = self.config.default_command_fallback.lower()
        for name in command_names:
            if name.lower() == fallback:
                return name
        return None

    def _keyword_preferred_tool(self, prompt: str, tool_names: tuple[str, ...]) -> str | None:
        prompt_lower = prompt.lower()
        for rule in self.config.keyword_rules:
            if any(token.lower() in prompt_lower for token in rule.contains):
                preferred = {name.lower() for name in rule.prefer_tools}
                for name in tool_names:
                    if name.lower() in preferred:
                        return name
        return None

    def _build_reason(
        self,
        prompt: str,
        selected_command: str | None,
        selected_tool: str | None,
        blocked_commands: tuple[str, ...],
        blocked_tools: tuple[str, ...],
        override_mode: str,
    ) -> str:
        parts = [f"policy={self.config.policy_name}", f"override={override_mode}"]
        if selected_command:
            parts.append(f"command={selected_command}")
        if selected_tool:
            parts.append(f"tool={selected_tool}")
        if blocked_commands:
            parts.append(f"blocked_commands={len(blocked_commands)}")
        if blocked_tools:
            parts.append(f"blocked_tools={len(blocked_tools)}")
        if not selected_command and not selected_tool:
            parts.append(f"no-routable-target for prompt={prompt!r}")
        return "; ".join(parts)

