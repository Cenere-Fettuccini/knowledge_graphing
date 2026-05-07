from __future__ import annotations

import time

from src.core.limits_store import import_from_paste, load_limits, load_mismatch_log
from src.core.router import llm_router


def derive_model_function(capabilities: dict) -> str:
    if not capabilities:
        return "General"

    sorted_caps = sorted(capabilities.items(), key=lambda x: x[1], reverse=True)
    top_score = sorted_caps[0][1]
    top_tasks = [task for task, score in sorted_caps if score >= top_score - 0.05]

    label_map = {
        "QA": "Q&A",
        "REASONING": "Reasoning",
        "EXTRACTION": "Extraction",
        "SUMMARIZATION": "Summarization",
        "CODE": "Code",
    }

    if len(top_tasks) >= 4:
        return "General Purpose"
    if len(top_tasks) == 1:
        return label_map.get(top_tasks[0], top_tasks[0])
    return " / ".join(label_map.get(t, t) for t in top_tasks[:2])


def get_credits() -> dict:
    now = time.time()
    models_data = []
    tracked_ids = set()

    for model in llm_router.models:
        short_id = model.model_id.split("/")[-1]
        tracked_ids.add(short_id)
        state = llm_router.limiter._get_state(model.model_id, model.project_scope)

        rpm_used = len([t for t in state.used_rpm if now - t < 60])
        rpd_used = len([t for t in state.used_rpd if now - t < 86400])
        tpm_used = sum(e["tokens"] for e in state.used_tpm if now - e["ts"] < 60)

        headroom = llm_router.limiter.get_headroom(
            model.model_id,
            model.project_scope,
            model.rpm_limit,
            model.rpd_limit,
            model.tpm_limit,
        )

        group_name = (
            "Local Models"
            if model.provider == "local"
            else f"{model.provider.capitalize()} Project ({model.project_scope})"
        )

        models_data.append({
            "model": short_id,
            "model_id": model.model_id,
            "provider": model.provider,
            "project_scope": model.project_scope,
            "group": group_name,
            "headroom": round(headroom * 100, 1),
            "function": derive_model_function(model.capabilities),
            "capabilities": model.capabilities,
            "rpm": {"used": rpm_used, "limit": model.rpm_limit},
            "rpd": {"used": rpd_used, "limit": model.rpd_limit},
            "tpm": {"used": tpm_used, "limit": model.tpm_limit},
        })

    overrides = load_limits()
    for short_id, limits in overrides.items():
        if short_id not in tracked_ids:
            models_data.append({
                "model": short_id,
                "model_id": f"models/{short_id}",
                "provider": "google",
                "group": "Untracked (Limits Only)",
                "headroom": None,
                "function": "Untracked",
                "capabilities": {},
                "rpm": {"used": None, "limit": limits.get("rpm_limit") or 0},
                "rpd": {"used": None, "limit": limits.get("rpd_limit") or 0},
                "tpm": {"used": None, "limit": limits.get("tpm_limit") or 0},
            })

    return {"models": models_data, "timestamp": now}


def import_limits_text(raw_text: str) -> dict:
    if not raw_text.strip():
        return {"ok": False, "error": "No text provided", "matched": []}
    updated, matched = import_from_paste(raw_text)
    llm_router.reload_limits()
    return {"ok": True, "matched": matched, "total_models": len(updated)}


def get_mismatches() -> dict:
    events = load_mismatch_log()
    overrides = load_limits()
    for ev in events:
        mid = ev["model_id"].split("/")[-1]
        override = overrides.get(mid, {})
        ev["override_limits"] = {
            "rpm": override.get("rpm_limit"),
            "tpm": override.get("tpm_limit"),
            "rpd": override.get("rpd_limit"),
        }
    return {"events": events[-50:]}
