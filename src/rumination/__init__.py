"""Rumination Engine — Deep Synthesis and creative Rabbit Hole passes.

The forward pass (entity / task / edge extraction from raw conversations) is
the count-triggered ``graph_ingest_trigger`` -> ``graph_extraction`` flow under
``src.agent_platform.analyzers``. Beliefs are extracted by a separate cloud
pass (``cloud_belief_extraction``) over rows the local pass flagged as
belief candidates.

This package owns the second-order passes that operate on already-extracted knowledge:

- ``deep_pass.DeepSynthesisEngine`` — retroactively analyzes Belief nodes for
  evolution, contradictions, and new insights.
- ``engine.RuminationScheduler`` — APScheduler wrapper that drives both the deep
  pass and the rabbit hole pass on configurable intervals.

Enable via ``RUMINATION_ENABLED=true`` in .env (disabled by default — heavy workload).
"""
