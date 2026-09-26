# Local Site Vision demo media

Place the local demo clips in this directory using these exact names:

- `CCTV_1.mp4` — drilling-operations fixed-camera demo
- `CCTV_2.mp4` — pipe-laydown-yard fixed-camera demo
- `LiveCamera_1.mp4` — worker-uploaded site walk-through demo

VEDA serves these demo clips locally under `/static/staticcams/` and
does not upload them to an external AI service.

The `detections/` sidecars contain local object and pose detections sampled from
the videos. `vision-tracker.js` interpolates matching track IDs against the
player's current time, so boxes move smoothly without running inference during
playback. CAM-03 is sampled at 4 FPS for better posture continuity. Its fixed
camera profile also retains a repeatedly confirmed parked vehicle as scene
memory, and marks person-like detections in the calibrated lifting corridor as
hook **review candidates** rather than silently calling them workers.

Temporal safety events are review candidates derived from several consecutive
pose samples. They warn on a rapid downward posture change inside the handling
workfront, but remain explicitly labelled as unconfirmed until a supervisor
reviews the clip. The system does not claim pipe recognition,
construction-progress measurement, or autonomous incident confirmation.
