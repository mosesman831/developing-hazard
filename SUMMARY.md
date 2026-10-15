# Developing Hazard - summary

Built for the VAST Builders Challenge London (Real-Time Video Agents Hack), Saturday 17 October 2026.
Team: Moses (mosesman831), Riyu-D1, fmdplt33.

## What it is

Every learner driver in Great Britain sits the hazard perception test. You watch dashcam-style clips and click when you see a "developing hazard": something that will make the driver change speed or direction. Click early in the hazard's window and you score up to 5 points. Click late and you score less. Click constantly or in a pattern and the clip scores 0.

Developing Hazard makes an AI sit that test on real dashcam footage from the hackathon's video index.

## How it works, in plain English

1. **Find test clips.** We search the indexed footage (mostly Toronto dashcam drives) for stretches that start calm and then something develops: a pedestrian stepping out, a car pulling across.
2. **Mark the answer key.** For each clip we work out the scoring window: from the moment an object starts heading into the car's path to the moment it is closest. YOLO tracks give a first guess; a human checks it.
3. **Play the clip as if it were live.** The agent sees frames one at a time, never the future. YOLO plus simple time-to-collision maths raises a "risk" signal.
4. **Think before clicking.** When risk rises, Cosmos Reason is asked "is this a real developing hazard?" before the agent clicks. The time it takes to think counts against it, like a real driver.
5. **Mark it the DVSA way.** 5 to 0 points by click timing, and 0 for click spamming.
6. **Leaderboard.** In Weights & Biases Weave we compare YOLO alone, YOLO plus Cosmos, a W&B-hosted LLM, and humans (including judges) on about 20 hand-labelled clips.
7. **Explain the misses.** An LLM writes a short note on why the agent missed a hazard, using the trace.

## Why it is interesting

- Everyone in the room has either taken this test or knows someone who has. The question "can an AI pass it?" needs no explanation.
- It is an honest evaluation of a video agent, with a real, published scoring rule, not a vibe check.
- The headline result is counter-intuitive: a raw object detector that "sees everything" scores badly, because seeing everything means clicking at everything.
- It uses the whole sponsor stack: VAST index and database, NVIDIA Cosmos and YOLO on CoreWeave, W&B inference and Weave, built in Cursor.

## The demo (3 minutes)

"Every UK learner sits this test. Can an AI pass it?" A judge clicks along to a clip live. Then the AI sits the same clip, with its reasoning trace shown. YOLO on its own scores 0 for spamming. Then the leaderboard, then one miss explained.

## What it is not

It is not a self-driving system and does not claim to be. It is a benchmark and a demo of how a video agent should decide *when* to act, not just *what* it sees.

Full detail is in [SPEC.md](SPEC.md).
