# NOTES-opus: spec review

Review of SPEC.md for the VAST Builders Challenge London, 17 Oct 2026. Done on 15 Oct 2026. SPEC.md was edited in place; this file says what changed, why, what I read, and what is still open.

Source content is paraphrased throughout. Quotes are short. Anything from an earlier event (San Francisco or New York) is tagged [PRIOR-EVENT] in the spec: probably true in London, but check it at 09:30.

## 1. The changes that matter most

1. **Window end is "obvious", not "closest approach".** The research that built the test defines the window from the earliest sign a hazard is developing to the point it becomes obvious ([TRL558](https://www.trl.co.uk/uploads/trl/documents/TRL558.pdf); [PPR2071](https://www.trl.co.uk/uploads/trl/documents/PPR2071-Validation-of-CGI-hazard-perception-clips.pdf)). The old spec ended windows at closest approach. That makes windows too long, so late clicks score and random clicking pays. Fixed in 7.7, 13.4 and Appendix D. Window bounds changed from 2-8 s to 1-7 s, the range TRL558 reports.
2. **Five equal bands and "first click counts" are now sourced, not assumed.** TRL558 says the window is split into five equal sub-windows and only the first response in it is scored. Points fall with time, so the first click is also the best; the old "best click" rule gives the same answer. Live DVSA clip parameters are still unpublished, so the spec keeps one [ASSUMPTION] that live clips still work this way.
3. **The click allowance is a fixed number, the same for every clip, and secret.** DSA's 2012 FOI answer says so ([FOI IA/00436/12](https://assets.publishing.service.gov.uk/media/5a78e203e5274a2acd18a860/dsa-ia0043612a.pdf)). In 2007 the Information Commissioner upheld DSA's refusal to publish the number and the minimum gap, because it would help candidates beat the test ([ICO FS50115678](https://ico.org.uk/media2/migrated/decision-notices/401338/fs_50115678.pdf)). The old P1 grew with hazard count, so the pattern rule depended on the labels. P1 is now "more than 8 clicks", and no pattern rule sees the labels (9.3).
4. **Random clicking was a real threat; clips are now 30 s and every agent is shown against chance.** Short clips with wide windows let a random clicker score well (numbers in section 4 below). Changes: clips are whole 30 s chunks (7.2), a gaming check runs before the test set is frozen (14.5), and every agent is reported as lift over a random clicker with the same number of clicks on each clip (14.3, Appendix E). Our rule is public and DVSA's is not, so ours can be gamed; this baseline is how we show nobody is gaming it.
5. **Scorer bug fixed.** The old float scorer gave 5 points for a click on the 1/5 band edge: `(6.6 - 6.0) // 0.6` is 0.0 in floating point. The new scorer works in integer ms. Conversion must use `round()`, not `int()`: `int(2.01 * 1000)` is 2009, and 18 of the 3,001 two-decimal times from 0 to 30 s convert wrongly with `int()`. I extracted the new scorer from SPEC.md and ran the worked example and the unit-test cases in 9.7; all pass.
6. **YOLO comes from stored per-frame boxes, not per-frame endpoint calls.** The YOLO endpoint takes a whole video, not a frame ([gpu skill](https://github.com/vast-data/vast-builders-challenge/blob/main/.cursor/skills/gpu/README.md)). CrossWise built 5 fps tracks from the boxes VAST already stores for every frame, read from `/videos/detections` ([CrossWise](https://github.com/sairamveereddy/CROSSWISE)). This removes the YOLO client, batching and shared-endpoint latency from the critical path (7.4).
7. **Cosmos is computed once on a verdict grid, with blocking and non-blocking agents and a points-versus-latency curve.** CrossWise's direct Cosmos calls at NYC took 2.9-9.1 s, median 4.3 s (from their `data/cosmos_captions.json`). That is longer than many scoring windows, so a blocking verifier may lose points every time. Changes:
   - verdicts are computed once per clip on a 0.5 s grid, so threshold sweeps cost nothing (12.3);
   - `yolo_cosmos_async` clicks first and verifies in the background. Wrong clicks are free until the allowance runs out, so verification is only worth what it saves of the click budget (1.2);
   - latency is a controlled variable: measured, fixed L, or zero (9.5).
8. **Cosmos prompt rewritten against yes-bias.** At NYC another team asked Cosmos directly whether clips showed a near miss and got yes on 168 of 180 ([Warehouse best buddy](https://tokensand.com/p/warehouse-best-buddy)). The new prompt asks for observable facts (where, motion, our car, act) and our code decides HAZARD (A.1). The spec also adds a false-alarm check on calm dev moments (14.5).
9. **Labelling is blind-first and blind to YOLO.**
   - Everyone's first view of a clip is a recorded blind sit (13.3), so each test clip gets two blind human baselines at about 35 s per person.
   - Labellers no longer see the auto proposal, risk curve or boxes until they save. Otherwise the "YOLO proposes windows within x s" result is meaningless, and labels drift towards YOLO's view.
   - Mining may not rank by our own YOLO risk (selection bias, 14.6).
   - Roles changed so nobody labels or arbitrates a clip before their blind sit (13.1).
10. **"Pedestrian crossing in front of a stopped car" is excluded.** Dashi's top pedestrian search hit at SF was the camera car stopped at a junction while people crossed ([Dashi](https://github.com/vaishnav-16/dashi)). The car is already stopped, so nothing makes it change speed or direction, and DVSA's definition is about having to act ([gov.uk](https://www.gov.uk/theory-test/hazard-perception-test)). Excluded in 13.2. Search queries now favour a moving camera car and use US spelling ("curb"), because the captions are US English.
11. **Deployment matches what `/deploy-app-no-registry` actually does.** The skill runs `python:3.12-slim` with code in a ConfigMap of about 1 MiB, pip at start, `$PORT`, `/health`, and an `/app` prefix that is stripped ([skill](https://github.com/vast-data/vast-builders-challenge/blob/main/.cursor/skills/deployment/deploy-app-no-registry/SKILL.md)). The old spec served mp4s and frames from the app and saved labels through it, which cannot work there. Changes (6.4):
    - the app has two modes: `dev` on the VM writes labels into git; `demo` in the pod serves a read-only snapshot under a 900 KB budget;
    - video goes through a VSS stream proxy, never stored in the pod;
    - the pod uses the in-cluster backend URL that both earlier teams needed;
    - URLs are relative and routes are hash routes;
    - we never write media into the pipeline buckets.
12. **Timeline fixed for a 16:30 deadline and a required video.** The tokens& page gives 16:30 BST as the submission deadline and lists a demo video with a shareable link as required ([tokens&](https://tokensand.com/vastlondon)). The old plan froze code at 16:00 and submitted at 16:30, with the video as optional. Now: code freeze 15:30, video 15:30-16:00, submitted by 16:20 (section 20). The VAST guide says submissions "start around 4:30pm" ([README](https://github.com/vast-data/vast-builders-challenge/blob/main/README.md)), so this is on the list to ask.
13. **Weave uses EvaluationLogger, not `weave.Evaluation`.** `Evaluation.evaluate` runs 20 predictions at once by default (`WEAVE_PARALLELISM`, checked in the weave 0.53.12 source). With live Cosmos calls that inflates the very latency we charge. EvaluationLogger records our own sequential harness and still gives the Evals compare view ([docs](https://docs.coreweave.com/products/wandb/weave/guides/evaluation/evaluation_logger)). Env var names fixed: the VM has `WANDB_TEAM`, not `WANDB_ENTITY` ([config.example](https://github.com/vast-data/vast-builders-challenge/blob/main/config.example)).
14. **Eval design tightened.**
    - Paired bootstrap for every A-vs-B claim; overlapping marginal intervals do not answer "is A better than B".
    - Label sensitivity: rescore every run under each labeller's windows.
    - Matched chance, and the straw-man honesty for `yolo_naive`.
    - A small dev tuning grid: 6 dev clips cannot support 72 configs.
15. **GPU auth corrected.** The old spec said no token is needed, which the architecture reference also says. The GPU skills say always send `Authorization: Bearer $GPU_BEARER_TOKEN`, and CrossWise did. Model ids now come from `/v1/models`: at NYC the endpoint served `nvidia/cosmos3-nano-reasoner`, not the `nvidia/cosmos3-reason` in config.example.
16. **VastDB moved from could to should.** The `vastdb-write` skill documents creating our own schema and tables ([skill](https://github.com/vast-data/vast-builders-challenge/tree/main/.cursor/skills/vast-database)), so the old "can we create tables?" question is answered. Rows are keyed by segment `source`, so our labels sit next to the index rows: a concrete moment for the two VAST judges (7.13, 10.10).
17. **Demo now has an honest "did it pass?" moment.**
    - The car pass mark is verified as 44 of 75 ([gov.uk](https://www.gov.uk/theory-test/pass-mark-and-result)). It is shown as a 58.7% reference line, never called a pass.
    - The demo adds the latency curve for the NVIDIA judge.
    - It adds a 90 s table walkthrough, since the first judging round is at the table.
18. **Judge names checked against the event page** ([Luma](https://luma.com/vastlondon)). The page lists "Ram B.", not a full surname, so the spec says "Ram B." unless confirmed. The page lists Abubakr Karali as Senior Solutions Architect at NVIDIA; "Metropolis" is from our notes and is not on the page.

## 2. Section by section

| Section | Change |
|---|---|
| Header | Deadline 16:30 per tokens&; first judging round at the table; repo must be reviewer-accessible |
| 0 | New markers [PRIOR-EVENT] and [UNVERIFIED]; 37 numbered sources with links (0.3) |
| 1.2 | DVSA facts sourced; FOI and ICO on the click allowance; TRL window definitions; "false alarms are free until the allowance runs out" |
| 1.3 | Link to NVIDIA VSS alert verification |
| 3 | Goals updated: matched chance baseline (must), VastDB (should), vlm_wb (could) |
| 4 | Judges as listed on Luma; uniqueness check over 86 prior projects with nearest neighbours; related research |
| 5 | Auth, hosts, model ids, Cosmos NIM parameters, latency data, segment structure, PIE facts, earlier teams' findings, new hard constraints |
| 6 | New architecture diagram; two-mode deployment; ConfigMap budget; in-cluster URL; no media in the pod |
| 7 | Miner queries and scrubbing; clip = 30 s chunk; detections loader; proposer hidden and "obvious" end; replayer clock rules; gate, async, vlm_wb, baselines; VastDB |
| 8 | Rules table with sources; R6-R9 added; pass mark as reference only |
| 9 | Integer-ms scorer; fixed-cap pattern rules that ignore labels; latency modes; new aggregates; tests |
| 10 | Clip and candidate tied to chunks and segment sources; blind flags; versions on runs; VastDB tables keyed by `source` |
| 11 | Mode column; video proxy with allow-list; live endpoint replaced by recorded replay; client details |
| 12 | Harness mediates every verifier call; scoring separated; verdict grid; gate and async code |
| 13 | Roles for blindness; stationary-ego exclusion; blind first view; TRL window rules; agreement keeps both windows |
| 14 | Matched chance; paired bootstrap; label sensitivity; gaming check; verifier false alarms; selection bias |
| 15 | EvaluationLogger; parallelism; env names; scorer argument name |
| 16 | Relative URLs and hash routes; preload; frame-accurate click timing; label screen hides YOLO until save; pass-rate line |
| 17-19 | Repo, pod requirements, deploy folder, secret scan, VM setup without pip, env table, config defaults |
| 20-22 | Timeline for 16:30 and the video; four-question go/no-go; MVP and stretch order |
| 23 | 25 risks, 10 new |
| 24-26 | Table walkthrough; stage script with latency curve and pass line; submission fields as listed; open questions split into answered and still to ask |
| Appendices | New Cosmos and VLM prompts; proposer with "obvious" end; paired bootstrap and matched chance; AST-based leak test; glossary; changelog |

## 3. What I read

DVSA and the test:

- gov.uk: [hazard perception test](https://www.gov.uk/theory-test/hazard-perception-test), [pass mark and result](https://www.gov.uk/theory-test/pass-mark-and-result), [CGI clips from 12 January 2015](https://www.gov.uk/government/news/hazard-perception-clips-get-a-modern-makeover).
- DSA FOI answer IA/00436/12, Annex A, created 9 October 2012 according to the PDF's metadata: [PDF](https://assets.publishing.service.gov.uk/media/5a78e203e5274a2acd18a860/dsa-ia0043612a.pdf).
- ICO decision notice FS50115678, 31 May 2007: [PDF](https://ico.org.uk/media2/migrated/decision-notices/401338/fs_50115678.pdf).
- TRL558, Grayson and Sexton (2002), The development of hazard perception testing: [PDF](https://www.trl.co.uk/uploads/trl/documents/TRL558.pdf).
- TRL PPR2071, Validation of CGI hazard perception clips: [PDF](https://www.trl.co.uk/uploads/trl/documents/PPR2071-Validation-of-CGI-hazard-perception-clips.pdf).

Event and platform:

- [tokens& event page](https://tokensand.com/vastlondon) and [Luma page](https://luma.com/vastlondon).
- [vast-data/vast-builders-challenge](https://github.com/vast-data/vast-builders-challenge), read at commit `bc97c08`: README, BEFORE_YOU_BUILD.md, ARCHITECTURE_REFERENCE.md, config.example, `.cursor/rules/build-day.mdc`, and every skill under `.cursor/skills/` (gpu, retrieval, ingest, deployment, vast-database, ask-cosmos, build-day-quickstart).

Earlier events in this series:

- Galleries: [San Francisco](https://tokensand.com/vastsf/projects) (45 projects) and [New York](https://tokensand.com/vastnyc/projects) (41 projects). I read all 86 titles and summaries, and the nearest ones in full.
- Repos read for real API behaviour on this stack: [CrossWise](https://github.com/sairamveereddy/CROSSWISE) (NYC) and [Dashi](https://github.com/vaishnav-16/dashi) (SF).
- Pages cited: [BLACKBOX](https://tokensand.com/p/blackbox), [Warehouse best buddy](https://tokensand.com/p/warehouse-best-buddy), [CloseCall](https://tokensand.com/p/closecall), [Evidence Atlas](https://tokensand.com/p/evidence-atlas), [Grabbit Mining Co.](https://tokensand.com/p/grabbit-mining-co), [Drive Recap](https://tokensand.com/p/drive-recap), [Vision Zero Agent](https://tokensand.com/p/vision-zero-agent-1), [Nostradamus](https://tokensand.com/p/nostradamus).

NVIDIA:

- [NIM for VLMs: Query the Cosmos 3 Reasoner API (1.7.0)](https://docs.nvidia.com/nim/vision-language-models/1.7.0/examples/cosmos-reason3/api.html).
- [Cosmos 3 reasoner cookbook](https://github.com/NVIDIA/cosmos/blob/main/cookbooks/cosmos3/reasoner/README.md).
- [VSS documentation](https://docs.nvidia.com/vss/latest/).

Weights & Biases:

- [EvaluationLogger docs](https://docs.coreweave.com/products/wandb/weave/guides/evaluation/evaluation_logger).
- [Serverless inference models](https://docs.coreweave.com/inference/models) and [API reference](https://docs.coreweave.com/products/inference/serverless/api-reference).
- The [`weave` 0.53.12](https://pypi.org/project/weave/0.53.12/) package, installed in a scratch venv to check signatures, the default parallelism and the scorer argument name.

Footage and related research:

- PIE: [Rasouli et al., ICCV 2019](https://openaccess.thecvf.com/content_ICCV_2019/papers/Rasouli_PIE_A_Large-Scale_Dataset_and_Models_for_Pedestrian_Intention_Estimation_ICCV_2019_paper.pdf) and the [annotations repo](https://github.com/aras62/PIE) (MIT licence).
- Related research: [VLAlert](https://arxiv.org/abs/2609.08130) and [RiskCueBench](https://arxiv.org/abs/2601.03369). Both work on when to warn from video. Neither abstract mentions the DVSA rule.

Could not verify:

- That live DVSA clips still use five equal bands.
- Whether the real test shows a flag per click (third-party sites only).
- "Metropolis" for Abubakr Karali, and Ram's surname.
- Anything about the London corpus.
- That the shared Cosmos endpoint accepts `video_frames` and the sampling parameters.
- Cursor port forwarding to the lab VM.
- Whether writing to the pipeline buckets triggers ingest.
- The clip length of today's DVSA clips. TRL558's trial tests ran 13 scenarios in 10-12 minutes, but that was 1995.

## 4. Our own numbers (not data)

**Random clicker simulation.** One hazard. Window start uniform between 5 s and the end of the clip less the window. k clicks uniform over the clip. Scored with the same five bands and `PATTERN_V1` rules (P1 more than 8). 20,000 trials. Expected points out of 5:

| Clip | Window | k=1 | k=2 | k=4 | k=6 | k=8 |
|---|---|---|---|---|---|---|
| 15 s | 2 s | 0.41 | 0.76 | 1.39 | 1.85 | 2.24 |
| 15 s | 3 s | 0.60 | 1.10 | 1.93 | 2.48 | 2.89 |
| 15 s | 5 s | 1.01 | 1.75 | 2.77 | 3.37 | 3.66 |
| 30 s | 2 s | 0.19 | 0.40 | 0.74 | 1.07 | 1.34 |
| 30 s | 3 s | 0.29 | 0.58 | 1.07 | 1.52 | 1.88 |
| 30 s | 5 s | 0.50 | 0.95 | 1.68 | 2.24 | 2.67 |

A second run (cap 6, which changes nothing for k up to 6) gave 60 s clips a little over half the 30 s figures, for example 1.29 for a 5 s window at k=6. The old spec's 10-25 s clips with windows clamped to 2-8 s and closest-approach ends sit near the top of this table. That is the main reason for 30 s clips, "obvious" ends and the matched-chance baseline.

**EMA lag in `yolo_risk`.** With weight 0.4 at 5 fps and a 0.6 threshold, a jump straight to 1.0 crosses one frame later (0.2 s). A jump to 0.7 crosses three frames later (0.6 s). On a 1 s window that is one to three bands, so the weight is now a tuned parameter.

**Grid cost.** About 20 clips x 30 s with a third of the time above risk 0.3 gives a few hundred Cosmos calls. That is 10-20 minutes at 2-5 s each with 2 in flight. This is an assumption: measure at 09:30.

## 5. Risks still open

- **Hazard density in PIE.** About 90 minutes of `pie_cam-3` at earlier events. Dashi found 1 coachable moment in 22 chunks, but that is a different question from ours. Captions rarely say what the camera car does, and vehicle-hazard searches came back nearly empty. Scrubbing is the plan; near-miss mode is the fallback.
- **Pedestrian detection on PIE.** Dashi found person counts low and YOLO noisy on this footage. If pedestrians are not boxed, detector agents will score badly. That is a finding, but it weakens the Cosmos comparison, because the Cosmos agents are triggered by YOLO.
- **Cosmos latency and quality on the day.** The shared endpoint may be slower in London. It may not accept the NIM parameters. It may still say HAZARD to everything despite the new prompt.
- **Label noise against band width.** A 0.6 s agreement tolerance is a full band on a 3 s window. The label-sensitivity report exposes this but does not fix it.
- **Small n.** 14-20 test hazards. Intervals will be wide. Only claim differences the paired interval supports.
- **Deploy unknowns.**
  - Pod networking to VSS and PyPI.
  - The 900 KB budget.
  - Video playback through the proxy on event wifi.
  - Segment-stitched playback in judge mode: click timing comes from media time, so it stays accurate, but a visible stutter at segment edges is possible.
- **Dev mode depends on port forwarding** from Cursor to the VM. If that fails, labelling has to happen through the pod with VastDB persistence. That is slower and riskier.
- **Scope.** Still a lot for 7 hours with 3 people. If behind at 12:00, the realistic cut is: async agent, VastDB, `vlm_wb` and everything below them in 22.2. The MVP plus `yolo_cosmos_gate` with the matched-chance baseline is a complete story.
- **Repo going public.** Run the secret scan over full history first. Bucket names and team numbers in data files are not secrets, but check for tokens.
- **SUMMARY.md is now out of step with the spec.** Step 2 still says the window runs "to the moment it is closest" and that YOLO gives a first guess a human checks. I did not edit SUMMARY.md because the brief was SPEC.md. Update it if you accept the changes; teammates are told to read it first.
- **"Real-time" claim.** Every run is a pseudo-live replay of recorded footage, with thinking time charged. Say exactly that. Do not imply live streams.

## 6. Questions for organisers on the day

1. Is 16:30 the submission deadline (tokens&) or when submissions open (VAST guide)? Can a submission be edited after it is sent?
2. Is the London corpus the same as SF and NYC? Is there any UK driving footage?
3. One lab VM per person, or one per team?
4. Does writing to the chunks or segments bucket trigger ingest? Is there a scratch bucket or prefix we may use?
5. May we use the public PIE annotations (not videos), for example ego speed, to check our windows?
6. Can the pod reach `video-backend-service.<team>.svc.cluster.local` and PyPI? Can `/videos/stream` serve a whole chunk (`original_video`) or only segments?
7. Does the shared Cosmos endpoint accept `video_frames`, `media_io_kwargs` and `mm_processor_kwargs`? What is a polite number of calls in flight?
8. Can judges view our Weave project, and may we create our own project under the team?
9. Is the first judging round at the table, and is there a stage final? How long per team?
10. Is a UK hazard-perception framing fine given the footage is from Toronto?
11. Is any external footage allowed at all? (Assume no.)
