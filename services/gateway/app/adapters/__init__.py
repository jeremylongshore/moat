# Gateway adapters package
from app.adapters.base import AdapterInterface, AdapterRegistry
from app.adapters.stub import StubAdapter

__all__ = ["AdapterInterface", "AdapterRegistry", "StubAdapter"]
