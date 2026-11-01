"""The Google tools: reading is free, creating an event needs approval, all run in the app."""

from assistant.tools.registry import TOOLS, requires_approval


def test_google_tools_run_in_the_desktop_app():
    for name in ("calendar_events", "calendar_create_event", "gmail_search"):
        assert TOOLS[name].client_side


def test_only_creating_an_event_needs_approval():
    create = TOOLS["calendar_create_event"]
    args = create.args_model(title="Dentista", start="2026-11-03T16:00:00-06:00")
    assert requires_approval(create, args)
    for name in ("calendar_events", "gmail_search"):
        tool = TOOLS[name]
        assert not requires_approval(tool, tool.args_model())
