"""
Priority 3: Manual DUT Reconfigure Alignment Tests

Verifies that CaseExecutionPipeline correctly detects WLAN configuration changes
and generates user-friendly reconfigure prompts with WLAN-specific fields.
"""

import unittest
from unittest.mock import Mock, MagicMock

from application.run_execution_support import CaseExecutionPipeline


class MockTestCase:
    """Mock TestCase object for testing."""
    def __init__(self, **kwargs):
        self.test_type = kwargs.get("test_type", "PSD")
        self.band = kwargs.get("band", "5G")
        self.standard = kwargs.get("standard", "802.11ac")
        self.channel = kwargs.get("channel", 36)
        self.center_freq_mhz = kwargs.get("center_freq_mhz", 5180.0)
        self.bw_mhz = kwargs.get("bw_mhz", 80)
        self.tags = kwargs.get("tags", {})
        self.key = kwargs.get("key", "test_key_1")


class TestDUTReconfigureSetupKey(unittest.TestCase):
    """Test suite for case_setup_key with WLAN-specific fields."""

    def setUp(self):
        """Initialize CaseExecutionPipeline with mocks."""
        # Create mock objects to avoid complex initialization
        mock_run_repo = MagicMock()
        mock_metadata_recorder = MagicMock()
        self.pipeline = CaseExecutionPipeline(mock_run_repo, mock_metadata_recorder)

    def test_case_setup_key_includes_wlan_fields(self):
        """Test 1: case_setup_key includes WLAN-specific fields."""
        case = MockTestCase(
            band="5G",
            standard="802.11ac",
            phy_mode="VHT",
            channel=36,
            center_freq_mhz=5180.0,
            bw_mhz=80,
            tags={"phy_mode": "VHT", "data_rate": "6Mbps", "voltage_condition": "NOMINAL"},
        )
        
        key = self.pipeline.case_setup_key(case)
        
        # Key should have 11 elements:
        # Legacy (7): band, center_freq_mhz, bw_mhz, phy_mode, data_rate, voltage_condition, target_voltage_v
        # WLAN (4): standard, bw_mhz, channel, center_freq_mhz
        self.assertEqual(len(key), 11, f"Key should have 11 elements, got {len(key)}: {key}")

    def test_case_setup_key_detects_standard_change(self):
        """Test 2: case_setup_key detects standard changes (802.11n vs 802.11ac)."""
        case1 = MockTestCase(
            standard="802.11n",
            channel=36,
            center_freq_mhz=5180.0,
            bw_mhz=20,
            tags={"phy_mode": "HT"},
        )
        case2 = MockTestCase(
            standard="802.11ac",
            channel=36,
            center_freq_mhz=5180.0,
            bw_mhz=20,
            tags={"phy_mode": "VHT"},
        )
        
        key1 = self.pipeline.case_setup_key(case1)
        key2 = self.pipeline.case_setup_key(case2)
        
        self.assertNotEqual(key1, key2, "Different standards should produce different keys")

    def test_case_setup_key_detects_channel_change(self):
        """Test 3: case_setup_key detects channel changes."""
        case1 = MockTestCase(channel=36)
        case2 = MockTestCase(channel=40)
        
        key1 = self.pipeline.case_setup_key(case1)
        key2 = self.pipeline.case_setup_key(case2)
        
        self.assertNotEqual(key1, key2, "Different channels should produce different keys")

    def test_case_setup_key_detects_bandwidth_change(self):
        """Test 4: case_setup_key detects bandwidth changes."""
        case1 = MockTestCase(bw_mhz=20)
        case2 = MockTestCase(bw_mhz=80)
        
        key1 = self.pipeline.case_setup_key(case1)
        key2 = self.pipeline.case_setup_key(case2)
        
        self.assertNotEqual(key1, key2, "Different bandwidths should produce different keys")

    def test_case_setup_key_detects_frequency_change(self):
        """Test 5: case_setup_key detects frequency changes."""
        case1 = MockTestCase(center_freq_mhz=5180.0)
        case2 = MockTestCase(center_freq_mhz=5210.0)
        
        key1 = self.pipeline.case_setup_key(case1)
        key2 = self.pipeline.case_setup_key(case2)
        
        self.assertNotEqual(key1, key2, "Different frequencies should produce different keys")

    def test_case_setup_key_identical_cases_same_key(self):
        """Test 6: Identical cases produce identical keys."""
        case1 = MockTestCase(
            band="5G",
            standard="802.11ac",
            channel=36,
            center_freq_mhz=5180.0,
            bw_mhz=80,
        )
        case2 = MockTestCase(
            band="5G",
            standard="802.11ac",
            channel=36,
            center_freq_mhz=5180.0,
            bw_mhz=80,
        )
        
        key1 = self.pipeline.case_setup_key(case1)
        key2 = self.pipeline.case_setup_key(case2)
        
        self.assertEqual(key1, key2, "Identical cases should produce identical keys")

    def test_case_setup_key_detects_phy_mode_change(self):
        """Test 7: case_setup_key includes phy_mode changes."""
        case1 = MockTestCase(tags={"phy_mode": "HT"})
        case2 = MockTestCase(tags={"phy_mode": "VHT"})
        
        key1 = self.pipeline.case_setup_key(case1)
        key2 = self.pipeline.case_setup_key(case2)
        
        self.assertNotEqual(key1, key2, "Different phy_mode should produce different keys")


class TestDUTReconfigurePromptPayload(unittest.TestCase):
    """Test suite for build_dut_prompt_payload with WLAN fields."""

    def setUp(self):
        """Initialize CaseExecutionPipeline with mocks."""
        mock_run_repo = MagicMock()
        mock_metadata_recorder = MagicMock()
        self.pipeline = CaseExecutionPipeline(mock_run_repo, mock_metadata_recorder)

    def test_prompt_payload_includes_wlan_fields(self):
        """Test 8: Prompt payload includes WLAN-specific fields."""
        prev_case = MockTestCase(
            standard="802.11n",
            channel=36,
            center_freq_mhz=5180.0,
            bw_mhz=20,
            tags={"phy_mode": "HT"},
        )
        curr_case = MockTestCase(
            standard="802.11ac",
            channel=36,
            center_freq_mhz=5180.0,
            bw_mhz=80,
            tags={"phy_mode": "VHT"},
        )
        
        payload = self.pipeline.build_dut_prompt_payload(prev_case, curr_case, "MANUAL")
        
        # Check WLAN fields are present in previous/current dicts
        self.assertIn("standard", payload["previous"])
        self.assertIn("standard", payload["current"])
        self.assertIn("bandwidth_mhz", payload["previous"])
        self.assertIn("bandwidth_mhz", payload["current"])
        self.assertIn("channel", payload["previous"])
        self.assertIn("channel", payload["current"])
        self.assertIn("frequency_mhz", payload["previous"])
        self.assertIn("frequency_mhz", payload["current"])

    def test_prompt_payload_shows_standard_change(self):
        """Test 9: Payload instructions show standard change."""
        prev_case = MockTestCase(standard="802.11n")
        curr_case = MockTestCase(standard="802.11ac")
        
        payload = self.pipeline.build_dut_prompt_payload(prev_case, curr_case, "MANUAL")
        
        # Should generate instruction for standard change
        instructions_str = " ".join(payload["instructions"])
        self.assertIn("Standard", instructions_str, "Should show standard change")
        self.assertIn("802.11n", instructions_str, "Should show old standard")
        self.assertIn("802.11ac", instructions_str, "Should show new standard")

    def test_prompt_payload_shows_channel_change(self):
        """Test 10: Payload instructions show channel change."""
        prev_case = MockTestCase(channel=36)
        curr_case = MockTestCase(channel=40)
        
        payload = self.pipeline.build_dut_prompt_payload(prev_case, curr_case, "MANUAL")
        
        # Should generate instruction for channel change
        instructions_str = " ".join(payload["instructions"])
        self.assertIn("Channel", instructions_str, "Should show channel change")

    def test_prompt_payload_shows_bandwidth_change(self):
        """Test 11: Payload instructions show bandwidth change."""
        prev_case = MockTestCase(bw_mhz=20)
        curr_case = MockTestCase(bw_mhz=80)
        
        payload = self.pipeline.build_dut_prompt_payload(prev_case, curr_case, "MANUAL")
        
        # Should generate instruction for bandwidth change
        instructions_str = " ".join(payload["instructions"])
        self.assertIn("Bandwidth", instructions_str, "Should show bandwidth change")

    def test_prompt_payload_handles_first_case(self):
        """Test 12: Payload handles first case (no previous_case)."""
        curr_case = MockTestCase(
            standard="802.11ac",
            channel=36,
            bw_mhz=80,
        )
        
        payload = self.pipeline.build_dut_prompt_payload(None, curr_case, "MANUAL")
        
        # Should have payload with current case
        self.assertEqual(payload["current"]["standard"], "802.11ac")
        self.assertEqual(payload["current"]["channel"], 36)
        self.assertEqual(payload["current"]["bandwidth_mhz"], 80)
        self.assertIsNone(payload["previous_setup_key"], "Previous key should be None for first case")

    def test_prompt_payload_combines_multiple_changes(self):
        """Test 13: Payload shows all changes (standard + channel + bw)."""
        prev_case = MockTestCase(
            standard="802.11n",
            channel=36,
            bw_mhz=20,
            tags={"phy_mode": "HT"},
        )
        curr_case = MockTestCase(
            standard="802.11ac",
            channel=42,
            bw_mhz=80,
            tags={"phy_mode": "VHT"},
        )
        
        payload = self.pipeline.build_dut_prompt_payload(prev_case, curr_case, "MANUAL")
        
        # Should have multiple instructions
        self.assertGreater(len(payload["instructions"]), 1, "Should generate multiple change instructions")
        
        # Verify each change is captured
        instructions_str = " ".join(payload["instructions"])
        self.assertIn("Standard", instructions_str)
        self.assertIn("Channel", instructions_str)
        self.assertIn("Bandwidth", instructions_str)

    def test_prompt_payload_no_change_detected(self):
        """Test 14: No unnecessary instructions for identical cases."""
        case = MockTestCase(
            standard="802.11ac",
            channel=36,
            bw_mhz=80,
            center_freq_mhz=5180.0,
            tags={"phy_mode": "VHT"},
        )
        
        payload = self.pipeline.build_dut_prompt_payload(case, case, "MANUAL")
        
        # Should have no instructions since cases are identical
        self.assertEqual(len(payload["instructions"]), 0, "No instructions for identical cases")

    def test_prompt_payload_voltage_change_already_works(self):
        """Test 15: Legacy voltage changes still work (backward compatibility)."""
        prev_case = MockTestCase(tags={"voltage_condition": "NOMINAL"})
        curr_case = MockTestCase(tags={"voltage_condition": "HIGH"})
        
        payload = self.pipeline.build_dut_prompt_payload(prev_case, curr_case, "MANUAL")
        
        # Voltage_condition should be included
        self.assertEqual(payload["previous"]["voltage_condition"], "NOMINAL")
        self.assertEqual(payload["current"]["voltage_condition"], "HIGH")


class TestDUTReconfigureIntegration(unittest.TestCase):
    """Integration tests for DUT reconfigure logic."""

    def setUp(self):
        """Initialize CaseExecutionPipeline with mocks."""
        mock_run_repo = MagicMock()
        mock_metadata_recorder = MagicMock()
        self.pipeline = CaseExecutionPipeline(mock_run_repo, mock_metadata_recorder)

    def test_wlan_mode_transition_requires_reconfigure(self):
        """Test 16: WLAN mode transition (802.11n ??802.11ac) requires reconfigure."""
        case1 = MockTestCase(standard="802.11n", phy_mode="HT", channel=36, bw_mhz=20)
        case2 = MockTestCase(standard="802.11ac", phy_mode="VHT", channel=36, bw_mhz=20)
        
        key1 = self.pipeline.case_setup_key(case1)
        key2 = self.pipeline.case_setup_key(case2)
        
        self.assertNotEqual(key1, key2, "Mode transition should require reconfigure")

    def test_wlan_channel_transition_requires_reconfigure(self):
        """Test 17: WLAN channel transition requires reconfigure."""
        case1 = MockTestCase(standard="802.11ac", channel=36, bw_mhz=80)
        case2 = MockTestCase(standard="802.11ac", channel=40, bw_mhz=80)
        
        key1 = self.pipeline.case_setup_key(case1)
        key2 = self.pipeline.case_setup_key(case2)
        
        self.assertNotEqual(key1, key2, "Channel change should require reconfigure")

    def test_wlan_repeated_settings_no_reconfigure(self):
        """Test 18: Repeated WLAN settings don't trigger unnecessary reconfigure."""
        case1 = MockTestCase(standard="802.11ac", channel=36, bw_mhz=80)
        case2 = MockTestCase(standard="802.11ac", channel=36, bw_mhz=80)
        
        key1 = self.pipeline.case_setup_key(case1)
        key2 = self.pipeline.case_setup_key(case2)
        
        self.assertEqual(key1, key2, "Identical settings should not require reconfigure")


if __name__ == "__main__":
    unittest.main()
