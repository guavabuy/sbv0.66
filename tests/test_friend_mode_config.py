import os
import unittest
from unittest.mock import patch

from friend_mode_config import (
    get_tg_friend_mode_enabled,
    get_thresholds,
    DEFAULT_LOW_TH,
    DEFAULT_HIGH_TH,
    DEFAULT_MIN_HITS,
)


class TestFriendModeConfig(unittest.TestCase):
    def test_friend_mode_missing_is_false(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(get_tg_friend_mode_enabled())

    def test_friend_mode_zero_is_false(self):
        with patch.dict(os.environ, {"TG_FRIEND_MODE": "0"}, clear=True):
            self.assertFalse(get_tg_friend_mode_enabled())

    def test_friend_mode_one_is_true(self):
        with patch.dict(os.environ, {"TG_FRIEND_MODE": "1"}, clear=True):
            self.assertTrue(get_tg_friend_mode_enabled())

    def test_friend_mode_illegal_is_false(self):
        with patch.dict(os.environ, {"TG_FRIEND_MODE": "abc"}, clear=True):
            self.assertFalse(get_tg_friend_mode_enabled())

    def test_thresholds_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            th = get_thresholds()
            self.assertEqual(th["low"], DEFAULT_LOW_TH)
            self.assertEqual(th["high"], DEFAULT_HIGH_TH)
            self.assertEqual(th["min_hits"], DEFAULT_MIN_HITS)

    def test_thresholds_valid_env(self):
        with patch.dict(
            os.environ,
            {"TG_LOW_TH": "0.3", "TG_HIGH_TH": "0.6", "TG_MIN_HITS": "5"},
            clear=True,
        ):
            th = get_thresholds()
            self.assertEqual(th["low"], 0.3)
            self.assertEqual(th["high"], 0.6)
            self.assertEqual(th["min_hits"], 5)

    def test_thresholds_invalid_env_fallback_to_defaults(self):
        with patch.dict(
            os.environ,
            {"TG_LOW_TH": "x", "TG_HIGH_TH": "NaN??", "TG_MIN_HITS": "3.5"},
            clear=True,
        ):
            th = get_thresholds()
            self.assertEqual(th["low"], DEFAULT_LOW_TH)
            self.assertEqual(th["high"], DEFAULT_HIGH_TH)
            self.assertEqual(th["min_hits"], DEFAULT_MIN_HITS)


if __name__ == "__main__":
    unittest.main()
