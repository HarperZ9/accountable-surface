"""The action plan as data: schema, digests, and mapping onto the effectors.

A plan carries no authority. Its step digest covers every field, including the
post-condition, so an approval for a step covers what the step must produce and
not only what it sends.
"""

from __future__ import annotations

import pytest

from accountable_surface import plan
from accountable_surface.browser_effector import BrowserAction
from accountable_surface.web_effector import WebAction

ORIGIN = "http://127.0.0.1:8765"


def _step(**over):
    raw = {
        "step_id": "s1", "action_kind": "web.fill",
        "target": {"origin": ORIGIN, "path": "/notes", "control": {"name": "Title", "role": "textbox"}},
        "args": {"value": "weekly notes"},
        "post_condition": {"kind": "field_value_is", "control": {"name": "Title"}, "value": "weekly notes"},
    }
    raw.update(over)
    return raw


def test_a_step_round_trips_and_names_its_url():
    step = plan.step_from_dict(_step())
    assert step.url == ORIGIN + "/notes" and step.origin == ORIGIN
    assert plan.step_from_dict(step.to_dict()) == step


def test_step_digest_covers_post_condition():
    a = plan.step_from_dict(_step())
    b = plan.step_from_dict(_step(post_condition={"kind": "field_value_is", "control": {"name": "Title"}, "value": "other"}))
    assert a.args == b.args and a.target == b.target
    assert plan.step_digest(a) != plan.step_digest(b)


def test_step_digest_is_stable_and_plan_digest_orders_steps():
    a, b = plan.step_from_dict(_step()), plan.step_from_dict(_step(step_id="s2"))
    assert plan.step_digest(a) == plan.step_digest(plan.step_from_dict(_step()))
    assert plan.plan_digest([a, b]) != plan.plan_digest([b, a])


@pytest.mark.parametrize("bad", [
    {"target": "http://127.0.0.1:8765/notes"},
    {"target": {"origin": ORIGIN, "path": "/n", "control": {"x": 10, "y": 20}}},
    {"action_kind": ""},
    {"args": "value"},
    {"step_id": None},
])
def test_malformed_steps_are_rejected(bad):
    with pytest.raises(plan.PlanError):
        plan.step_from_dict(_step(**bad))


def test_missing_post_condition_is_a_problem():
    step = plan.step_from_dict(_step(post_condition=None))
    assert "post_condition" in plan.post_condition_problem(step)


def test_post_condition_the_readback_cannot_settle_is_a_problem():
    step = plan.step_from_dict(_step(post_condition={"kind": "region_changed"}))
    assert "cannot settle" in plan.post_condition_problem(step)
    assert plan.post_condition_problem(plan.step_from_dict(_step())) is None


def test_mapping_onto_the_web_effector():
    step = plan.step_from_dict(_step())
    assert plan.effector_content(step) == (ORIGIN + "/notes", WebAction("fill", url=ORIGIN + "/notes", selector="Title", value="weekly notes"))
    submit = plan.step_from_dict(_step(
        action_kind="web.submit", args={"action": "/order/submit"},
        target={"origin": ORIGIN, "path": "/order", "control": {"name": "Submit order", "role": "button"}},
        post_condition={"kind": "title_is", "value": "Order received"}))
    assert plan.effector_content(submit)[1] == WebAction("submit", url=ORIGIN + "/order/submit", value="Order received")


def test_mapping_onto_the_browser_effector():
    click = plan.step_from_dict(_step(
        action_kind="browser.click", args={},
        target={"origin": ORIGIN, "path": "/app", "control": {"name": "Save", "role": "button"}},
        post_condition={"kind": "text_present", "value": "Saved"}))
    assert plan.effector_content(click)[1] == BrowserAction("click", url=ORIGIN + "/app", selector="Save")
    nav = plan.step_from_dict(_step(action_kind="browser.navigate", args={},
                                    target={"origin": ORIGIN, "path": "/next"},
                                    post_condition={"kind": "url_is", "value": ORIGIN + "/next"}))
    assert plan.effector_content(nav)[1] == BrowserAction("navigate", url=ORIGIN + "/next")


def test_value_never_appears_in_the_public_rendering():
    step = plan.step_from_dict(_step(args={"value": "4111 1111 1111 1111"}))
    rendered = plan.render_public(step)
    assert "4111" not in str(rendered) and rendered["value_length"] == 19
