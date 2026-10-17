# Developing Hazard

An AI sits the UK hazard perception test on real dashcam footage.

We built a small fleet of agents that watch thirty-second dashcam clips the way a learner driver would: react when something develops, score clicks against human hazard windows, and log every decision to Weave. Riyu mined clips from VSS caption search on Toronto PIE footage, labelled hazard windows blind, and stored labels beside segment sources in VastDB. Moses ran YOLO11 detections on CoreWeave, tuned a risk EMA agent on dev clips only, and gated optional Cosmos Reason calls on a precomputed verdict grid so latency stays honest. The web app replays runs, shows the leaderboard, and hides another labeller's window until you have saved your own.

**Stack:** VAST AI OS (VSS search, videos, VastDB), Cosmos3-Reason, Cosmos Embed1, YOLO11 on CoreWeave, W&B inference + Weave, Cursor.

**Team:** mosesman831, Riyu-D1, fmdplt33. Weave project `vastdata/team-36`.

**Honest limitations (SPEC 25):** small test set; single-labeller windows with no second labeller pass and no frozen test set at time of writing; windows are ours, not DVSA's; footage is dashcam from Toronto, not UK test clips. On dev, tuned `yolo_risk` scored 6/15 (run `r_yolo_risk_20261017T122620`); that is tuning signal, not a claim about the unseen test split.
