"""Projection layer: turn a canonical Profile into a custom output *view* defined
by a runtime config, then validate that view against a schema. This layer is the
only thing the runtime config touches -- the engine upstream never changes.
"""
