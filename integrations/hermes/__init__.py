"""Copy this plugin directory into a Hermes profile's plugins/memory directory."""

from agent.memory_provider import MemoryProvider
from mnemosyne.hosts.hermes import HermesAdapter


class MnemosyneMemoryProvider(HermesAdapter, MemoryProvider):
    pass


def register(ctx):
    ctx.register_memory_provider(MnemosyneMemoryProvider())
