"""Heuristic extraction of durable knowledge and opinion signals from chat."""

from __future__ import annotations

from dataclasses import dataclass
import re


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "by", "for", "from",
    "how", "i", "if", "in", "into", "is", "it", "its", "me", "my", "of", "on",
    "or", "our", "so", "that", "the", "their", "there", "they", "this", "to",
    "we", "with", "would", "you", "your",
}


@dataclass(slots=True)
class KnowledgeSignal:
    kind: str
    content: str
    belief_key: str
    entity_name: str
    entity_type: str
    confidence: float = 0.72


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "general"


def _trim_statement(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text.rstrip(".!? ")


def _extract_topic_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9']+", text.lower())
    return [token for token in tokens if token not in STOPWORDS]


def _summarize_aspect(text: str) -> str:
    tokens = _extract_topic_tokens(text)
    return "-".join(tokens[:4]) if tokens else "general"


def _infer_entity_from_text(text: str) -> tuple[str, str]:
    lowered = text.lower()
    keyword_entities = [
        (("explorer", "graph"), ("Explorer Graph", "System")),
        (("explorer",), ("Explorer", "System")),
        (("chat",), ("Chat Experience", "System")),
        (("task", "tasks"), ("Task System", "Workflow")),
        (("belief", "beliefs"), ("Belief Tracking", "System")),
        (("memory", "memories"), ("Memory System", "System")),
        (("neo4j",), ("Neo4j Graph", "Tool")),
        (("routine", "routines"), ("Routine Scheduler", "Workflow")),
    ]
    for keywords, entity in keyword_entities:
        if any(keyword in lowered for keyword in keywords):
            return entity
    return ("General Preferences", "Topic")


def _build_signal(content: str, category: str, entity_name: str, entity_type: str, confidence: float) -> KnowledgeSignal:
    aspect = _summarize_aspect(content)
    belief_key = _slugify(f"{entity_name}:{category}:{aspect}")
    return KnowledgeSignal(
        kind=category,
        content=content,
        belief_key=belief_key,
        entity_name=entity_name,
        entity_type=entity_type,
        confidence=confidence,
    )


def extract_knowledge_signals(text: str, context: dict | None = None) -> list[KnowledgeSignal]:
    normalized = _trim_statement(text)
    lowered = normalized.lower()
    if len(normalized) < 8:
        return []

    anchor_name = None
    anchor_type = "Topic"
    if context and context.get("context_summary"):
        anchor_name = str(context["context_summary"]).split(" (", 1)[0].strip()
        anchor_type = "Topic"

    default_entity_name, default_entity_type = _infer_entity_from_text(normalized)
    entity_name = anchor_name or default_entity_name
    entity_type = anchor_type if anchor_name else default_entity_type

    signals: list[KnowledgeSignal] = []

    favorite_match = re.search(r"\bmy favorite (?P<topic>.+?) is (?P<value>.+)", lowered)
    if favorite_match:
        topic = favorite_match.group("topic").strip(" .")
        value = favorite_match.group("value").strip(" .")
        signals.append(
            _build_signal(
                content=f"My favorite {topic} is {value}",
                category="preference",
                entity_name=topic.title(),
                entity_type="PreferenceTopic",
                confidence=0.84,
            )
        )

    starter_patterns = [
        (r"\bi think(?: that)? (?P<clause>.+)", "opinion", 0.74, "I think {clause}"),
        (r"\bi believe(?: that)? (?P<clause>.+)", "belief", 0.78, "I believe {clause}"),
        (r"\bi feel(?: that)? (?P<clause>.+)", "opinion", 0.72, "I feel {clause}"),
        (r"\bi prefer (?P<clause>.+)", "preference", 0.86, "I prefer {clause}"),
        (r"\bi (?:really )?like (?P<clause>.+)", "preference", 0.8, "I like {clause}"),
        (r"\bi (?:really )?love (?P<clause>.+)", "preference", 0.84, "I love {clause}"),
        (r"\bi (?:do not|don't) like (?P<clause>.+)", "aversion", 0.82, "I do not like {clause}"),
        (r"\bi hate (?P<clause>.+)", "aversion", 0.88, "I hate {clause}"),
        (r"\bi want (?P<clause>.+)", "goal", 0.76, "I want {clause}"),
        (r"\bi need (?P<clause>.+)", "need", 0.78, "I need {clause}"),
    ]

    for pattern, category, confidence, template in starter_patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        clause = _trim_statement(match.group("clause"))
        if clause:
            signals.append(
                _build_signal(
                    content=template.format(clause=clause),
                    category=category,
                    entity_name=entity_name,
                    entity_type=entity_type,
                    confidence=confidence,
                )
            )
        break

    if " should " in f" {lowered} ":
        signals.append(
            _build_signal(
                content=normalized,
                category="proposal",
                entity_name=entity_name,
                entity_type=entity_type,
                confidence=0.76,
            )
        )

    if any(marker in lowered for marker in ("useful", "useless", "doesn't make sense", "does not make sense", "too noisy")):
        signals.append(
            _build_signal(
                content=normalized,
                category="evaluation",
                entity_name=entity_name,
                entity_type=entity_type,
                confidence=0.73,
            )
        )

    unique: dict[str, KnowledgeSignal] = {}
    for signal in signals:
        unique.setdefault(signal.belief_key, signal)
    return list(unique.values())
