from app.services.sync_service import SyncPlan


def test_sync_plan_marks_incremental_scope_as_space_wide():
    plan = SyncPlan.for_incremental(space_key="DEMO")

    assert plan.scope == "space"
    assert plan.mode == "incremental"
