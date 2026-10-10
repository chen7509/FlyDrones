"""Apply one truth-free native motion intent during the existing 200 ms anchor lead."""

from __future__ import annotations

from tools.benchmark.readiness_anchor import AnchoredPolicy


class MotionIntentAnchoredPolicy(AnchoredPolicy):
    """Keep the frozen force profile, but require native acknowledgement before it starts."""

    def __init__(self, readiness, persist, *, prepare_motion):
        if not callable(prepare_motion):
            raise ValueError("motion-intent callback required")
        super().__init__(readiness, persist)
        self.prepare_motion = prepare_motion
        self.motion_intent_prepared = False

    def step(self, ns, dt_ns, *, unarmed_wall_ns, wall_ns):
        had_anchor = self.anchor_ns is not None
        force = super().step(
            ns, dt_ns, unarmed_wall_ns=unarmed_wall_ns, wall_ns=wall_ns
        )
        if not had_anchor and self.anchor_ns is not None:
            try:
                self.prepare_motion(self.anchor_ns, self.readiness())
                self.motion_intent_prepared = True
            except Exception as exc:
                self.refuse(repr(exc))
        if self.anchor_ns is not None and ns >= self.anchor_ns and not self.motion_intent_prepared:
            self.refuse("motion reached anchor without native motion intent")
        return force

    def finish(self):
        result = super().finish()
        result["motion_intent_prepared"] = self.motion_intent_prepared
        result["full_profile_requested"] = (
            result["full_profile_requested"] and self.motion_intent_prepared
        )
        return result
