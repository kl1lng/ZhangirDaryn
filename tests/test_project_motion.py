import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.motion_db import compose_phrase_segments
from src.project_motion import load_settings, prepare_project_videos, read_project_json, write_project_json


class AutomaticProjectMotionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "hello"
        (self.project / "videos").mkdir(parents=True)
        self.db = Path(self.temporary.name) / "motion.sqlite3"
        self.settings = {**load_settings(self.project), "license_name": "own recording",
                         "rights_confirmed": True, "signer_id": "signer-01"}

    def video(self, name="hello.avi"):
        path = self.project / "videos" / name
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 24, (32, 32))
        self.assertTrue(writer.isOpened())
        for _ in range(12):
            writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
        writer.release()
        return path

    def test_upload_preparation_registers_word_and_pose_for_text_without_retraining(self):
        video = self.video()
        sequence = np.zeros((12, 162), dtype=np.float32)
        sequence[:, 0:3] = (.45, .6, .01)
        sequence[:, 3:6] = (.48, .5, .01)
        pose = np.tile(np.array([.6, .35, .01, .4, .35, .01, .6, .5, .01,
                                 .4, .5, .01, .55, .6, .01, .45, .6, .01], dtype=np.float32), (12, 1))
        with patch("src.extract_landmarks.extract_from_video", return_value=sequence.tolist()) as hands, \
             patch("src.extract_landmarks.extract_body_pose_from_video", return_value=(pose, pose * .5)):
            first = prepare_project_videos(self.project, "сәлем", [video], self.settings, db_path=self.db)
            repeated = prepare_project_videos(self.project, "сәлем", [video], self.settings, db_path=self.db)
        self.assertEqual(first[0]["status"], "ready")
        self.assertEqual(first[0]["clip_id"], repeated[0]["clip_id"])
        self.assertEqual(hands.call_count, 1, "unchanged uploaded video must not be extracted twice")
        segments, found, missing = compose_phrase_segments("сәлем сәлем", db_path=self.db)
        self.assertEqual(found, ["сәлем", "сәлем"])
        self.assertFalse(missing)
        self.assertEqual(len(segments[0]["metadata"]["body_pose_world_landmarks"]), 12)
        report = read_project_json(self.project, "motion_import_report.json")
        self.assertEqual(report[video.name]["status"], "ready")

    def test_settings_survive_restart_and_invalid_settings_never_import(self):
        write_project_json(self.project, "motion_import_settings.json", self.settings)
        self.assertEqual(load_settings(self.project), self.settings)
        with patch("src.motion_db.import_video_motion") as importer:
            with self.assertRaises(ValueError):
                prepare_project_videos(self.project, "сәлем", [], {**self.settings, "rights_confirmed": False}, db_path=self.db)
        importer.assert_not_called()

    def test_one_failed_video_does_not_block_other_uploads_and_reports_retryable_error(self):
        bad, good = self.project / "videos/bad.mp4", self.project / "videos/good.mp4"
        progress = []
        with patch("src.motion_db.import_video_motion", side_effect=[ValueError("no hands"), 7]), \
             patch("src.motion_db.get_motion_clip", return_value={"metadata": {"hand_detection_coverage": 1, "body_pose_coverage": 0}}):
            rows = prepare_project_videos(self.project, "рахмет", [bad, good], self.settings,
                                          db_path=self.db, progress=lambda value, name: progress.append(value))
        self.assertEqual([row["status"] for row in rows], ["error", "hands_only"])
        self.assertEqual(progress, [.5, 1])
        self.assertEqual(len(read_project_json(self.project, "motion_import_report.json")), 2)

    def test_video_outside_project_is_rejected(self):
        with patch("src.motion_db.import_video_motion") as importer:
            rows = prepare_project_videos(self.project, "сәлем", [Path(self.temporary.name) / "other.mp4"], self.settings, db_path=self.db)
        self.assertEqual(rows[0]["status"], "error")
        importer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
