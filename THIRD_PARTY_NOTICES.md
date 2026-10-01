# Third-party model notices

## MediaPipe Pose Landmarker Lite / BlazePose GHUM 3D

- Source: https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task
- Version: float16/1
- SHA-256: `59929E1D1EE95287735DDD833B19CF4AC46D29BC7AFDDBBF6753C459690D574A`
- Model card: https://storage.googleapis.com/mediapipe-assets/Model%20Card%20BlazePose%20GHUM%203D.pdf
- License: Apache License 2.0, as stated by the model card. See `LICENSE-APACHE-2.0.txt`.
- Authors named in the model card: Valentin Bazarevsky, Ivan Grishchenko, and Eduard Gabriel Bazavan (Google).

The model card describes this model as an approximate 33-point human pose estimator,
not a medically accurate or life-critical measurement system. Its estimated Z
coordinates are not metric depth. This project uses the normalized image landmarks
for visual arm animation only.
