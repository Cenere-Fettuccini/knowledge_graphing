"""Rumination Engine — Deep Synthesis and creative Rabbit Hole passes.

The forward pass (entity/belief/task extraction from raw conversations) lives in
``src.agent_platform.analyzers.knowledge`` and runs on every analyzer tick.

This package owns the second-order passes that operate on already-extracted knowledge:

- ``deep_pass.DeepSynthesisEngine`` — retroactively analyzes Belief nodes for
  evolution, contradictions, and new insights.
- ``engine.RuminationScheduler`` — APScheduler wrapper that drives both the deep
  pass and the rabbit hole pass on configurable intervals.

Enable via ``RUMINATION_ENABLED=true`` in .env (disabled by default — heavy workload).
"""
