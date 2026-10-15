import tempfile
import unittest
import csv
import json
import os
import config
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode
from urllib.request import urlopen
from unittest.mock import patch

import numpy as np
from unittest.mock import MagicMock

from src.motion_matcher import MotionLibraryMatcher
from src.motion_db import add_motion_clip, compose_phrase_segments, register_gesture
from src.ingest_manifest import ManifestRow, import_manifest, read_manifest, read_manifest_text, save_uploaded_videos, select_manifest_batch
from src.motion_api import _MotionHandler
from src.normalize import PREPROCESSING_VERSION, normalize_sequence
from src.training_data import collect_training_sequences, prepare_training_data
from src.training_utils import grouped_split_indices, load_label_map, save_label_map, stratified_split_indices


class FluentSignersMetadataTests(unittest.TestCase):
    def test_metadata_generates_review_only_manifest_for_matching_local_videos(self):
        from src.fluentsigners50 import prepare_manifest

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata = root / "metadata"
            videos = root / "videos"
            metadata.mkdir()
            videos.mkdir()
            (metadata / "russian_translation.csv").write_text(
                "ID,Translation\n0,Привет\n1,Спасибо\n", encoding="utf-8"
            )
            (metadata / "gloss_annotation.csv").write_text(
                "ID,Gloss\n0,ПРИВЕТ\n1,СПАСИБО\n", encoding="utf-8"
            )
            (videos / "0.mp4").write_bytes(b"video")
            manifest = root / "motion_manifest.csv"

            found, missing = prepare_manifest(videos, manifest, metadata_dir=metadata)

            with manifest.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual((found, missing), (1, 1))
            self.assertEqual(rows[0]["phrase"], "ПРИВЕТ")
            self.assertEqual(rows[0]["language"], "ru-RU")
            self.assertEqual(rows[0]["rights_confirmed"], "false")
            self.assertIn("sample_id=0", rows[0]["source"])


class TrainingPipelineTests(unittest.TestCase):
    def test_database_motion_clip_is_returned_as_a_real_anatomical_playback_segment(self):
        from src.motion_db import find_gesture

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            gesture_id = register_gesture("сәлем", "сәлем", db_path=db_path)
            sequence = np.zeros((6, 162), dtype=np.float32)
            for frame in range(6):
                # Distinct anatomical hand coordinates must survive DB packing.
                sequence[frame, :63] = np.arange(63, dtype=np.float32) + frame
                sequence[frame, 63:126] = np.arange(63, dtype=np.float32) + 100 + frame
            body_pose = np.tile(
                np.asarray([0.6, 0.3, 0, 0.4, 0.3, 0,
                            0.65, 0.5, 0, 0.35, 0.5, 0,
                            0.65, 0.7, 0, 0.35, 0.7, 0], dtype=np.float32),
                (6, 1),
            )
            clip_id = add_motion_clip(
                gesture_id, sequence, fps=24, body_pose=body_pose,
                metadata={"hand_detection_coverage": 1.0, "training_eligible": True},
                db_path=db_path,
            )
            found = find_gesture("СӘЛЕМ", db_path=db_path)
            segments, labels, missing = compose_phrase_segments("сәлем", db_path=db_path)

        self.assertEqual(found["clip_id"], clip_id)
        self.assertEqual(found["sequence"].shape, (6, 162))
        np.testing.assert_array_equal(found["sequence"], sequence)
        self.assertEqual(segments[0]["clip_id"], clip_id)
        self.assertEqual(segments[0]["metadata"]["body_pose_landmarks"], body_pose.tolist())
        self.assertEqual((labels, missing), (["сәлем"], []))

    def test_phrase_registration_merges_case_and_punctuation_variants(self):
        from src.motion_db import connect as connect_motion_db, find_gesture

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            first_id = register_gesture(
                "сәлем досым", "Сәлем, досым!", db_path=db_path
            )
            second_id = register_gesture(
                "СӘЛЕМ ДОСЫМ", "сәлем досым", source="second-camera", db_path=db_path
            )
            add_motion_clip(first_id, np.ones((4, 162), dtype=np.float32), db_path=db_path)
            resolved = find_gesture("СӘЛЕМ, ДОСЫМ!", db_path=db_path)
            with connect_motion_db(db_path) as db:
                gesture_count = db.execute("SELECT COUNT(*) FROM gestures").fetchone()[0]

        self.assertEqual(first_id, second_id)
        self.assertEqual(gesture_count, 1)
        self.assertEqual(resolved["phrase"], "Сәлем, досым!")
        self.assertEqual(resolved["source_video"], None)

    def test_classifier_requires_two_distinct_labels_before_claiming_recognition(self):
        from src.predict import model_has_distinguishable_classes

        self.assertFalse(model_has_distinguishable_classes({0: "сәлем"}))
        self.assertFalse(model_has_distinguishable_classes({0: "Сәлем", 1: " сәлем "}))
        self.assertTrue(model_has_distinguishable_classes({0: "сәлем", 1: "рахмет"}))

    def test_phrase_composer_uses_curated_kazakh_inflection_alias(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            gesture_id = register_gesture("сәлем", "сәлем", db_path=db_path)
            from src.motion_db import register_gesture_alias
            register_gesture_alias(gesture_id, "сәлеммен", db_path=db_path)
            clip_id = add_motion_clip(
                gesture_id, np.full((5, 162), 0.4, dtype=np.float32),
                fps=24.0, db_path=db_path,
            )

            segments, found, missing = compose_phrase_segments(
                "Сәлеммен, белгісізге!", db_path=db_path
            )

        self.assertEqual([segment["type"] for segment in segments], ["motion", "missing"])
        self.assertEqual(segments[0]["label"], "сәлеммен")
        self.assertEqual(segments[0]["clip_id"], clip_id)
        self.assertEqual(segments[0]["fps"], 24.0)
        self.assertEqual(found, ["сәлеммен"])
        self.assertEqual(missing, ["белгісізге"])

    def test_phrase_composer_does_not_guess_unregistered_kazakh_inflection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            gesture_id = register_gesture("сәлем", "сәлем", db_path=db_path)
            add_motion_clip(gesture_id, np.ones((3, 162), dtype=np.float32), db_path=db_path)

            _segments, found, missing = compose_phrase_segments("сәлеммен", db_path=db_path)

        self.assertEqual(found, [])
        self.assertEqual(missing, ["сәлеммен"])

    def test_phrase_assembly_uses_untracked_pause_not_invented_between_sign_motion(self):
        from src.motion_db import compose_phrase

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            first = np.full((3, 162), 0.1, dtype=np.float32)
            second = np.full((5, 162), 0.9, dtype=np.float32)
            first_id = register_gesture("бір", "бір", db_path=db_path)
            second_id = register_gesture("екі", "екі", db_path=db_path)
            add_motion_clip(first_id, first, db_path=db_path)
            add_motion_clip(second_id, second, db_path=db_path)
            assembled, found, missing = compose_phrase(
                "бір екі", gap_frames=2, db_path=db_path
            )

        np.testing.assert_array_equal(assembled[:3], first)
        np.testing.assert_array_equal(assembled[3:5], np.zeros((2, 162), dtype=np.float32))
        np.testing.assert_array_equal(assembled[5:], second)
        self.assertEqual(found, ["бір", "екі"])
        self.assertEqual(missing, [])

    def test_backfill_video_geometry_adds_dimensions_without_reextracting_landmarks(self):
        from src.motion_db import backfill_video_geometry_metadata, find_gesture

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "source.mp4"
            video.write_bytes(b"video")
            database = root / "motion.sqlite3"
            gesture_id = register_gesture("сәлем", db_path=database)
            sequence = np.zeros((3, 162), dtype=np.float32)
            sequence[:, 0] = 0.5
            sequence[:, 4] = 0.55
            clip_id = add_motion_clip(
                gesture_id, sequence, source_video=str(video),
                metadata={"raw_video": True}, db_path=database,
            )
            capture = MagicMock()
            capture.isOpened.return_value = True
            capture.get.side_effect = [1920.0, 1080.0]
            with patch("cv2.VideoCapture", return_value=capture):
                self.assertEqual(backfill_video_geometry_metadata(database), 1)
                self.assertEqual(backfill_video_geometry_metadata(database), 0)
            stored = find_gesture("сәлем", db_path=database)

        self.assertEqual(stored["clip_id"], clip_id)
        self.assertEqual(stored["sequence"].shape, sequence.shape)
        self.assertEqual(stored["metadata"]["frame_width"], 1920)
        self.assertEqual(stored["metadata"]["frame_height"], 1080)
        self.assertAlmostEqual(stored["metadata"]["image_aspect_ratio"], 16 / 9)

    def test_mediapipe_handedness_is_canonicalized_for_mirrored_and_raw_video(self):
        from src.extract_landmarks import canonical_hand_label

        self.assertEqual(canonical_hand_label("Left"), "Right")
        self.assertEqual(canonical_hand_label("Right"), "Left")
        self.assertEqual(canonical_hand_label("Left", input_mirrored=True), "Left")
        self.assertEqual(canonical_hand_label("Right", input_mirrored=True), "Right")

    def test_live_frame_keeps_face_features_when_hand_detection_drops(self):
        from types import SimpleNamespace
        from src.predict import extract_live_frame_features

        detection_result = SimpleNamespace(hand_landmarks=[], handedness=[])
        face_values = [0.25] * 36
        with patch("src.predict.extract_face_features", return_value=face_values) as face_extractor:
            frame, hand_found = extract_live_frame_features(
                detection_result, np.zeros((360, 640, 3), dtype=np.uint8), object(), object()
            )
        self.assertFalse(hand_found)
        self.assertEqual(len(frame), 162)
        self.assertEqual(frame[:126], [0.0] * 126)
        self.assertEqual(frame[126:], face_values)
        face_extractor.assert_called_once()

    def test_face_crop_landmarks_are_mapped_back_to_full_frame(self):
        from types import SimpleNamespace
        from src.extract_landmarks import FACE_INDICES, extract_face_features

        detection = SimpleNamespace(
            bounding_box=SimpleNamespace(origin_x=485, origin_y=46, width=268, height=268),
            categories=[SimpleNamespace(score=0.45)],
        )

        class RegionDetector:
            def detect(self, image):
                return SimpleNamespace(detections=[detection])

        class FaceLandmarker:
            def detect(self, image):
                if image.numpy_view().shape[:2] == (720, 1280):
                    return SimpleNamespace(face_landmarks=[])
                landmarks = [SimpleNamespace(x=0.5, y=0.5, z=-0.1) for _ in range(max(FACE_INDICES) + 1)]
                return SimpleNamespace(face_landmarks=[landmarks])

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        features = extract_face_features(frame, RegionDetector(), FaceLandmarker())
        crop_left = 485 - int(268 * 0.45)
        crop_top = max(0, 46 - int(268 * 0.45))
        crop_width = min(1280, 485 + 268 + int(268 * 0.45)) - crop_left
        crop_height = min(720, 46 + 268 + int(268 * 0.45)) - crop_top
        side = max(crop_width, crop_height)
        pad_left = (side - crop_width) // 2
        pad_top = (side - crop_height) // 2
        self.assertEqual(len(features), 36)
        self.assertAlmostEqual(features[0], (crop_left + side * 0.5 - pad_left) / 1280)
        self.assertAlmostEqual(features[1], (crop_top + side * 0.5 - pad_top) / 720)
        self.assertAlmostEqual(features[2], -0.1 * side / 1280)

    def test_video_import_records_hand_and_face_tracking_coverage(self):
        from src.motion_db import find_gesture, get_motion_clip, import_video_motion, connect as connect_motion_db

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "sign.mp4"
            video.write_bytes(b"test video source")
            sequence = np.zeros((10, 162), dtype=np.float32)
            sequence[:, 0] = 0.5
            sequence[:, 1] = 0.5
            sequence[:, 3] = 0.55
            sequence[:, 4] = 0.5
            sequence[:6, 126:] = 0.25
            capture = MagicMock()
            capture.isOpened.return_value = True
            capture.get.return_value = 24.0
            with patch("cv2.VideoCapture", return_value=capture), patch(
                "src.extract_landmarks.extract_from_video", return_value=sequence.tolist()
            ):
                clip_id = import_video_motion(
                    "сәлем", video, phrase="сәлем", rights_confirmed=True,
                    license_name="Собственная запись владельца проекта",
                    db_path=root / "motion.sqlite3"
                )
            clip = find_gesture("сәлем", db_path=root / "motion.sqlite3")
            exact_clip = get_motion_clip(clip_id, db_path=root / "motion.sqlite3")
            with connect_motion_db(root / "motion.sqlite3") as db:
                stored_license = db.execute(
                    "SELECT license FROM gestures WHERE lemma=?", ("сәлем",)
                ).fetchone()[0]

        self.assertAlmostEqual(clip["metadata"]["hand_detection_coverage"], 1.0)
        self.assertAlmostEqual(clip["metadata"]["face_detection_coverage"], 0.6)
        self.assertEqual(clip["metadata"]["frames_with_face"], 6)
        self.assertTrue(clip["metadata"]["training_eligible"])
        self.assertEqual(clip["metadata"]["frame_width"], 24)
        self.assertEqual(clip["metadata"]["frame_height"], 24)
        self.assertEqual(clip["metadata"]["image_aspect_ratio"], 1.0)
        self.assertTrue(clip["metadata"]["rights_confirmed"])
        self.assertEqual(stored_license, "Собственная запись владельца проекта")
        np.testing.assert_array_equal(exact_clip["sequence"], sequence)

    def test_video_import_converts_annotation_seconds_to_original_frame_range(self):
        from src.motion_db import find_gesture, import_video_motion
        from src.motion_db import connect as connect_motion_db

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "sentence.mp4"
            video.write_bytes(b"annotated sentence video")
            sequence = np.zeros((12, 162), dtype=np.float32)
            sequence[:, 0] = 0.5
            sequence[:, 1] = 0.5
            sequence[:, 3] = 0.55
            sequence[:, 4] = 0.5
            capture = MagicMock()
            capture.isOpened.return_value = True
            from cv2 import CAP_PROP_FPS, CAP_PROP_FRAME_COUNT, CAP_PROP_FRAME_WIDTH, CAP_PROP_FRAME_HEIGHT
            capture.get.side_effect = lambda prop: {
                CAP_PROP_FPS: 24.0,
                CAP_PROP_FRAME_COUNT: 100,
                CAP_PROP_FRAME_WIDTH: 640,
                CAP_PROP_FRAME_HEIGHT: 480,
            }.get(prop, 0)
            database = root / "motion.sqlite3"
            with patch("cv2.VideoCapture", return_value=capture), patch(
                "src.extract_landmarks.extract_from_video", return_value=sequence.tolist()
            ) as extract:
                import_video_motion(
                    "сәлем", video, phrase="сәлем", start_seconds=0.25,
                    end_seconds=0.75, db_path=database,
                )
            extract.assert_called_once_with(
                str(video.resolve()), input_mirrored=False, start_frame=6, end_frame=18
            )
            with connect_motion_db(database) as db:
                row = db.execute("SELECT start_frame,end_frame,frame_count FROM motion_clips").fetchone()
            self.assertEqual(row, (6, 18, 12))
            clip = find_gesture("сәлем", db_path=database)
        self.assertEqual(clip["metadata"]["clip_start_seconds"], 0.25)
        self.assertEqual(clip["metadata"]["clip_end_seconds"], 0.75)

    def test_manifest_reuses_full_video_landmarks_for_all_annotated_segments(self):
        from src.motion_db import compose_phrase_segments, connect as connect_motion_db

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "sentence.mp4"
            video.write_bytes(b"one long annotated source")
            database = root / "motion.sqlite3"
            full_sequence = np.zeros((100, 162), dtype=np.float32)
            full_sequence[:, 0:2] = (0.5, 0.5)
            full_sequence[:, 3:5] = (0.55, 0.5)
            capture = MagicMock()
            capture.isOpened.return_value = True
            from cv2 import CAP_PROP_FPS, CAP_PROP_FRAME_COUNT, CAP_PROP_FRAME_WIDTH, CAP_PROP_FRAME_HEIGHT
            capture.get.side_effect = lambda prop: {
                CAP_PROP_FPS: 24.0,
                CAP_PROP_FRAME_COUNT: 100,
                CAP_PROP_FRAME_WIDTH: 640,
                CAP_PROP_FRAME_HEIGHT: 480,
            }.get(prop, 0)
            rows = [
                ManifestRow(2, video, "сәлем", "local", "permission", "signer-1", "kk-KZ",
                            start_seconds=0.25, end_seconds=0.75),
                ManifestRow(3, video, "рахмет", "local", "permission", "signer-1", "kk-KZ",
                            start_seconds=1.25, end_seconds=1.75),
            ]
            with patch("cv2.VideoCapture", return_value=capture), patch(
                "src.extract_landmarks.extract_from_video", return_value=full_sequence.tolist()
            ) as extract, patch(
                "src.extract_landmarks.extract_body_pose_from_video", return_value=None
            ) as extract_pose:
                imported, failures = import_manifest(rows, db_path=database)
            self.assertEqual(len(imported), 2, failures)
            self.assertEqual(failures, [])
            extract.assert_called_once_with(
                str(video.resolve()), input_mirrored=False, start_frame=0, end_frame=100
            )
            extract_pose.assert_called_once()
            with connect_motion_db(database) as db:
                ranges = db.execute(
                    "SELECT start_frame,end_frame,frame_count FROM motion_clips ORDER BY start_frame"
                ).fetchall()
            self.assertEqual(ranges, [(6, 18, 12), (30, 42, 12)])
            segments, found, missing = compose_phrase_segments("сәлем рахмет", db_path=database)
        self.assertEqual(found, ["сәлем", "рахмет"])
        self.assertEqual(missing, [])
        self.assertEqual([segment["type"] for segment in segments], ["motion", "motion"])
        self.assertEqual([len(segment["sequence"]) for segment in segments], [12, 12])
        self.assertEqual([segment["source_video"] for segment in segments], [str(video.resolve())] * 2)
        self.assertEqual([(segment["start_frame"], segment["end_frame"]) for segment in segments],
                         [(6, 18), (30, 42)])

    def test_video_import_deduplicates_identical_copied_source_video(self):
        from src.motion_db import import_video_motion

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_video, copied_video = root / "first.mp4", root / "copy.mp4"
            first_video.write_bytes(b"same source video")
            copied_video.write_bytes(b"same source video")
            sequence = np.zeros((10, 162), dtype=np.float32)
            sequence[:, 0] = 0.5
            sequence[:, 1] = 0.5
            sequence[:, 3] = 0.55
            sequence[:, 4] = 0.5
            capture = MagicMock()
            capture.isOpened.return_value = True
            capture.get.return_value = 24.0
            database = root / "motion.sqlite3"
            with patch("cv2.VideoCapture", return_value=capture), patch(
                "src.extract_landmarks.extract_from_video", return_value=sequence.tolist()
            ) as extract:
                first_id = import_video_motion(
                    "сәлем", first_video, phrase="сәлем", db_path=database
                )
                duplicate_id = import_video_motion(
                    "сәлем", copied_video, phrase="сәлем", db_path=database
                )

            self.assertEqual(first_id, duplicate_id)
            extract.assert_called_once()

    def test_curated_phrase_alias_reuses_the_database_motion_without_guessing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            greeting_id = register_gesture("сәлем", "сәлем", db_path=db_path)
            clip_id = add_motion_clip(
                greeting_id, np.ones((3, 162), dtype=np.float32), fps=24.0, db_path=db_path
            )
            from src.motion_db import register_gesture_alias, find_gesture
            register_gesture_alias(
                greeting_id, "Сәлеметсіз бе", language="kk-KZ", db_path=db_path
            )
            segments, found, missing = compose_phrase_segments(
                "СӘЛЕМЕТСІЗ БЕ!", db_path=db_path
            )
            resolved = find_gesture("сәлеметсіз бе", db_path=db_path)
            other_id = register_gesture("рахмет", "рахмет", db_path=db_path)
            with self.assertRaisesRegex(ValueError, "уже привязан"):
                register_gesture_alias(
                    other_id, "сәлеметсіз бе", language="kk-KZ", db_path=db_path
                )
            with self.assertRaisesRegex(ValueError, "названием другого жеста"):
                register_gesture_alias(
                    greeting_id, "рахмет", language="kk-KZ", db_path=db_path
                )
            with self.assertRaisesRegex(ValueError, "уже используется как вариант"):
                register_gesture("сәлеметсіз бе", "сәлеметсіз бе", db_path=db_path)
            still_resolved = find_gesture("сәлеметсіз бе", db_path=db_path)

        self.assertEqual(found, ["сәлеметсіз бе"])
        self.assertEqual(missing, [])
        self.assertEqual([segment["type"] for segment in segments], ["motion"])
        self.assertEqual(segments[0]["clip_id"], clip_id)
        self.assertEqual(resolved["clip_id"], clip_id)
        self.assertEqual(still_resolved["gesture_id"], greeting_id)

    def test_motion_dictionary_is_scoped_to_selected_text_language(self):
        from src.motion_db import compose_phrase_segments

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            gesture_id = register_gesture(
                "привет", "привет", language="ru-RU", db_path=db_path
            )
            clip_id = add_motion_clip(
                gesture_id, np.ones((4, 162), dtype=np.float32), db_path=db_path
            )

            russian_segments, russian_found, russian_missing = compose_phrase_segments(
                "Привет", language="ru-RU", db_path=db_path
            )
            kazakh_segments, kazakh_found, kazakh_missing = compose_phrase_segments(
                "Привет", language="kk-KZ", db_path=db_path
            )

        self.assertEqual(russian_found, ["привет"])
        self.assertEqual(russian_missing, [])
        self.assertEqual(russian_segments[0]["clip_id"], clip_id)
        self.assertEqual(kazakh_segments, [{"type": "missing", "label": "привет"}])
        self.assertEqual(kazakh_found, [])
        self.assertEqual(kazakh_missing, ["привет"])

    def test_text_lookup_skips_low_tracking_clip_and_uses_next_eligible_recording(self):
        from src.motion_db import find_gesture

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            gesture_id = register_gesture("сәлем", "сәлем", db_path=db_path)
            poor_id = add_motion_clip(
                gesture_id, np.full((4, 162), 0.1, dtype=np.float32),
                metadata={"hand_detection_coverage": 0.2, "training_eligible": False},
                db_path=db_path,
            )
            selected = find_gesture("сәлем", db_path=db_path)
            good_id = add_motion_clip(
                gesture_id, np.full((4, 162), 0.2, dtype=np.float32),
                metadata={"hand_detection_coverage": 0.9, "training_eligible": True},
                db_path=db_path,
            )
            selected_after_good_import = find_gesture("сәлем", db_path=db_path)
            from src.motion_db import compose_phrase_segments
            segments, found, missing = compose_phrase_segments("сәлем", db_path=db_path)
        self.assertIsNone(selected)
        self.assertEqual(selected_after_good_import["clip_id"], good_id)
        self.assertNotEqual(good_id, poor_id)
        self.assertEqual(found, ["сәлем"])
        self.assertEqual(missing, [])
        self.assertEqual(segments[0]["clip_id"], good_id)

    def test_text_lookup_prefers_full_body_motion_over_newer_hand_only_clip(self):
        from src.motion_db import find_gesture

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            gesture_id = register_gesture("сәлем", "сәлем", db_path=db_path)
            pose_clip_id = add_motion_clip(
                gesture_id, np.full((4, 162), 0.3, dtype=np.float32),
                body_pose=np.full((4, 18), 0.4, dtype=np.float32), fps=24.0,
                metadata={"hand_detection_coverage": 0.85}, db_path=db_path,
            )
            add_motion_clip(
                gesture_id, np.full((4, 162), 0.6, dtype=np.float32), fps=60.0,
                metadata={"hand_detection_coverage": 0.99}, db_path=db_path,
            )
            selected = find_gesture("сәлем", db_path=db_path)

        self.assertEqual(selected["clip_id"], pose_clip_id)
        self.assertEqual(selected["fps"], 24.0)
        self.assertGreaterEqual(selected["metadata"]["body_pose_coverage"], 0.5)

    def test_text_lookup_does_not_choose_newest_clip_for_ambiguous_lemma(self):
        from src.motion_db import find_gesture

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            first_gesture = register_gesture(
                "сәлем", "сәлем ресми", db_path=db_path
            )
            first_clip = add_motion_clip(
                first_gesture, np.full((4, 162), 0.1, dtype=np.float32), db_path=db_path
            )
            second_gesture = register_gesture(
                "сәлем", "сәлем бейресми", db_path=db_path
            )
            add_motion_clip(
                second_gesture, np.full((4, 162), 0.2, dtype=np.float32), db_path=db_path
            )
            ambiguous = find_gesture("сәлем", db_path=db_path)
            exact = find_gesture("сәлем ресми", db_path=db_path)
            segments, found, missing = compose_phrase_segments("сәлем", db_path=db_path)

        self.assertIsNone(ambiguous)
        self.assertEqual(exact["clip_id"], first_clip)
        self.assertEqual(segments, [{"type": "missing", "label": "сәлем"}])
        self.assertEqual(found, [])
        self.assertEqual(missing, ["сәлем"])

    def test_exact_phrase_match_precedes_a_newer_lemma_and_normalizes_punctuation(self):
        from src.motion_db import find_gesture

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            phrase_gesture = register_gesture(
                "сәлем", "сәлем досым", db_path=db_path
            )
            phrase_clip = add_motion_clip(
                phrase_gesture, np.full((3, 162), 1.0, dtype=np.float32),
                db_path=db_path,
            )
            lemma_gesture = register_gesture(
                "сәлем досым", "басқа тіркес", db_path=db_path
            )
            add_motion_clip(
                lemma_gesture, np.full((3, 162), 2.0, dtype=np.float32),
                db_path=db_path,
            )
            result = find_gesture("СӘЛЕМ, ДОСЫМ!", db_path=db_path)

        self.assertIsNotNone(result)
        self.assertEqual(result["clip_id"], phrase_clip)
        self.assertEqual(result["phrase"], "сәлем досым")

    def test_library_coverage_counts_only_usable_clips_and_distinct_sources(self):
        from src.motion_db import library_coverage, library_stats

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            kk_gesture = register_gesture("сәлем", "сәлем", db_path=db_path)
            add_motion_clip(
                kk_gesture, np.ones((3, 162), dtype=np.float32),
                source_video="/videos/a.mp4", signer_id="signer-a",
                metadata={"hand_detection_coverage": 0.9, "body_pose_coverage": 0.8,
                          "source_video_sha256": "same-video"},
                db_path=db_path,
            )
            add_motion_clip(
                kk_gesture, np.ones((3, 162), dtype=np.float32),
                source_video="/videos/b.mp4", signer_id="signer-a",
                metadata={"hand_detection_coverage": 0.9}, db_path=db_path,
            )
            add_motion_clip(
                kk_gesture, np.ones((3, 162), dtype=np.float32),
                source_video="/videos/../videos/a.mp4", signer_id="signer-a",
                metadata={"hand_detection_coverage": 0.9, "body_pose_coverage": 0.8},
                db_path=db_path,
            )
            add_motion_clip(
                kk_gesture, np.ones((3, 162), dtype=np.float32),
                source_video="/imported-copy/a.mp4", signer_id="signer-a",
                metadata={"hand_detection_coverage": 0.9,
                          "source_video_sha256": "same-video"},
                db_path=db_path,
            )
            add_motion_clip(
                kk_gesture, np.ones((3, 162), dtype=np.float32),
                source_video="/videos/poor.mp4",
                metadata={"hand_detection_coverage": 0.1, "training_eligible": False},
                db_path=db_path,
            )
            ru_gesture = register_gesture(
                "привет", "привет", language="ru-RU", db_path=db_path
            )
            add_motion_clip(
                ru_gesture, np.ones((3, 162), dtype=np.float32),
                source_video="/videos/ru.mp4", db_path=db_path,
            )
            result = library_coverage(db_path=db_path)
            stats = library_stats(db_path=db_path)

        self.assertEqual(result, [
            {"language": "kk-KZ", "catalog_gestures": 1, "gestures": 1,
             "uncovered_gestures": [], "eligible_clips": 2,
             "validation_groups": 1, "body_pose_clips": 1},
            {"language": "ru-RU", "catalog_gestures": 1, "gestures": 1,
             "uncovered_gestures": [], "eligible_clips": 1,
             "validation_groups": 1, "body_pose_clips": 0},
        ])
        self.assertEqual(stats, {
            "gestures": 2, "clips": 3,
            "stored_gestures": 2, "stored_clips": 6,
            "unique_sources": 4,
        })

    def test_library_stats_merges_relative_absolute_and_hash_source_aliases(self):
        from src.motion_db import library_stats

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            gesture_id = register_gesture("сәлем", "сәлем", db_path=db_path)
            add_motion_clip(
                gesture_id, np.ones((3, 162), dtype=np.float32),
                source_video="data/salem/videos/A73_1.mp4", db_path=db_path,
            )
            add_motion_clip(
                gesture_id, np.ones((3, 162), dtype=np.float32),
                source_video=str(Path(config.BASE_DIR) / "data/salem/videos/A73_1.mp4"),
                metadata={"source_video_sha256": "same-video"}, db_path=db_path,
            )
            stats = library_stats(db_path=db_path)

        self.assertEqual(stats["stored_clips"], 2)
        self.assertEqual(stats["unique_sources"], 1)

    def test_library_coverage_reports_catalog_labels_without_usable_motion(self):
        from src.motion_db import library_coverage

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            empty_label = register_gesture("рахмет", "рахмет", db_path=db_path)
            add_motion_clip(
                empty_label, np.ones((3, 162), dtype=np.float32),
                metadata={"hand_detection_coverage": 0.1, "training_eligible": False},
                db_path=db_path,
            )
            result = library_coverage(db_path=db_path)

        self.assertEqual(result, [{
            "language": "kk-KZ", "catalog_gestures": 1, "gestures": 0,
            "uncovered_gestures": ["рахмет"],
            "eligible_clips": 0, "validation_groups": 0, "body_pose_clips": 0,
        }])

    def test_compose_api_returns_ordered_database_motion_with_per_clip_fps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            for label, fps, marker in (("first", 24.0, 1.0), ("second", 60.0, 2.0)):
                gesture_id = register_gesture(label, label, db_path=db_path)
                add_motion_clip(
                    gesture_id,
                    np.full((3, 162), marker, dtype=np.float32),
                    fps=fps,
                    db_path=db_path,
                )

            from src.motion_db import compose_phrase_segments as compose_from_db
            server = ThreadingHTTPServer(("127.0.0.1", 0), _MotionHandler)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch(
                    "src.motion_db.compose_phrase_segments",
                    side_effect=lambda text, language="kk-KZ": compose_from_db(
                        text, language=language, db_path=db_path
                    ),
                ):
                    query = urlencode({"text": "first unknown second"})
                    with urlopen(f"http://127.0.0.1:{server.server_port}/api/compose?{query}") as response:
                        payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual([item["type"] for item in payload["segments"]], ["motion", "missing", "motion"])
        self.assertEqual([item["label"] for item in payload["segments"]], ["first", "unknown", "second"])
        motion_segments = [item for item in payload["segments"] if item["type"] == "motion"]
        self.assertEqual([item["fps"] for item in motion_segments], [24.0, 60.0])
        self.assertEqual([item["sequence"][0][0] for item in motion_segments], [1.0, 2.0])
        self.assertEqual(payload["missing"], ["unknown"])

    def test_avatar_route_embeds_motion_selected_from_database(self):
        sequence = np.arange(4 * 162, dtype=np.float32).reshape(4, 162)
        next_sequence = np.full((2, 162), 0.25, dtype=np.float32)
        segments = [
            {"type": "motion", "label": "hello", "sequence": sequence, "fps": 24.0},
            {"type": "missing", "label": "unknown"},
            {"type": "motion", "label": "world", "sequence": next_sequence, "fps": 60.0},
        ]
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MotionHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("src.motion_db.compose_phrase_segments", return_value=(segments, ["hello", "world"], ["unknown"])):
                with urlopen(f"http://127.0.0.1:{server.server_port}/avatar?text=hello") as response:
                    html = response.read().decode("utf-8")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertIn("let activeSequence=" + json.dumps(sequence.tolist(), separators=(",", ":")), html)
        self.assertIn('let activeLabel="hello";', html)
        self.assertIn("let activeFps=24.0;", html)
        self.assertIn('"fps":24.0', html)
        self.assertIn('"fps":60.0', html)
        self.assertIn('let initialMissing=["unknown"];', html)
        self.assertIn("voiceQueue=clips.slice(1)", html)
        self.assertNotIn("__MOTION_", html)

    def test_database_motion_with_face_track_reaches_api_and_avatar_unchanged(self):
        from src.motion_db import compose_phrase_segments as compose_from_db

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            gesture_id = register_gesture("сәлем", "сәлем", db_path=db_path)
            sequence = np.zeros((56, 162), dtype=np.float32)
            sequence[:, 0:3] = (0.5, 0.5, 0.01)
            sequence[:, 3:6] = (0.51, 0.49, 0.01)
            sequence[:, 126:162] = np.arange(36, dtype=np.float32) / 100
            body_pose = np.zeros((56, 18), dtype=np.float32)
            body_pose[:, 0::3] = .4
            body_pose[:, 1::3] = .3
            source_video = "C:/dataset/greeting.mp4"
            add_motion_clip(
                gesture_id, sequence, source_video=source_video, fps=24.0,
                start_frame=120, end_frame=176, body_pose=body_pose, db_path=db_path,
            )

            server = ThreadingHTTPServer(("127.0.0.1", 0), _MotionHandler)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                resolver = lambda text, **kwargs: compose_from_db(text, db_path=db_path)
                with patch("src.motion_db.compose_phrase_segments", side_effect=resolver):
                    encoded_text = urlencode({"text": "сәлем"})
                    with urlopen(f"http://127.0.0.1:{server.server_port}/api/compose?{encoded_text}") as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    with urlopen(f"http://127.0.0.1:{server.server_port}/avatar?{encoded_text}") as response:
                        html = response.read().decode("utf-8")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        serialized = json.dumps(sequence.tolist(), ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(payload["found"], ["сәлем"])
        self.assertEqual(payload["missing"], [])
        self.assertEqual(payload["segments"][0]["fps"], 24.0)
        self.assertEqual(payload["segments"][0]["sequence"], sequence.tolist())
        self.assertEqual(payload["segments"][0]["body_pose"], body_pose.tolist())
        self.assertEqual(payload["segments"][0]["source_video"], source_video)
        self.assertEqual(payload["segments"][0]["start_frame"], 120)
        self.assertEqual(payload["segments"][0]["end_frame"], 176)
        self.assertIn("let activeSequence=" + serialized, html)
        self.assertIn('"sequence":' + serialized, html)
        self.assertIn('let activeBodyPose=' + json.dumps(body_pose.tolist(), separators=(",", ":")), html)

    def test_body_pose_track_round_trips_database_api_and_avatar(self):
        from src.motion_db import find_gesture

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            gesture_id = register_gesture("сәлем", "сәлем", db_path=db_path)
            sequence = np.zeros((4, 162), dtype=np.float32)
            sequence[:, 0:3] = (0.5, 0.5, 0.01)
            sequence[:, 3:6] = (0.52, 0.5, 0.01)
            pose = np.zeros((4, 18), dtype=np.float32)
            pose[:, 0:18:3] = np.linspace(.35, .52, 6)
            pose[:, 1:18:3] = np.linspace(.3, .7, 6)
            world_pose = pose * 0.5
            add_motion_clip(gesture_id, sequence, body_pose=pose,
                            body_pose_world=world_pose, db_path=db_path)
            stored = find_gesture("сәлем", db_path=db_path)
            np.testing.assert_allclose(stored["metadata"]["body_pose_landmarks"], pose)
            np.testing.assert_allclose(stored["metadata"]["body_pose_world_landmarks"], world_pose)
            self.assertEqual(stored["metadata"]["body_pose_frames"], 4)
            self.assertEqual(stored["metadata"]["body_pose_coverage"], 1.0)
            self.assertEqual(stored["metadata"]["left_arm_pose_coverage"], 1.0)
            segments, _, _ = compose_phrase_segments("сәлем", db_path=db_path)
            self.assertEqual(segments[0]["metadata"]["body_pose_landmarks"], pose.tolist())
            with self.assertRaisesRegex(ValueError, "форму"):
                add_motion_clip(gesture_id, sequence, body_pose=pose[:-1], db_path=db_path)

    def test_saved_model_labels_carry_and_enforce_preprocessing_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "models" / "label_map.json"
            save_label_map(
                {"сәлем": 0, "рахмет": 1}, path,
                training_metadata={"validation_strategy": "grouped_by_signer_or_source"},
            )
            loaded = load_label_map(path)
            metadata = json.loads(path.read_text(encoding="utf-8"))["training"]
            path.write_text('{"сәлем": 0}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_label_map(path)
        self.assertEqual(loaded, {0: "сәлем", 1: "рахмет"})
        self.assertEqual(metadata["validation_strategy"], "grouped_by_signer_or_source")

    def test_normalization_preserves_hand_location_and_shared_geometry(self):
        def make_sequence(left_x, right_x):
            sequence = np.zeros((2, 162), dtype=np.float32)
            for frame in range(2):
                for offset, wrist_x in ((0, left_x), (63, right_x)):
                    for point in range(21):
                        sequence[frame, offset + point * 3] = wrist_x + (point % 5) * 0.012
                        sequence[frame, offset + point * 3 + 1] = 0.45 + (point // 5) * 0.012
            return sequence

        centered = normalize_sequence(make_sequence(0.35, 0.65))
        shifted = normalize_sequence(make_sequence(0.45, 0.75))
        self.assertEqual(PREPROCESSING_VERSION, 2)
        self.assertLess(centered[0, 0], 0.0)
        self.assertGreater(centered[0, 63], 0.0)
        self.assertNotAlmostEqual(float(centered[0, 0]), float(shifted[0, 0]))
        self.assertAlmostEqual(
            float(centered[0, 63] - centered[0, 0]),
            float(shifted[0, 63] - shifted[0, 0]),
            places=5,
        )
        scaled = make_sequence(0.35, 0.65)
        scaled[:, 0:126:3] = (scaled[:, 0:126:3] - 0.5) * 1.7 + 0.5
        scaled[:, 1:126:3] = (scaled[:, 1:126:3] - 0.5) * 1.7 + 0.5
        scaled[:, 2:126:3] *= 1.7
        self.assertTrue(np.allclose(centered, normalize_sequence(scaled), atol=1e-6))

    def test_manifest_validates_each_label_and_rights_and_imports_rows_individually(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "hello.mp4").write_bytes(b"test fixture")
            (root / "thanks.mp4").write_bytes(b"test fixture")
            manifest_path = root / "clips.csv"
            with manifest_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "video_path", "phrase", "source", "license", "rights_confirmed", "signer_id",
                    "input_mirrored", "start_seconds", "end_seconds"
                ])
                writer.writeheader()
                writer.writerow({"video_path": "hello.mp4", "phrase": "сәлем", "source": "AI-Ym", "license": "разрешение", "rights_confirmed": "yes", "signer_id": "A", "input_mirrored": "true", "start_seconds": "1.25", "end_seconds": "2.8"})
                writer.writerow({"video_path": "thanks.mp4", "phrase": "рахмет", "source": "AI-Ym", "license": "разрешение", "rights_confirmed": "no", "signer_id": "B", "input_mirrored": "false", "start_seconds": "3", "end_seconds": "2"})
            rows, errors = read_manifest(manifest_path)
            imported_calls = []

            def fake_importer(label, path, **kwargs):
                imported_calls.append((label, Path(path).name, kwargs))
                return len(imported_calls)

            progress_events = []
            successes, failures = import_manifest(
                rows,
                importer=fake_importer,
                progress=lambda completed, total, row: progress_events.append(
                    (completed, total, row.phrase)
                ),
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("rights_confirmed", errors[0])
        self.assertIn("end_seconds", errors[0], "reversed gloss time ranges must not be accepted")
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 0)
        self.assertEqual(imported_calls[0][0:2], ("сәлем", "hello.mp4"))
        self.assertEqual(imported_calls[0][2]["signer_id"], "A")
        self.assertTrue(imported_calls[0][2]["input_mirrored"])
        self.assertTrue(rows[0].rights_confirmed)
        self.assertNotIn("rights_confirmed", imported_calls[0][2],
                         "custom importer callback signature stays backward compatible")
        self.assertEqual(imported_calls[0][2]["start_seconds"], 1.25)
        self.assertEqual(imported_calls[0][2]["end_seconds"], 2.8)
        self.assertEqual(progress_events, [(1, 1, "сәлем")])

    def test_manifest_import_registers_curated_alias_on_motion_gesture(self):
        row = ManifestRow(
            line=2,
            video_path=Path("hello.mp4"),
            phrase="сәлем",
            source="local",
            license_name="permission",
            signer_id=None,
            language="kk-KZ",
            aliases=("Сәлеметсіз бе",),
        )
        with patch("src.motion_db.register_gesture", return_value=17) as register, patch(
            "src.motion_db.register_gesture_aliases"
        ) as register_aliases:
            imported, failures = import_manifest([row], importer=lambda *_args, **_kwargs: 4)
        register.assert_called_once_with(
            "сәлем", "сәлем", language="kk-KZ", source="local", license_name="permission"
        )
        register_aliases.assert_called_once_with(
            17, ["Сәлеметсіз бе"], language="kk-KZ"
        )
        self.assertEqual(imported, [(row, 4)])
        self.assertEqual(failures, [])

    def test_manifest_forwards_rights_confirmation_to_default_motion_importer(self):
        from src.motion_db import import_video_motion

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"authorized local clip")
            manifest = (
                "video_path,phrase,source,license,rights_confirmed,language\n"
                "clip.mp4,сәлем,local,owner-confirmed,yes,kk-KZ\n"
            )
            rows, errors = read_manifest_text(manifest, base_dir=root)
            self.assertEqual(errors, [])
            with patch("src.motion_db.import_video_motion", return_value=23) as importer:
                imported, failures = import_manifest(
                    rows, db_path=root / "motion.sqlite3"
                )

        self.assertEqual(failures, [])
        self.assertEqual(imported, [(rows[0], 23)])
        self.assertIs(importer.call_args.kwargs["rights_confirmed"], True)
        self.assertTrue(importer.call_args.kwargs["extraction_cache"] is not None)

    def test_manifest_translation_alias_routes_other_language_to_same_kazakh_motion(self):
        from src.motion_db import compose_phrase_segments, register_gesture, add_motion_clip

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            row = ManifestRow(
                line=2, video_path=Path("source.mp4"), phrase="сәлем",
                source="dataset", license_name="CC BY 4.0", signer_id="signer-7",
                language="kk-KZ", translations=(("ru-RU", "привет"),),
            )

            def importer(label, _video, **options):
                gesture_id = register_gesture(
                    label, options["phrase"], language=options["language"],
                    db_path=db_path,
                )
                return add_motion_clip(
                    gesture_id, np.full((4, 162), .3, dtype=np.float32),
                    source_video="source.mp4", db_path=db_path,
                )

            imported, failures = import_manifest([row], importer=importer, db_path=db_path)
            segments, found, missing = compose_phrase_segments(
                "Привет!", language="ru-RU", db_path=db_path
            )

        self.assertEqual(len(imported), 1)
        self.assertEqual(failures, [])
        self.assertEqual(found, ["привет"])
        self.assertEqual(missing, [])
        self.assertEqual(segments[0]["type"], "motion")
        self.assertEqual(segments[0]["label"], "привет")

    def test_available_avatar_search_terms_include_cross_language_aliases_only_for_usable_motion(self):
        from src.motion_db import available_search_terms, register_gesture_alias

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            gesture_id = register_gesture("сәлем", "сәлем", db_path=db_path)
            add_motion_clip(
                gesture_id, np.ones((3, 162), dtype=np.float32),
                metadata={"training_eligible": True}, db_path=db_path,
            )
            register_gesture_alias(gesture_id, "привет", language="ru-RU", db_path=db_path)
            unavailable_id = register_gesture("рахмет", "рахмет", db_path=db_path)
            add_motion_clip(
                unavailable_id, np.ones((3, 162), dtype=np.float32),
                metadata={"training_eligible": False}, db_path=db_path,
            )

            kk_terms = available_search_terms("kk-KZ", db_path=db_path)
            ru_terms = available_search_terms("ru-RU", db_path=db_path)

        self.assertEqual(kk_terms, ["сәлем"])
        self.assertEqual(ru_terms, ["привет"])

    def test_manifest_parses_explicit_cross_language_translation_aliases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "hello.mp4"
            video.write_bytes(b"video")
            manifest_path = root / "manifest.csv"
            manifest_path.write_text(
                "video_path,phrase,aliases,translations,source,license,rights_confirmed,language\n"
                "hello.mp4,сәлем,,ru-RU=привет|ru-RU=здравствуйте,dataset,CC-BY-4.0,yes,kk-KZ\n",
                encoding="utf-8",
            )
            rows, errors = read_manifest(manifest_path)

        self.assertEqual(errors, [])
        self.assertEqual(rows[0].translations, (("ru-RU", "привет"), ("ru-RU", "здравствуйте")))

    def test_manifest_alias_conflict_is_rejected_before_video_extraction(self):
        from src.ingest_manifest import import_manifest

        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "motion.sqlite3"
            register_gesture("сәлем", "сәлем", db_path=database)
            register_gesture("рахмет", "рахмет", db_path=database)
            row = ManifestRow(
                line=2, video_path=Path("unread-video.mp4"), phrase="сәлем",
                source="local", license_name="permission", signer_id=None,
                language="kk-KZ", aliases=("рахмет",),
            )
            called = []
            imported, failures = import_manifest(
                [row], importer=lambda *args, **kwargs: called.append((args, kwargs)),
                db_path=database,
            )
        self.assertEqual(imported, [])
        self.assertEqual(len(failures), 1)
        self.assertIn("другому жесту", failures[0][1])
        self.assertEqual(called, [], "conflicting alias is rejected before expensive video processing")

    def test_manifest_phrase_normalization_conflict_is_rejected_before_import(self):
        from src.ingest_manifest import import_manifest

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            register_gesture("greeting", "Сәлем, досым!", db_path=db_path)
            row = ManifestRow(
                line=2, video_path=Path(temp_dir) / "new.mp4", phrase="сәлем досым",
                source="local", license_name="permission", signer_id=None,
                language="kk-KZ",
            )
            called = []
            imported, failures = import_manifest(
                [row], importer=lambda *_args, **_kwargs: called.append(True) or 1,
                db_path=db_path,
            )

        self.assertEqual(imported, [])
        self.assertEqual(called, [])
        self.assertEqual(len(failures), 1)
        self.assertIn("разными леммами", failures[0][1])

    def test_large_manifest_can_be_split_into_deterministic_resumable_batches(self):
        rows = [
            ManifestRow(i + 2, Path(f"{i}.mp4"), f"phrase-{i}", "local", "permission", None, "kk-KZ")
            for i in range(5)
        ]
        self.assertEqual(
            [row.phrase for row in select_manifest_batch(rows, offset=1, limit=2)],
            ["phrase-1", "phrase-2"],
        )
        self.assertEqual(
            [row.phrase for row in select_manifest_batch(rows, offset=3)],
            ["phrase-3", "phrase-4"],
        )
        self.assertEqual(select_manifest_batch(rows, offset=5), [])
        with self.assertRaisesRegex(ValueError, "offset"):
            select_manifest_batch(rows, offset=-1)
        with self.assertRaisesRegex(ValueError, "limit"):
            select_manifest_batch(rows, limit=0)

    def test_uploaded_manifest_text_resolves_paths_from_project_video_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            videos = root / "videos"
            videos.mkdir()
            (videos / "hello.mp4").write_bytes(b"fixture")
            (root / "outside.mp4").write_bytes(b"outside project")
            manifest = (
                "video_path,phrase,aliases,source,license,rights_confirmed,signer_id,language\n"
                "hello.mp4,сәлем,Сәлеметсіз бе; Салем,AI-Ym,written permission,yes,signer-1,kk-KZ\n"
                "missing.mp4,рахмет,,AI-Ym,permission,no,,kk-KZ\n"
                "../outside.mp4,hello,,local,permission,yes,,kk-KZ\n"
            )
            rows, errors = read_manifest_text(manifest, base_dir=videos)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].video_path.name, "hello.mp4")
        self.assertEqual(rows[0].phrase, "сәлем")
        self.assertEqual(rows[0].signer_id, "signer-1")
        self.assertEqual(rows[0].aliases, ("Сәлеметсіз бе", "Салем"))
        self.assertEqual(len(errors), 2)
        self.assertIn("rights_confirmed", errors[0])
        self.assertIn("файл не найден", errors[0])
        self.assertIn("выходит за папку проекта", errors[1])

    def test_batch_video_upload_rejects_path_traversal_and_never_overwrites(self):
        class Uploaded:
            def __init__(self, name, data):
                self.name = name
                self.data = data

            def getvalue(self):
                return self.data

        class BrokenUpload:
            name = "broken.mp4"

            def getvalue(self):
                raise OSError("simulated read error")

        with tempfile.TemporaryDirectory() as temp_dir:
            videos = Path(temp_dir) / "videos"
            videos.mkdir()
            (videos / "existing.mp4").write_bytes(b"keep this original")
            uploads = [
                Uploaded("new.mp4", b"valid video bytes"),
                Uploaded("existing.mp4", b"keep this original"),
                Uploaded("existing.mp4", b"different bytes"),
                Uploaded("../outside.mp4", b"must not escape"),
                Uploaded("notes.txt", b"not a video"),
                BrokenUpload(),
            ]
            saved, errors = save_uploaded_videos(uploads, videos)
            self.assertEqual([path.name for path in saved], ["new.mp4", "existing.mp4"])
            self.assertEqual((videos / "existing.mp4").read_bytes(), b"keep this original")
            self.assertFalse((Path(temp_dir) / "outside.mp4").exists())
        self.assertEqual(len(errors), 4)
        self.assertTrue(any("не перезаписан" in error for error in errors))
        self.assertTrue(any("Недопустимое имя" in error for error in errors))
        self.assertTrue(any("Не удалось сохранить broken.mp4" in error for error in errors))

    def test_phrase_segments_preserve_word_order_and_clip_fps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "motion.sqlite3"
            for word, fps, marker in (("бір", 24.0, 1.0), ("екі", 60.0, 2.0)):
                gesture_id = register_gesture(word, word, db_path=db_path)
                sequence = np.full((4, 162), marker, dtype=np.float32)
                add_motion_clip(gesture_id, sequence, fps=fps, db_path=db_path)
            segments, found, missing = compose_phrase_segments(
                "бір белгісіз екі", db_path=db_path
            )
        self.assertEqual([item["type"] for item in segments], ["motion", "missing", "motion"])
        self.assertEqual([item["label"] for item in segments], ["бір", "белгісіз", "екі"])
        self.assertEqual([item["fps"] for item in segments if item["type"] == "motion"], [24.0, 60.0])
        self.assertEqual(found, ["бір", "екі"])
        self.assertEqual(missing, ["белгісіз"])

    def test_stratified_split_keeps_each_class_in_both_sets(self):
        labels = np.array([0] * 5 + [1] * 3)
        train, validation = stratified_split_indices(labels, 0.25)
        self.assertFalse(set(train) & set(validation))
        self.assertEqual(set(labels[train]), {0, 1})
        self.assertEqual(set(labels[validation]), {0, 1})

    def test_stratified_split_rejects_single_example_class(self):
        with self.assertRaises(ValueError):
            stratified_split_indices(np.array([0, 1, 1]), 0.2)

    def test_project_video_sequences_prepare_to_model_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "greeting"
            project_path.mkdir()
            samples = np.zeros((3, 30, 162), dtype=np.float32)
            samples[:, :, 0] = np.arange(30, dtype=np.float32)
            np.save(project_path / "landmarks_raw.npy", samples)
            (project_path / "landmarks_meta.json").write_text(json.dumps({
                "format": "raw_frame_landmarks",
                "data_file": "landmarks_raw.npy",
                "source_videos": [],
            }), encoding="utf-8")
            projects = {
                "greeting": {
                    "name_kz": "сәлем",
                    "path": project_path,
                    "landmarks_path": project_path / "landmarks_raw.npy",
                    "has_landmarks": True,
                }
            }
            sequences, counts = collect_training_sequences(
                projects, include_motion_library=False
            )
            X, y, labels = prepare_training_data(sequences)
        self.assertEqual(counts, {"сәлем": 3})
        self.assertEqual(X.shape, (3, 30, 162))
        self.assertEqual(y.tolist(), [0, 0, 0])
        self.assertEqual(labels, {"сәлем": 0})

    def test_legacy_project_arrays_are_skipped_but_raw_database_clip_is_kept(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "greeting"
            videos_path = project_path / "videos"
            videos_path.mkdir(parents=True)
            video_path = videos_path / "hello.mp4"
            video_path.write_bytes(b"test")
            np.save(project_path / "landmarks.npy", np.zeros((1, 30, 162), dtype=np.float32))
            raw_clip = np.zeros((8, 162), dtype=np.float32)
            raw_clip[:, 0] = 0.4
            raw_clip[:, 3] = 0.45
            raw_clip[:, 6] = 0.5
            projects = {"hello": {
                "name_kz": "сәлем", "path": project_path, "has_landmarks": True,
            }}
            clip = {
                "lemma": "сәлем", "source_video": str(video_path),
                "sequence": raw_clip, "metadata": {},
            }
            with patch("src.training_data.load_motion_library", return_value=[clip, clip]):
                sequences, counts = collect_training_sequences(projects)
        self.assertEqual(counts, {"сәлем": 1})
        self.assertEqual(sequences["сәлем"][0].shape, (8, 162))

    def test_raw_project_video_is_not_counted_twice_from_motion_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "greeting"
            video_path = project_path / "videos" / "hello.mp4"
            video_path.parent.mkdir(parents=True)
            video_path.write_bytes(b"test")
            sample = np.zeros((12, 162), dtype=np.float32)
            sample[:, 0] = 0.4
            sample[:, 3] = 0.45
            sample[:, 6] = 0.5
            raw = np.empty(1, dtype=object)
            raw[0] = sample
            np.save(project_path / "landmarks_raw.npy", raw, allow_pickle=True)
            (project_path / "landmarks_meta.json").write_text(json.dumps({
                "format": "raw_frame_landmarks",
                "data_file": "landmarks_raw.npy",
                "source_videos": ["videos/hello.mp4"],
            }), encoding="utf-8")
            projects = {"hello": {
                "name_kz": "сәлем", "path": project_path,
                "has_landmarks": True,
                "landmarks_path": project_path / "landmarks_raw.npy",
            }}
            clip = {
                "lemma": "сәлем", "source_video": str(video_path),
                "sequence": sample, "metadata": {},
            }
            with patch("src.training_data.load_motion_library", return_value=[clip, clip]):
                sequences, counts = collect_training_sequences(projects)
        self.assertEqual(counts, {"сәлем": 1})
        self.assertEqual(sequences["сәлем"][0].shape, (12, 162))

    def test_training_deduplicates_exact_intervals_but_keeps_other_glosses_from_same_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "project"
            video_path = project_path / "videos" / "sentence.mp4"
            video_path.parent.mkdir(parents=True)
            video_path.write_bytes(b"fixture")

            def motion(marker):
                sequence = np.zeros((12, 162), dtype=np.float32)
                sequence[:, 0] = .35 + marker
                sequence[:, 3] = .40 + marker
                sequence[:, 6] = .45 + marker
                return sequence

            project_sequence = motion(0.0)
            raw = np.empty(1, dtype=object)
            raw[0] = project_sequence
            np.save(project_path / "landmarks_raw.npy", raw, allow_pickle=True)
            (project_path / "landmarks_meta.json").write_text(json.dumps({
                "format": "raw_frame_landmarks", "data_file": "landmarks_raw.npy",
                "source_videos": ["videos/sentence.mp4"],
            }), encoding="utf-8")
            def clip(lemma, sequence, start, end):
                return {
                    "lemma": lemma, "source_video": str(video_path),
                    "start_frame": start, "end_frame": end,
                    "sequence": sequence, "metadata": {},
                }
            library = [
                clip("сәлем", project_sequence.copy(), 0, 12),  # exact project duplicate
                clip("сәлем", motion(.1), 12, 24),             # different segment, same source
                clip("сәлем", motion(.1), 12, 24),             # duplicate interval
                clip("рахмет", motion(.2), 12, 24),            # distinct annotated class
            ]
            projects = {"greeting": {
                "name_kz": "сәлем", "path": project_path, "has_landmarks": True,
            }}
            with patch("src.training_data.load_motion_library", return_value=library):
                sequences, counts, groups = collect_training_sequences(projects, include_groups=True)

        self.assertEqual(counts, {"рахмет": 1, "сәлем": 2})
        self.assertEqual(len(set(groups["сәлем"])), 1,
                         "segments from a shared source remain grouped to prevent validation leakage")
        self.assertEqual(len(sequences["сәлем"]), 2)

    def test_relative_motion_source_is_deduplicated_independent_of_working_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_path = root / "project"
            video_path = project_path / "videos" / "hello.mp4"
            video_path.parent.mkdir(parents=True)
            video_path.write_bytes(b"video")
            other_cwd = root / "elsewhere"
            other_cwd.mkdir()
            sample = np.zeros((12, 162), dtype=np.float32)
            sample[:, 0] = 0.4
            sample[:, 3] = 0.45
            sample[:, 6] = 0.5
            raw = np.empty(1, dtype=object)
            raw[0] = sample
            np.save(project_path / "landmarks_raw.npy", raw, allow_pickle=True)
            (project_path / "landmarks_meta.json").write_text(json.dumps({
                "format": "raw_frame_landmarks",
                "data_file": "landmarks_raw.npy",
                "source_videos": ["videos/hello.mp4"],
            }), encoding="utf-8")
            projects = {"hello": {
                "name_kz": "сәлем", "path": project_path,
                "landmarks_path": project_path / "landmarks_raw.npy",
                "has_landmarks": True,
            }}
            clip = {
                "lemma": "сәлем", "source_video": "project/videos/hello.mp4",
                "sequence": sample, "metadata": {},
            }
            previous_cwd = Path.cwd()
            try:
                os.chdir(other_cwd)
                with patch("src.training_data.config.BASE_DIR", root), \
                     patch("src.training_data.load_motion_library", return_value=[clip]):
                    sequences, counts = collect_training_sequences(projects)
            finally:
                os.chdir(previous_cwd)
        self.assertEqual(counts, {"сәлем": 1})
        self.assertEqual(len(sequences["сәлем"]), 1)

    def test_matcher_self_matches_real_sequence(self):
        sequence = np.zeros((30, 162), dtype=np.float32)
        for offset in (0, 63):
            for point in range(21):
                sequence[:, offset + point * 3] = 0.30 + (point % 5) * 0.02
                sequence[:, offset + point * 3 + 1] = 0.40 + (point // 5) * 0.03
        matcher = MotionLibraryMatcher([{
            "clip_id": 17,
            "lemma": "test",
            "phrase": "test",
            "sequence": sequence,
        }])
        result = matcher.match(sequence)
        self.assertIsNotNone(result)
        self.assertEqual(result["clip_id"], 17)
        self.assertEqual(result["distance"], 0.0)
        self.assertFalse(result["is_classifiable"])
        self.assertFalse(result["is_trained_classifier"])

    def test_motion_matcher_handles_tempo_variation_without_ignoring_gesture_order(self):
        from src.motion_matcher import MotionLibraryMatcher

        reference = np.zeros((12, 162), dtype=np.float32)
        trajectory = np.array([0, 0, 0, 1, 1, 1, .2, .2, .2, .7, .7, .7], dtype=np.float32)
        for offset in (0, 63):
            for point in range(21):
                reference[:, offset + point * 3] = .25 + trajectory * .2 + (point % 5) * .01
                reference[:, offset + point * 3 + 1] = .35 + (point // 5) * .025

        # Repeated holds model the same sign articulated more slowly.
        slow = np.repeat(reference[[0, 2, 4, 6, 8, 10, 11]], [2, 2, 2, 2, 2, 2, 2], axis=0)
        reversed_motion = reference[::-1].copy()
        tempo_distance = MotionLibraryMatcher._temporal_distance(reference, slow)
        ordered_distance = MotionLibraryMatcher._temporal_distance(reference, reversed_motion)
        self.assertLess(tempo_distance, 0.025)
        self.assertGreater(ordered_distance, tempo_distance + 0.02)

    def test_low_hand_coverage_motion_is_not_used_as_training_or_matching_example(self):
        sequence = np.zeros((30, 162), dtype=np.float32)
        for offset in (0, 63):
            for point in range(21):
                sequence[:, offset + point * 3] = 0.30 + (point % 5) * 0.02
                sequence[:, offset + point * 3 + 1] = 0.40 + (point // 5) * 0.03
        weak_clip = {
            "clip_id": 1, "lemma": "weak", "sequence": sequence,
            "metadata": {"hand_detection_coverage": 0.2},
        }
        strong_clip = {
            "clip_id": 2, "lemma": "strong", "sequence": sequence,
            "metadata": {"hand_detection_coverage": 0.9},
        }
        matcher = MotionLibraryMatcher([weak_clip, strong_clip])
        self.assertEqual([item["clip_id"] for item in matcher.references], [2])
        with patch("src.training_data.load_motion_library", return_value=[weak_clip, strong_clip]):
            sequences, counts = collect_training_sequences({})
        self.assertEqual(counts, {"strong": 1})

    def test_low_hand_coverage_raw_project_sequence_is_excluded_from_training(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "project"
            project_path.mkdir()
            sequence = np.zeros((10, 162), dtype=np.float32)
            sequence[:2, 0] = 0.4
            sequence[:2, 3] = 0.5
            sequence[:2, 6] = 0.6
            raw = np.empty(1, dtype=object)
            raw[0] = sequence
            np.save(project_path / "landmarks_raw.npy", raw, allow_pickle=True)
            (project_path / "landmarks_meta.json").write_text(json.dumps({
                "format": "raw_frame_landmarks",
                "data_file": "landmarks_raw.npy",
                "source_videos": [],
            }), encoding="utf-8")
            projects = {"weak": {
                "name_kz": "әлсіз", "path": project_path,
                "landmarks_path": project_path / "landmarks_raw.npy",
                "has_landmarks": True,
            }}
            with patch("src.training_data.load_motion_library", return_value=[]):
                sequences, counts = collect_training_sequences(projects)
        self.assertEqual(sequences, {})
        self.assertEqual(counts, {})

    def test_project_signer_metadata_groups_multiple_videos_from_same_person(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "project"
            project_path.mkdir()
            sequences = []
            for marker in (0.4, 0.42):
                sample = np.zeros((8, 162), dtype=np.float32)
                for offset in (0, 63):
                    for point in range(21):
                        sample[:, offset + point * 3] = marker + (point % 5) * 0.02
                        sample[:, offset + point * 3 + 1] = 0.4 + (point // 5) * 0.03
                sequences.append(sample)
            raw = np.empty(2, dtype=object)
            raw[:] = sequences
            np.save(project_path / "landmarks_raw.npy", raw, allow_pickle=True)
            (project_path / "landmarks_meta.json").write_text(json.dumps({
                "format": "raw_frame_landmarks",
                "data_file": "landmarks_raw.npy",
                "source_videos": ["videos/one.mp4", "videos/two.mp4"],
                "signer_ids": {"one.mp4": "signer-a", "two.mp4": "signer-a"},
            }), encoding="utf-8")
            projects = {"greeting": {
                "name_kz": "сәлем", "path": project_path,
                "has_landmarks": True,
            }}
            with patch("src.training_data.load_motion_library", return_value=[]):
                grouped = collect_training_sequences(projects, include_groups=True)
        examples, counts, groups = grouped
        self.assertEqual(counts, {"сәлем": 2})
        self.assertEqual(groups["сәлем"], ["signer:signer-a", "signer:signer-a"])

    def test_matcher_ignores_duplicate_examples_when_reporting_runner_up_class(self):
        sequence = np.zeros((30, 162), dtype=np.float32)
        for offset in (0, 63):
            for point in range(21):
                sequence[:, offset + point * 3] = 0.30 + (point % 5) * 0.02
                sequence[:, offset + point * 3 + 1] = 0.40 + (point // 5) * 0.03
        clips = [
            {"clip_id": idx, "lemma": "сәлем", "phrase": "сәлем", "sequence": sequence.copy()}
            for idx in (1, 2)
        ]
        matcher = MotionLibraryMatcher(clips)
        result = matcher.match(sequence)
        self.assertIsNone(result["runner_up_distance"])

        distinct_phrase = {
            "clip_id": 3, "lemma": "test", "phrase": "another meaning",
            "sequence": sequence + np.float32(0.1),
        }
        matcher = MotionLibraryMatcher([clips[0], distinct_phrase])
        result = matcher.match(sequence)
        self.assertIsNotNone(result["runner_up_distance"])
        self.assertTrue(result["is_classifiable"])

    def test_matcher_deduplicates_same_source_but_keeps_distinct_video_examples(self):
        sequence = np.zeros((30, 162), dtype=np.float32)
        for offset in (0, 63):
            for point in range(21):
                sequence[:, offset + point * 3] = 0.30 + (point % 5) * 0.02
                sequence[:, offset + point * 3 + 1] = 0.40 + (point // 5) * 0.03
        clips = [
            {"clip_id": 1, "lemma": "hello", "phrase": "hello", "source_video": "data/source.mp4", "sequence": sequence},
            {"clip_id": 2, "lemma": "hello", "phrase": "hello", "source_video": str(Path(config.BASE_DIR) / "data" / "source.mp4"), "sequence": sequence},
            {"clip_id": 3, "lemma": "hello", "phrase": "hello", "source_video": "data/another.mp4", "sequence": sequence},
        ]
        matcher = MotionLibraryMatcher(clips)
        self.assertEqual([item["clip_id"] for item in matcher.references], [1, 3])

    def test_matcher_does_not_reward_missing_hand_landmarks_as_zero_error(self):
        sequence = np.zeros((30, 162), dtype=np.float32)
        for offset in (0, 63):
            for point in range(21):
                sequence[:, offset + point * 3] = 0.30 + (point % 5) * 0.02
                sequence[:, offset + point * 3 + 1] = 0.40 + (point // 5) * 0.03
        matcher = MotionLibraryMatcher([{
            "clip_id": 1, "lemma": "test", "sequence": sequence,
        }])
        complete = matcher.match(sequence)["distance"]
        missing_right = sequence.copy()
        missing_right[:, 63:126] = 0.0
        incomplete = matcher.match(missing_right)["distance"]
        self.assertEqual(complete, 0.0)
        self.assertGreater(incomplete, complete)

    def test_motion_matcher_rejects_windows_with_too_few_observed_hand_frames(self):
        sequence = np.zeros((30, 162), dtype=np.float32)
        for point in range(21):
            sequence[:, point * 3] = 0.30 + (point % 5) * 0.02
            sequence[:, point * 3 + 1] = 0.40 + (point // 5) * 0.03
        matcher = MotionLibraryMatcher([{
            "clip_id": 1, "lemma": "сәлем", "sequence": sequence,
        }])
        mostly_missing = sequence.copy()
        mostly_missing[3:] = 0
        self.assertIsNone(matcher.match(mostly_missing))


    def test_grouped_validation_split_never_leaks_an_executor_between_sets(self):
        labels = np.asarray([0, 0, 1, 1, 0, 1])
        groups = np.asarray(["signer-a", "signer-b", "signer-a", "signer-b", "signer-c", "signer-c"])
        train_indices, validation_indices = grouped_split_indices(labels, groups, 0.25, seed=7)
        self.assertFalse(set(groups[train_indices]) & set(groups[validation_indices]))
        self.assertEqual(set(labels[train_indices]), {0, 1})
        self.assertEqual(set(labels[validation_indices]), {0, 1})

    def test_grouped_validation_refuses_classes_with_only_one_group(self):
        with self.assertRaisesRegex(ValueError, "минимум 2 исполнителя/источника"):
            grouped_split_indices(
                np.asarray([0, 0, 1, 1]),
                np.asarray(["a", "a", "a", "b"]),
                0.25,
            )


if __name__ == "__main__":
    unittest.main()
