"""On resolve, write the answer into PolicyAssignment.overrides for the node
and (optionally) update PipelineContext.conventionsContext for the dataset."""
from typing import Any, Dict


def on_resolve(request: Any, answer: Dict[str, Any], db: Any) -> None:
    """Write per-node override; optionally update dataset-level convention.

    db is the prisma client when running in production, or the test fake which
    exposes .conventions and .overrides dicts. The fake-DB path here is used
    for unit testing; the production path is handled by the API layer in
    Task 12 (the router commits the resolution + convention updates atomically).
    """
    if not hasattr(db, "overrides"):
        return  # Prisma path is handled by the API layer; this is the fake-DB path

    column = answer["column"]
    table_fqn = request.payload["table_fqn"]

    overrides = db.overrides.setdefault((request.pipelineStackId, table_fqn), {})
    overrides.setdefault("clarifications", {})["volume_timestamp_column"] = column

    if "." in table_fqn:
        dataset = table_fqn.rsplit(".", 1)[0]
        conv = db.conventions.setdefault(request.pipelineStackId, {})
        pref = conv.setdefault("volume_timestamp_preference", {
            "ordered": [], "scope": dataset
        })
        if column not in pref["ordered"]:
            pref["ordered"].insert(0, column)
        pref["scope"] = dataset
