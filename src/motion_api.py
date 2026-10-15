"""Локальный HTTP API для поиска и выдачи motion-клипов браузерному аватару."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class _MotionHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send(200, {"ok": True})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/models/rocketbox-male-adult-01.glb", "/models/rocketbox-male-adult-02.glb"):
            model_path = Path(__file__).resolve().parents[1] / "web" / "models" / parsed.path.rsplit("/", 1)[-1]
            try:
                body = model_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "model/gltf-binary")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError as error:
                self._send(404, {"error": str(error)})
            return
        if parsed.path == "/avatar":
            avatar_path = Path(__file__).resolve().parents[1] / "web" / "avatar.html"
            try:
                phrase = parse_qs(parsed.query).get("text", [""])[0].strip()
                language = parse_qs(parsed.query).get("language", ["kk-KZ"])[0].strip() or "kk-KZ"
                sequence: list[list[float]] = []
                fps = 30.0
                queue: list[dict] = []
                missing: list[str] = []
                if phrase:
                    from src.motion_db import compose_phrase_segments
                    segments, _found, missing = compose_phrase_segments(phrase, language=language)
                    queue = [
                        {**segment, "sequence": segment["sequence"].astype(float).tolist(),
                         "body_pose": segment.get("metadata", {}).get("body_pose_landmarks"),
                         "body_pose_world": segment.get("metadata", {}).get("body_pose_world_landmarks"),
                         "image_aspect_ratio": segment.get("metadata", {}).get("image_aspect_ratio"),
                         "body_pose_status": segment.get("metadata", {}).get("body_pose_status", "not_extracted"),
                         "language": language}
                        for segment in segments if segment["type"] == "motion"
                    ]
                    if queue:
                        sequence = queue[0]["sequence"]
                        fps = float(queue[0]["fps"])
                html = avatar_path.read_text(encoding="utf-8")
                html = html.replace(
                    "__MOTION_SEQUENCE__", json.dumps(sequence, ensure_ascii=False, separators=(",", ":"))
                )
                html = html.replace("__MOTION_LABEL__", json.dumps(phrase, ensure_ascii=False))
                html = html.replace("__MOTION_FPS__", str(fps))
                html = html.replace(
                    "/*IMAGE_ASPECT_RATIO__*/1",
                    json.dumps(queue[0].get("image_aspect_ratio") or 1 if queue else 1),
                )
                html = html.replace(
                    "/*MOTION_QUEUE__*/[]",
                    json.dumps(queue, ensure_ascii=False, separators=(",", ":")),
                )
                html = html.replace(
                    "/*MOTION_MISSING__*/[]",
                    json.dumps(missing, ensure_ascii=False, separators=(",", ":")),
                )
                html = html.replace(
                    "/*BODY_POSE__*/null",
                    json.dumps(queue[0].get("body_pose") if queue else None,
                               ensure_ascii=False, separators=(",", ":")),
                )
                html = html.replace(
                    "/*BODY_POSE_WORLD__*/null",
                    json.dumps(queue[0].get("body_pose_world") if queue else None,
                               ensure_ascii=False, separators=(",", ":")),
                )
                html = html.replace("/*MOTION_LANGUAGE__*/\"kk-KZ\"", json.dumps(language))
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError as error:
                self._send(500, {"error": str(error)})
            return
        if parsed.path != "/api/compose":
            self._send(404, {"error": "not_found"})
            return
        text = parse_qs(parsed.query).get("text", [""])[0]
        language = parse_qs(parsed.query).get("language", ["kk-KZ"])[0].strip() or "kk-KZ"
        try:
            from src.motion_db import compose_phrase_segments
            segments, found, missing = compose_phrase_segments(text, language=language)
            serializable_segments = [
                {**segment, "sequence": segment["sequence"].astype(float).tolist(),
                 "body_pose": segment.get("metadata", {}).get("body_pose_landmarks"),
                 "body_pose_world": segment.get("metadata", {}).get("body_pose_world_landmarks"),
                 "image_aspect_ratio": segment.get("metadata", {}).get("image_aspect_ratio"),
                 "body_pose_status": segment.get("metadata", {}).get("body_pose_status", "not_extracted"),
                 "language": language}
                if segment["type"] == "motion" else segment
                for segment in segments
            ]
            self._send(200, {
                "text": text,
                "language": language,
                "found": found,
                "missing": missing,
                "segments": serializable_segments,
            })
        except Exception as error:
            self._send(500, {"error": str(error)})

    def log_message(self, format: str, *args) -> None:
        return


_server: ThreadingHTTPServer | None = None
_server_thread: threading.Thread | None = None
_lock = threading.Lock()


def ensure_motion_api(host: str = "127.0.0.1", port: int = 8502) -> None:
    global _server, _server_thread
    with _lock:
        if _server is not None and _server_thread is not None and _server_thread.is_alive():
            return
        server = ThreadingHTTPServer((host, port), _MotionHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, name="dosym-motion-api", daemon=True)
        thread.start()
        _server = server
        _server_thread = thread

