"""Consent-based bank linking through approved aggregators only.

Renewal Radar never asks for, receives or stores online-banking passwords.
Linking goes through a provider-hosted widget (Plaid Link, Flinks Connect); the
app only ever holds an opaque access handle, and only mortgage fields are kept.
Only sandbox transports exist in this codebase. Production access requires a
signed provider agreement and is refused until one is configured.
"""
