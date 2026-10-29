# PWA camera matching implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement the approved scope below.

**Goal:** A local camera preview with up to three plausible library labels below it.

**Architecture:** Lazy camera screen; MediaPipe HandLandmarker and temporal example matching in a dedicated module worker. Only public reference coordinates are downloaded. Camera ImageBitmaps stay on the device. No trained classifier, no facial-expression interpretation, no confidence percentages or automatic sentence translation.

**Tech stack:** Existing Next.js/React, pinned @mediapipe/tasks-vision, Web Worker, getUserMedia.

**Spec:** User approved the experimental nearest-example approach in this conversation.

## Constraints and failure modes

- Explicit Start/Stop; no audio. Stop tracks and worker on hide, navigation, errors and cancellation.
- At most one frame in flight, at most 10 captures/sec, match at most twice/sec.
- Missing hands clear stale results; insufficient/weak matches show no guess.
- Preserve unmirrored anatomical handedness and relative two-hand geometry.
- Model/library load errors, permission denial and unsupported browser remain actionable.
- No MediaPipe/model/reference downloads until the camera feature is started.
- Existing text, speech, dictionary and avatar continue to work.

## Tasks

- [x] Pure matching module + tests: normalization, resampling, temporal distance, class deduplication, missing hands, rejection, immutable references.
- [x] Pinned generated runtime/model assets + worker; model integrity and reproducible build.
- [x] Lazy `/camera` screen: preview, model/reference preparation, top-three labels, permission errors, lifecycle cleanup, three locales and responsive controls.
- [x] Tests: fake camera/worker lifecycle and results, genuine MediaPipe execution with a synthetic local video, existing regressions and production build.
- [ ] Documentation/map, explicit limitations, commit/push/deploy and live smoke test without opening the user's camera.

## Validation notes (30 October)

- Six camera browser checks pass, including real WASM on a blank frame and mobile layout; optional recorded-video check was run separately.
- Genuine authorized local recording of «Ө» produces the expected label among candidates. A word recording («Кітапхана») yields no match under the current visibility/window gates; this is an explicit limitation, not a quality claim for all vocabulary.
- Recording test waits for actual composed video frames; seeking a detached paused video previously returned stale frames. Production uses continuously playing camera video.
- Existing locale/speech/playback checks pass in their normal backend configuration. Those mocks are not designed for the public-snapshot URLs used by the isolated camera test server.
- Public compact camera.json has 115 approved references, 1,416,093 bytes; downloaded content verified against the export checksum. No camera footage was uploaded.
