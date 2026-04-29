"""Research agent loops — autonomous multi-step investigation pipelines.

This package is reserved for future research-oriented agent loops that go
beyond single-turn Q&A.  Examples include:

  • Deep-dive research: given a topic, autonomously search the web, read
    papers, synthesise findings, and produce a structured report.
  • Fact-checking loops: take a claim, gather evidence for and against,
    score confidence.
  • Comparative analysis: evaluate multiple options against user-defined
    criteria using tool calls and memory retrieval.

Each sub-module should expose a single async entry-point that the Agent Core
can delegate to when it detects a research-class request.
"""
