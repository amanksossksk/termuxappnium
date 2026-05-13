"""ScreenRouter: declaratively handle a sequence of random pop-up screens.

The pattern in most app onboarding flows is the same: a stream of
permission dialogs, "Welcome" screens, cookie banners, "Rate the app"
prompts, etc. arrive in unpredictable order, each one needing a tap to
dismiss before you get to the real UI.

`ScreenRouter` lets you describe each case once and then run a loop that
dispatches them until your main screen appears.

Example
-------

    from android_controller import Device, ScreenRouter

    d = Device.from_config("config.json")
    router = ScreenRouter(d)

    router.when(text_contains="notifications").tap_label("Skip", "Not now")
    router.when(text_contains="location").tap_label("Don't allow", "Deny")
    router.when(text_contains="cookies").tap_label("Accept all", "Agree", "I agree")
    router.when(text="Welcome").tap_label("Get started", "Continue")
    router.when(text_contains="update").tap_label("Later", "Not now")

    # Custom action:
    router.when(text="Sign in").do(lambda d, el: d.tap_text("Sign in with Google"))

    # Or tap the matched element itself if it's the button:
    router.when(text="I agree", clickable=True).tap_match()

    # Run until the main screen appears (or timeout).
    router.run(
        stop_when={"resource_id": "mark.via.gp:id/url_bar"},
        timeout=120,
    )

Notes
-----
* Rules are checked in registration order — put the most specific rule first.
* Each iteration dumps the UI once and tries every rule against that dump,
  so it's not expensive even with 20+ rules.
* After a handler fires we sleep `settle_ms` (default 400 ms) to let the
  next screen render before the next iteration.
* When filtering by button text, also pass `clickable=True` — Android often
  has the same text in both a paragraph (TextView) and the button itself.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from .device import Device
from .elements import UIElement, find_elements_in_xml


# Action signature: receives (device, matched_element) and returns True iff
# something was actually done (so the router knows to sleep + restart).
Action = Callable[[Device, UIElement], bool]


class ScreenRule:
    """Builder returned by `ScreenRouter.when(...)`. Chain one action method."""

    def __init__(self, router: "ScreenRouter", name: str, filters: dict[str, Any]):
        self._router = router
        self._name = name
        self._filters = filters

    # ---------------- action terminators ----------------

    def tap_label(self, *labels: str, clickable: bool = True) -> "ScreenRouter":
        """When the rule fires, tap the first matching clickable label."""
        targets = list(labels)

        def action(d: Device, _matched: UIElement) -> bool:
            for label in targets:
                kwargs = {"text": label}
                if clickable:
                    kwargs["clickable"] = True
                el = d.find_element(**kwargs)
                if el:
                    el.tap()
                    return True
            return False

        return self._router._register(self._name, self._filters, action)

    def tap_match(self) -> "ScreenRouter":
        """When the rule fires, tap the matched element itself."""
        def action(_d: Device, matched: UIElement) -> bool:
            try:
                matched.tap()
                return True
            except Exception:
                return False
        return self._router._register(self._name, self._filters, action)

    def tap_id(self, resource_id: str) -> "ScreenRouter":
        """When the rule fires, tap any clickable element with this resource_id."""
        def action(d: Device, _matched: UIElement) -> bool:
            el = d.find_element(resource_id=resource_id, clickable=True)
            if el:
                el.tap()
                return True
            return False
        return self._router._register(self._name, self._filters, action)

    def tap_desc(self, *descs: str) -> "ScreenRouter":
        """When the rule fires, tap the first clickable element matching one of these content_descs."""
        targets = list(descs)

        def action(d: Device, _matched: UIElement) -> bool:
            for desc in targets:
                el = d.find_element(content_desc=desc, clickable=True)
                if el:
                    el.tap()
                    return True
            return False
        return self._router._register(self._name, self._filters, action)

    def press_key(self, key) -> "ScreenRouter":
        """When the rule fires, press a hardware key (e.g. 'BACK')."""
        def action(d: Device, _matched: UIElement) -> bool:
            d.press_key(key)
            return True
        return self._router._register(self._name, self._filters, action)

    def do(self, fn: Callable[[Device, UIElement], Any]) -> "ScreenRouter":
        """When the rule fires, run a custom callable.

        The callable receives `(device, matched_element)`. Return value is
        treated as truthy/falsy: truthy means "I handled it" (sleep + restart);
        falsy means "I didn't handle it" (move on to next rule).
        """
        def action(d: Device, matched: UIElement) -> bool:
            return bool(fn(d, matched))
        return self._router._register(self._name, self._filters, action)

    def skip(self) -> "ScreenRouter":
        """When the rule fires, do nothing but consume the match (mostly for
        building denylists / 'expected screens to ignore' cases)."""
        return self._router._register(self._name, self._filters, lambda d, m: True)


class ScreenRouter:
    """Dispatch handlers across whichever screen happens to appear."""

    def __init__(
        self,
        device: Device,
        *,
        poll: float = 0.5,
        settle_ms: int = 400,
        verbose: bool = True,
    ):
        self.device = device
        self.poll = poll
        self.settle_ms = settle_ms
        self.verbose = verbose
        self._rules: list[tuple[str, dict[str, Any], Action]] = []

    # ---------------- registration ----------------

    def when(self, *, name: Optional[str] = None, **filters) -> ScreenRule:
        """Start a rule that fires when an element matching `filters` exists.

        Returns a `ScreenRule` you chain with `.tap_label(...)`, `.tap_match()`,
        `.press_key(...)`, `.do(fn)`, etc.
        """
        rule_name = name or self._auto_name(filters)
        return ScreenRule(self, rule_name, filters)

    def add(
        self,
        filters: dict[str, Any],
        action: Action,
        name: Optional[str] = None,
    ) -> "ScreenRouter":
        """Low-level: register a rule with a raw action function."""
        return self._register(name or self._auto_name(filters), filters, action)

    def _register(
        self, name: str, filters: dict[str, Any], action: Action
    ) -> "ScreenRouter":
        self._rules.append((name, filters, action))
        return self

    @staticmethod
    def _auto_name(filters: dict[str, Any]) -> str:
        return ", ".join(f"{k}={v!r}" for k, v in filters.items())

    # ---------------- execution ----------------

    def step(self) -> Optional[str]:
        """Run one iteration: dump UI, try every rule once, fire the first hit.

        Returns the rule name that fired, or None.
        """
        try:
            xml = self.device.dump_ui()
        except Exception as e:
            self._log(f"dump_ui failed: {e}")
            return None
        for name, filters, action in self._rules:
            els = find_elements_in_xml(xml, self.device, filters)
            if not els:
                continue
            self._log(f"matched: {name}")
            if action(self.device, els[0]):
                return name
            self._log(f"  (rule '{name}' matched but action returned False)")
        return None

    def run(
        self,
        *,
        stop_when: Optional[dict | Callable[[Device], bool]] = None,
        timeout: float = 120.0,
        max_actions: Optional[int] = None,
    ) -> bool:
        """Loop until `stop_when` is satisfied or `timeout` seconds elapse.

        - `stop_when` can be a filter dict (e.g. `{"resource_id": "...:id/url_bar"}`)
          or a callable `(device) -> bool`.
        - `max_actions` is a safety cap on how many handlers may fire.
        - Returns True if `stop_when` was satisfied, False on timeout.
        """
        deadline = time.time() + timeout
        actions = 0

        while time.time() < deadline:
            if self._stop_condition_met(stop_when):
                self._log("stop_when satisfied")
                return True

            fired = self.step()
            if fired:
                actions += 1
                if max_actions and actions >= max_actions:
                    self._log(f"max_actions ({max_actions}) reached")
                    return self._stop_condition_met(stop_when)
                time.sleep(self.settle_ms / 1000)
            else:
                time.sleep(self.poll)

        self._log("timeout reached")
        return self._stop_condition_met(stop_when)

    def _stop_condition_met(
        self, stop_when: Optional[dict | Callable[[Device], bool]]
    ) -> bool:
        if stop_when is None:
            return False
        if callable(stop_when):
            try:
                return bool(stop_when(self.device))
            except Exception:
                return False
        if isinstance(stop_when, dict):
            try:
                return self.device.exists(**stop_when)
            except Exception:
                return False
        return False

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[router] {msg}", flush=True)
