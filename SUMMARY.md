# Developing Hazard - summary

Built for the VAST Builders Challenge London (Real-Time Video Agents Hack), Saturday 17 October 2026.
Team: Moses (mosesman831), Riyu-D1, fmdplt33.

## What it is

Every learner driver in Great Britain sits the hazard perception test. You watch dashcam-style clips and click when you see a "developing hazard": something that will make the driver change speed or direction. Each hazard has a scoring window, from the first sign it is developing to the moment it becomes obvious. The window is split into five equal parts: click in the first and you score 5, in the last and you score 1, outside it and you score 0. Only your first click in the window counts. Wrong clicks are free, but clicking constantly or in a pattern scores 0 for the whole clip.

Developing Hazard makes an AI sit that test on real dashcam footage from the hackathon's video index.

## How it works, in plain English

1. **Find test clips.** We search the indexed footage (Toronto dashcam drives) for 30-second chunks where something develops: a pedestrian stepping out, a car pulling across. Clips are a full 30 seconds because on short clips random clicking scores well.
2. **Mark the answer key blind.** Two of us watch each clip and click as if sitting the test, without seeing YOLO's guess or each other's answer. Then we agree a window per hazard: from the first sign it is developing to the moment it becomes obvious.
3. **Check it can't be gamed, then freeze it.** Before 12:30 we check a random clicker can't get close to our agents on practice clips, and fix our click-spam rules. The test set is frozen at 14:00 and never changed after.
4. **Play the clip as if it were live.** The agent sees frames one at a time, never the future. YOLO, using the detections already stored with the footage, plus simple time-to-collision maths raises a "risk" signal.
5. **Think before clicking.** When risk rises, the agent checks Cosmos Reason's verdict on "is this a real developing hazard?". Cosmos is slow (seconds per call), so we run it once per clip on a time grid and reuse the answers. Its thinking time still counts against the agent, like a driver's reaction time.
6. **Mark it the DVSA way.** 5 to 1 points by which fifth of the window the first click lands in, 0 outside it, and 0 for the clip if the click-spam rules fire. Times are exact to the millisecond.
7. **Leaderboard.** In Weights & Biases Weave we compare YOLO alone, YOLO plus risk, YOLO plus Cosmos, and blind human sits (including judges) on 15-20 clips. Every result sits next to a random clicker with the same number of clicks, which is the line an agent has to beat.
8. **Explain the misses (spare half hour).** If there is a spare ~30 minutes in the afternoon, the W&B serverless LLM writes a plain-English explanation of each miss from the Weave trace. We check each one before showing it. That puts W&B's hosted model visibly in the demo for the W&B judge. It is a quick win, not core.

## Why it is interesting

- Everyone in the room has either taken this test or knows someone who has. The question "can an AI pass it?" needs no explanation.
- It is an honest evaluation of a video agent, with a real, published scoring rule, not a vibe check.
- The headline result is counter-intuitive: a raw object detector that "sees everything" scores 0, because seeing everything means clicking at everything. We say on stage that this one is a straw man on purpose, and the fair comparison is on the leaderboard.
- It uses the sponsor stack end to end (see Sponsor fit below).

## The demo (3 minutes)

"Every UK learner sits this test. Can an AI pass it?" A judge clicks along to a 30-second clip live. Then the AI sits the same clip, with its reasoning trace and Cosmos delay shown. YOLO on its own scores 0 for spamming. Then the leaderboard with the random-clicker line, the chart of points against Cosmos delay, then one miss explained. We never say "pass": this isn't the real DVSA test.

## The day

Code freezes at 15:30. We record the required demo video from 15:30 to 16:00 and submit before the 16:30 deadline.

## Sponsor fit

- **VAST:** search the video index; write results back.
- **NVIDIA:** Cosmos Embed to find clips, Cosmos Reason to confirm hazards, YOLO for detections.
- **W&B:** Weave traces every click, the leaderboard lives there, and the serverless LLM writes miss explanations if we have half an hour spare.
- **Cursor:** we build in it over Remote-SSH.
- **CoreWeave:** the GPUs underneath everything; every team uses them, so this is not a demo feature.

## What it is not

It is not a self-driving system and does not claim to be. It is a benchmark and a demo of how a video agent should decide *when* to act, not just *what* it sees.

Full detail is in [SPEC.md](SPEC.md).
