"""On resolve: 'expected' writes a dampening rule; 'investigate' hands off to debug mode."""
from typing import Any, Dict


def on_resolve(request: Any, answer: Dict[str, Any], db: Any) -> None:
    disposition = answer["disposition"]

    if disposition == "expected":
        _write_dampening_rule(request, db)
        return

    if disposition == "investigate":
        _handoff_to_debug(request, db)
        return


def _write_dampening_rule(request: Any, db: Any) -> None:
    if not hasattr(db, "conventions"):
        return  # production Prisma path handled by API layer
    conv = db.conventions.setdefault(request.pipelineStackId, {})
    dampening = conv.setdefault("dampening", {"rules": []})
    rule = {
        "node": request.scopeRef,
        "metric": request.payload["metric"],
        "min_z_to_alert": _bump_threshold(request.payload["z_score"]),
        "rationale": "user marked borderline failure as expected",
        "source_request_id": request.id,
    }
    dampening["rules"].append(rule)


def _bump_threshold(z_observed: float) -> float:
    abs_z = abs(z_observed)
    return max(3.0, abs_z + 0.5)


def _handoff_to_debug(request: Any, db: Any) -> None:
    if not hasattr(db, "handed_off_to_debug"):
        return
    db.handed_off_to_debug.append({
        "node_fqn": request.payload["node_fqn"],
        "metric": request.payload["metric"],
        "z_score": request.payload["z_score"],
        "observed": request.payload["observed"],
        "expected_range": request.payload["expected_range"],
    })
