"""Background analyzer agents.

Each analyzer reads from one of the memory backends and produces durable
graph updates. This module is intentionally separate from the live
``AgentService`` — analyzers run on triggers (manual, scheduled, post-bulk
ingest) rather than per-turn.
"""
