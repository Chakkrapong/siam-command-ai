from __future__ import annotations

from dataclasses import dataclass

from .models import MusicGenAdapterContract, SubsystemModel


@dataclass(frozen=True)
class DeferredMusicGenAdapter(MusicGenAdapterContract):
    adapter_name: str = "musicgen-deferred-adapter"
    tool_name: str = "MusicGenTool"

    def describe_tool(self) -> str:
        return (
            "Deferred MusicGen adapter contract. "
            "Implementation is intentionally not mounted in this phase."
        )

    def mount_subsystem(self) -> SubsystemModel:
        return SubsystemModel(
            name="MusicGen",
            owner="MusicGen",
            role="domain tool subsystem contract placeholder",
            path="src/siam_command/musicgen.py",
            status="planned",
        )

