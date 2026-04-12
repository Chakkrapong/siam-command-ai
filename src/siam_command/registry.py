from __future__ import annotations

from dataclasses import dataclass

from ..siam_core.compat import (
    build_command_catalog_port,
    build_subsystem_catalog_port,
    build_tool_catalog_port,
)
from ..siam_core.interfaces import CommandCatalogPort, SubsystemCatalogPort, ToolCatalogPort
from .config import SubsystemsConfig, ToolWhitelistConfig
from .models import SubsystemModel


@dataclass(frozen=True)
class SiamCommandRegistry:
    command_names: tuple[str, ...]

    @classmethod
    def from_interface(cls, catalog: CommandCatalogPort) -> "SiamCommandRegistry":
        return cls(command_names=catalog.list_names())

    @classmethod
    def from_claw(cls) -> "SiamCommandRegistry":
        return cls.from_interface(build_command_catalog_port())

    def list_available(self) -> tuple[str, ...]:
        return self.command_names


@dataclass(frozen=True)
class SiamToolRegistry:
    tool_names: tuple[str, ...]
    allowed_tool_names: tuple[str, ...]

    @classmethod
    def from_interface(cls, catalog: ToolCatalogPort, whitelist: ToolWhitelistConfig) -> "SiamToolRegistry":
        available = catalog.list_names()
        allowed = catalog.list_allowed_names(whitelist.allowed_tools)
        return cls(tool_names=available, allowed_tool_names=allowed)

    @classmethod
    def from_claw(cls, whitelist: ToolWhitelistConfig) -> "SiamToolRegistry":
        return cls.from_interface(build_tool_catalog_port(), whitelist)

    def list_available(self) -> tuple[str, ...]:
        return self.tool_names

    def list_allowed(self) -> tuple[str, ...]:
        return self.allowed_tool_names

    def filter_allowed(self, tool_names: tuple[str, ...]) -> tuple[str, ...]:
        allowed_lower = {name.lower() for name in self.allowed_tool_names}
        return tuple(name for name in tool_names if name.lower() in allowed_lower)


@dataclass(frozen=True)
class SiamSubsystemRegistry:
    subsystem_items: tuple[SubsystemModel, ...]

    @classmethod
    def from_interface(
        cls,
        subsystems: SubsystemsConfig,
        catalog: SubsystemCatalogPort,
    ) -> "SiamSubsystemRegistry":
        compat_items = tuple(
            SubsystemModel(
                name=str(item.get("name", "")),
                owner=str(item.get("owner", "")),
                role=str(item.get("role", "")),
                path=str(item.get("path", "")),
                status=str(item.get("status", "active")),
            )
            for item in catalog.list_subsystems()
        )
        return cls(subsystem_items=compat_items + subsystems.items)

    @classmethod
    def from_config_and_manifest(cls, subsystems: SubsystemsConfig) -> "SiamSubsystemRegistry":
        return cls.from_interface(subsystems, build_subsystem_catalog_port())

    def list_all(self) -> tuple[SubsystemModel, ...]:
        return self.subsystem_items
