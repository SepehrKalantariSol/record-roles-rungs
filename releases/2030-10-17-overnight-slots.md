# Release: overnight slots, 2030-10-17

Written by the deployer before the cutover. Nothing above the line changes
after the cutover starts; the outcome is added below it.

| | |
|---|---|
| Tickets | TCC-142 |
| Image | `portal:overnight-slots-2030-10-17`: the build QC passed on staging as `portal:overnight-slots-rc2` (commit-wren), retagged, not rebuilt |
| Live now | `portal:dock-notes-fix-2030-10-11`, measured on portal.tollaven.example at 09:41Z from the build stamp on the rendered page |
| Migration | none. The work order says no schema change; migration state measured at 09:41Z: `mig-0031` in place, nothing pending |
| Order | code only, so nothing to order. Had there been a migration, it would run as its own job and finish before the image reference changes |
| Rollback target | `portal:dock-notes-fix-2030-10-11`, the image measured live. The work order's baseline named `portal:dock-notes-2030-10-04`; rolling back to that would also have removed the fix of 11 October. Corrected in the record by event 18 |
| What would undo a rollback | auto-sync on the configuration repository. Its head will name the new image, and any commit there, of any kind, makes the controller apply that head again |
| How to roll back, then | revert `cfg-otter` in the configuration repository and let the controller apply the revert. Not a hand change to the cluster. If a hand change is ever unavoidable, pause auto-sync first and write here who resumes it and when |
| Pre-release dump | object storage, `dumps/2030-10-17-pre-overnight-slots`, taken 09:52Z |
| Cutover | one commit, `cfg-otter`, changing the portal's image reference in the configuration repository |

---

## Outcome

| | |
|---|---|
| Cutover | `cfg-otter` merged 10:14Z; controller synced 10:16Z; rollout complete 10:19Z |
| Health probe | green throughout. Recorded, not counted: it reads nothing this release changed |
| Hosted journey | production, portal.tollaven.example, 10:30Z to 10:33Z, run `jt-kestrel-03`. Signed in as dispatchers of the two production test carriers, test carrier A and test carrier B, and as a shift lead. 12 of 12 steps pass, the same steps as staging attempt 2 (`tickets/TCC-142/evidence/2030-10-16-qc-2/journey.txt`), including the next day's export holding the booking that crosses midnight |
| Fingerprint | tables, rows, content digest, migration state, stored objects and their digest: equal before and after, once the journey's 5 bookings and 4 exports, all carrying `jt-kestrel-03`, were removed by that run's mark |
| Rung reached | verified |
| Rollback | not used. Auto-sync left on; nothing to undo |
