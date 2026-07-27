from __future__ import annotations

import unittest

from alpabridge.audit.review import has_intervention


class HasInterventionTests(unittest.TestCase):
    def test_baseline_and_planner_action_modes_are_never_flagged_as_interventions(self) -> None:
        # action_mode means two different things depending on the policy:
        # a real token choice for token_dagger_bc (where anything but
        # "maintain" is a genuine correction), or just the policy's own
        # constant name for every baseline/planner - which must never read
        # as an intervention, since these policies have no correction
        # concept at all. This used to misfire for every single frame of
        # constant_velocity/route_following runs.
        for action_mode in (
            "constant_velocity",
            "route_following",
            "mpc_planner",
            "direct_actor_planner",
            "maintain",
        ):
            with self.subTest(action_mode=action_mode):
                self.assertFalse(has_intervention({"step": {"action_mode": action_mode}}))

    def test_a_real_token_correction_is_still_flagged_as_an_intervention(self) -> None:
        self.assertTrue(has_intervention({"step": {"action_mode": "nudge_left"}}))
        self.assertTrue(has_intervention({"step": {"action_mode": "evasive_right"}}))

    def test_explicit_intervention_flag_is_still_honored(self) -> None:
        self.assertTrue(has_intervention({"step": {"action_mode": "maintain", "intervention": True}}))


if __name__ == "__main__":
    unittest.main()
