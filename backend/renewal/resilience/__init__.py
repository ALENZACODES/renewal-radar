"""Failure isolation for optional third-party integrations."""
from .circuit_breakers import CircuitBreaker, CircuitOpen, registry

__all__ = ['CircuitBreaker', 'CircuitOpen', 'registry']
