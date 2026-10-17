# Merge bot log

Only the Hackathon PR merge bot edits this file. One line per decision: time (BST), PR, agent, merged or rejected, reason.

- 11:13 BST, PR #4, AG2 (Riyu-D1), merged (4f43945). Phase 1 tasks 1, 2, 4, 5, 6 accepted. Go/no-go probes (AG2-P1-3) waived by Moses, moved to start of Phase 2. AG2-P1-PR left unticked until probes run. web/label.js needs AG3's web/player.js to load.
- 11:13 BST, PR #6, AG1 (mosesman831), merged (cfcfb41). Phase 1 tasks 1-4, 6, 7 accepted. Go/no-go probes (AG1-P1-5) waived by Moses, moved to start of Phase 2. AG1-P1-5 and AG1-P1-PR Agent cells were falsely ticked (probes not run); unticked on the branch before merge (3e078b8), confirmed by gate. Their Gate and Merged cells stay unticked.
- 11:13 BST, M-P1 not ticked: AG3 (fmdplt33) has no Phase 1 PR yet.
- 11:50 BST, PR #9, AG1 (mosesman831), merged (029095e). Phase 2 tasks 1-7, 9, 10 and acceptance accepted: 100 tests pass, run r_yolo_risk_20261017T113337 on example clip c07 (AG2 dev clips not merged, no detections, scores 0), gaming check on a synthetic sit (yolo_risk 0.80 vs random@matched 0.082), PATTERN_V1 frozen. AG1-P2-8 (blind human sit) not done; its Gate and Merged cells stay unticked. M-P2 not ticked: AG2 #8 held, no AG3 Phase 2 PR.
