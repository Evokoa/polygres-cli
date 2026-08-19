from __future__ import annotations

import json
from pathlib import Path

from polygres_cli._vendor.polygres_lib import context


def test_shared_context_fixtures_validate_through_vendored_contracts() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "context" / "contract-fixtures.json"
    if not fixture_path.exists():
        fixture_path = (
            Path(__file__).parents[2]
            / "polygres-lib"
            / "fixtures"
            / "context"
            / "contract-fixtures.json"
        )
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))

    for model_name, payload in fixtures["requests"].items():
        model = getattr(context, model_name)
        model.model_validate(payload)
    for model_name, payload in fixtures["responses"].items():
        model = getattr(context, model_name)
        model.model_validate(payload)

    additive = context.CapabilitiesResponse.model_validate(fixtures["additive_response"])
    assert additive.setup_blocker_message is not None
    assert additive.rank_fusion_blocker_message is not None
    assert (
        additive.model_dump()["future_additive_field"]
        == fixtures["additive_response"]["future_additive_field"]
    )


def test_vendored_public_names_distinguish_context_hybrid_modes() -> None:
    assert "rank_fusion" in {item.value for item in context.ContextRankedMode}
    assert "joint" in {item.value for item in context.ContextRankedMode}
    assert context.JointSearchRequest is not context.RankFusionSearchRequest
    assert context.ContextJointResponse is not context.RankedResponse
    operation_kinds = {item.value for item in context.ContextOperationKind}
    assert "points_reconcile" in operation_kinds
    assert "points_backfill" not in operation_kinds
    assert "points_sync" not in operation_kinds
