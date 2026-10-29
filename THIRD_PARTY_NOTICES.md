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
coordinates in the image-space track are not metric depth. This project uses
normalized image X/Y plus shoulder-relative world-landmark Z for visual arm
animation. Coordinates are scaled to the avatar and are not bodily measurements.
# 3D avatar models

`web/models/quaternius-animated-human.glb` is Quaternius' **Animated Human**
(low-poly), converted to GLB by the `rana-jatin/avatar-stage` project. The model
is released under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
Original asset: https://opengameart.org/content/animated-human-low-poly
Source conversion and model-specific notes:
https://github.com/rana-jatin/avatar-stage/blob/main/demo/public/models/MODEL_LICENSE.md

The avatar-stage software itself is MIT-licensed, but DosYm does not bundle or
depend on that software. This is a legacy fallback candidate; the active human
avatar is documented below.

## DosYm PWA assets and processing tools

`pwa/public/fonts/NotoSans.ttf` is the complete Noto Sans Variable source font,
distributed under SIL Open Font License 1.1. The PWA interface uses the device's
system sans-serif stack and does not request this font. Its complete license is
beside the source font in `pwa/public/fonts/OFL.txt`.

The PWA uses Three.js 0.160.0, MIT; its upstream license is copied into the
generated, Git-ignored avatar vendor folder from the installed npm package.

`imageio-ffmpeg` 0.6.0 is a BSD-2-Clause Python wrapper. Its Windows wheel used
for local private video previews contains FFmpeg 7.1 Essentials from Gyan.dev,
configured with GPL and version-3 components (including libx264/libx265).
This FFmpeg executable is installed into the ignored virtual environment by
pip; it is not checked into the repository or served to PWA users. The server
operator must review the chosen FFmpeg distribution/configuration and its
redistribution obligations before packaging it with a public deployment.
Sources: https://github.com/imageio/imageio-ffmpeg and
https://www.gyan.dev/ffmpeg/builds/ .

`web/models/rocketbox-male-adult-01.glb` is a browser-ready conversion of
Microsoft Rocketbox's `Male_Adult_01.fbx`. The source avatar library is licensed
under MIT; the converted file retains the humanoid skeleton and articulated
finger bones. Color and normal maps were resized and compressed for local web
delivery. See [web/models/ROCKETBOX_LICENSE.md](web/models/ROCKETBOX_LICENSE.md).
The FBX2glTF converter used during preparation is BSD-3-Clause licensed; its
license applies to the converter, not to the avatar model.

`web/models/rocketbox-male-adult-02.glb` is a browser-ready conversion of
Microsoft Rocketbox's `Male_Adult_02.fbx` from `Assets/Avatars/Adults/Male_Adult_02/`.
It uses the same MIT library license. Color and normal maps were resized and
JPEG-compressed for local web delivery; the original rig and finger bones remain.

## Animation methods and test runtime

The recorded-motion stabilizer is an original bidirectional adaptation of the
One Euro filter described by Géry Casiez, Nicolas Roussel and Daniel Vogel,
CHI 2012: https://gery.casiez.net/1euro/ . No third-party filter implementation
is bundled. Its output is used for presentation only.

Three.js 0.160.0 (MIT) is used by the web renderer and as a development dependency
for numerical tests against the Rocketbox skeleton: https://github.com/mrdoob/three.js .
The npm package contains the upstream license. Kalidokit and external IK libraries
are not bundled; the arm solver and rig-specific finger calibration are local code.
