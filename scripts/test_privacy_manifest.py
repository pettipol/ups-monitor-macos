from __future__ import annotations

import plistlib
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from check_privacy_manifest import ManifestCheckError, check_privacy_manifests, main


PROFILE = {
    "NSPrivacyTracking": False,
    "NSPrivacyCollectedDataTypes": [],
}


class PrivacyManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.app_source = self.root / "App/PrivacyInfo.xcprivacy"
        self.widget_source = self.root / "Widget/PrivacyInfo.xcprivacy"
        self.app_bundle = self.root / "Synthetic.app"
        self.app_packaged = self.app_bundle / "Contents/Resources/PrivacyInfo.xcprivacy"
        self.widget_packaged = (
            self.app_bundle
            / "Contents/PlugIns/UPSMonitorWidget.appex/Contents/Resources/PrivacyInfo.xcprivacy"
        )
        self.write_manifest(self.app_source, PROFILE)
        self.write_manifest(self.widget_source, PROFILE)

    @staticmethod
    def write_manifest(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as manifest_file:
            plistlib.dump(value, manifest_file)

    def assert_invalid(self, expected_path: str) -> None:
        with self.assertRaises(ManifestCheckError) as caught:
            check_privacy_manifests(self.root)
        self.assertEqual(caught.exception.logical_path, expected_path)

    def test_valid_source_and_packaged_app_and_widget(self) -> None:
        self.write_manifest(self.app_packaged, PROFILE)
        self.write_manifest(self.widget_packaged, PROFILE)
        check_privacy_manifests(self.root, self.app_bundle)

    def test_missing_app_source_manifest(self) -> None:
        self.app_source.unlink()
        self.assert_invalid("App/PrivacyInfo.xcprivacy")

    def test_missing_widget_source_manifest(self) -> None:
        self.widget_source.unlink()
        self.assert_invalid("Widget/PrivacyInfo.xcprivacy")

    def test_malformed_source_manifest(self) -> None:
        self.app_source.write_bytes(b"not a plist")
        self.assert_invalid("App/PrivacyInfo.xcprivacy")

    def test_truncated_xml_is_reported_redacted_by_cli(self) -> None:
        self.app_source.write_bytes(
            b'<?xml version="1.0"?><plist version="1.0"><dict>SECRET-SYNTHETIC'
        )
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = main(["--source-root", str(self.root)])
        self.assertEqual(exit_code, 1)
        self.assertIn("App/PrivacyInfo.xcprivacy", stderr.getvalue())
        self.assertNotIn("SECRET-SYNTHETIC", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_tracking_integer_zero_is_not_boolean_false(self) -> None:
        value = dict(PROFILE, NSPrivacyTracking=0)
        self.write_manifest(self.app_source, value)
        self.assert_invalid("App/PrivacyInfo.xcprivacy")

    def test_tracking_string_true_is_rejected(self) -> None:
        value = dict(PROFILE, NSPrivacyTracking="true")
        self.write_manifest(self.app_source, value)
        self.assert_invalid("App/PrivacyInfo.xcprivacy")

    def test_nonempty_collected_data_is_rejected(self) -> None:
        value = dict(PROFILE, NSPrivacyCollectedDataTypes=[{"type": "synthetic"}])
        self.write_manifest(self.app_source, value)
        self.assert_invalid("App/PrivacyInfo.xcprivacy")

    def test_empty_non_array_collected_data_is_rejected(self) -> None:
        for value in ("", {}):
            with self.subTest(value_type=type(value).__name__):
                self.write_manifest(
                    self.app_source,
                    dict(PROFILE, NSPrivacyCollectedDataTypes=value),
                )
                self.assert_invalid("App/PrivacyInfo.xcprivacy")

    def test_extra_api_key_is_rejected(self) -> None:
        value = dict(PROFILE, NSPrivacyAccessedAPITypes=[])
        self.write_manifest(self.app_source, value)
        self.assert_invalid("App/PrivacyInfo.xcprivacy")

    def test_missing_packaged_app_manifest(self) -> None:
        self.write_manifest(self.widget_packaged, PROFILE)
        with self.assertRaises(ManifestCheckError) as caught:
            check_privacy_manifests(self.root, self.app_bundle)
        self.assertEqual(caught.exception.logical_path, "app/Contents/Resources/PrivacyInfo.xcprivacy")

    def test_missing_packaged_widget_manifest(self) -> None:
        self.write_manifest(self.app_packaged, PROFILE)
        with self.assertRaises(ManifestCheckError) as caught:
            check_privacy_manifests(self.root, self.app_bundle)
        self.assertEqual(
            caught.exception.logical_path,
            "app/Contents/PlugIns/UPSMonitorWidget.appex/Contents/Resources/PrivacyInfo.xcprivacy",
        )

    def test_packaged_app_profile_drift_is_rejected(self) -> None:
        self.write_manifest(self.app_packaged, dict(PROFILE, NSPrivacyTracking=True))
        self.write_manifest(self.widget_packaged, PROFILE)
        with self.assertRaises(ManifestCheckError) as caught:
            check_privacy_manifests(self.root, self.app_bundle)
        self.assertEqual(caught.exception.logical_path, "app/Contents/Resources/PrivacyInfo.xcprivacy")

    def test_packaged_widget_profile_drift_is_rejected(self) -> None:
        self.write_manifest(self.app_packaged, PROFILE)
        self.write_manifest(self.widget_packaged, dict(PROFILE, NSPrivacyCollectedDataTypes=["synthetic"]))
        with self.assertRaises(ManifestCheckError) as caught:
            check_privacy_manifests(self.root, self.app_bundle)
        self.assertEqual(
            caught.exception.logical_path,
            "app/Contents/PlugIns/UPSMonitorWidget.appex/Contents/Resources/PrivacyInfo.xcprivacy",
        )


if __name__ == "__main__":
    unittest.main()
