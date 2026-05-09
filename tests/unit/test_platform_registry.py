from src.platform.app_factory import build_registry


def test_registry_exposes_section_roles_and_routes():
    registry = build_registry()
    apps = {app.id: app for app in registry.list_apps()}

    assert apps["explorer"].section_role == "cross_cutting"
    assert apps["chat"].section_role == "cross_cutting"
    assert apps["credits"].section_role == "cross_cutting"
    assert apps["financial_manager"].section_role == "domain"
    assert apps["routine_scheduler"].section_role == "domain"

    assert apps["chat"].route_prefix == "/apps/chat"
    assert apps["credits"].route_prefix == "/apps/credits"
    assert apps["financial_manager"].route_prefix == "/apps/financial-manager"
    assert apps["routine_scheduler"].route_prefix == "/apps/routine-scheduler"
