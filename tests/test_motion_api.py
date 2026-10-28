import json
from pathlib import Path
import threading
import unittest
import numpy as np
from http.server import ThreadingHTTPServer
from unittest.mock import call, patch
from urllib.parse import urlencode
from urllib.request import urlopen

from src.motion_api import _MotionHandler


class MotionApiLanguageTests(unittest.TestCase):
    def test_preparation_module_is_served_as_javascript_without_template_replacement(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MotionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/rig-motion.mjs", timeout=3) as response:
                self.assertEqual(response.headers.get_content_type(), "text/javascript")
                self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "*")
                self.assertEqual(response.read(), (Path(__file__).resolve().parents[1] / "web/rig-motion.mjs").read_bytes())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_rocketbox_glb_is_served_from_the_local_model_route(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MotionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for name in ("rocketbox-male-adult-01.glb", "rocketbox-male-adult-02.glb"):
                model_path = Path(__file__).resolve().parents[1] / "web" / "models" / name
                expected = model_path.read_bytes()
                url = f"http://127.0.0.1:{server.server_port}/models/{name}"
                with urlopen(url, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get_content_type(), "model/gltf-binary")
                    self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "*")
                    self.assertEqual(response.read(), expected)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_compose_endpoint_passes_selected_language_to_database_lookup(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MotionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch(
                "src.motion_db.compose_phrase_segments",
                return_value=([], [], ["привет"]),
            ) as compose:
                url = f"http://127.0.0.1:{server.server_port}/api/compose?{urlencode({'text': 'Привет', 'language': 'ru-RU'})}"
                with urlopen(url, timeout=3) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                avatar_url = f"http://127.0.0.1:{server.server_port}/avatar?{urlencode({'text': 'Привет', 'language': 'ru-RU'})}"
                with urlopen(avatar_url, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("DosYm Motion Avatar", response.read().decode("utf-8"))

            self.assertEqual(compose.call_args_list, [
                call("Привет", language="ru-RU"),
                call("Привет", language="ru-RU"),
            ])
            self.assertEqual(payload["language"], "ru-RU")
            self.assertEqual(payload["missing"], ["привет"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_source_aspect_ratio_survives_database_api_and_avatar_rendering(self):
        segment = {
            "type": "motion", "label": "сәлем", "sequence": np.zeros((2, 162)),
            "fps": 24.0, "metadata": {"image_aspect_ratio": 16 / 9},
        }
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MotionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch(
                "src.motion_db.compose_phrase_segments",
                return_value=([segment], ["сәлем"], []),
            ):
                url = f"http://127.0.0.1:{server.server_port}/api/compose?{urlencode({'text': 'сәлем'})}"
                with urlopen(url, timeout=3) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                avatar_url = f"http://127.0.0.1:{server.server_port}/avatar?{urlencode({'text': 'сәлем'})}"
                with urlopen(avatar_url, timeout=3) as response:
                    avatar = response.read().decode("utf-8")
            self.assertAlmostEqual(payload["segments"][0]["image_aspect_ratio"], 16 / 9)
            self.assertIn(
                "let activeImageAspectRatio=normalizeImageAspectRatio(1.7777777777777777);",
                avatar,
            )
            self.assertNotIn("/*IMAGE_ASPECT_RATIO__*/", avatar)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
