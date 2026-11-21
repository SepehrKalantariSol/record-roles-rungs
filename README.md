# Record, roles, rungs

Running production work through a team of AI coding agents without losing
control of it.

## What this is

This repository is a **structural design extracted from a private production
system and rebuilt for publication.** Nothing here was copied from that
system. Every file was written new, from a description of the design, so that
the method could be shown without anything that belongs to the system behind
it.

- **The estate is invented.** Tollaven Cold Chain, its dock-booking portal,
  its carriers, its people and its tickets do not exist. The framing is
  invented too: presenting the method as serving an operator like this one is
  part of the example, and says nothing about where the design came from.
  Hosts end in `.example`. Dates fall in October 2030 so that nobody mistakes
  them for history.
- **Two incidents are rebuilt** (PRACTICE.md §8 and §9). Each mechanism
  really happened; the particulars (doors, counts, times) are invented.
- **The other rules carry their reasoning, not their incident.** In the real
  system every rule cited the incident that produced it. Here only two are
  told in full.

Author: Sepehr Kalantari, GitHub account SepehrKalantariSol.

## The idea

Agents are fast, confident and forgetful. The control comes from three things:

1. **A record that cannot be quietly rewritten.** Every ticket is a directory
   in a git repository. The request is kept verbatim, the log only grows, and
   CI fails any change that edits history.
2. **Roles that cannot widen themselves.** Each role is a file saying what it
   must not do, a separate grant file says which tools it may use, and a deny
   list sits behind both. Roles change by pull request, never by an agent.
3. **A "done" that only the live system can satisfy.** A change is finished
   when a real browser journey has passed against the deployment, with a
   fingerprint of the data before and after. Not when it builds.

## Layout

```
README.md                  this file
PRACTICE.md                the rulebook: process, work orders, rungs, incidents
MANAGER.md                 instructions for the main manager, the top-level session
agent-settings.json        commands no agent may run
roles/                     one file per role, plus toolbelt.json, the tool grants
bin/record.py              the only write path into the record
bin/guard.py               CI check: write-once files and append-only logs stay so
bin/render_agents.py       renders agent definitions from roles + grants
.github/workflows/record-guard.yml
tests/test_record.py       one test per refusal and per invariant
tickets/
  TCC-142/                 the worked example
    request.md             the request, verbatim             (write-once)
    order.json             the work order                    (write-once)
    events.jsonl           one line per handoff              (append-only)
    questions.jsonl        questions, and answers verbatim   (append-only)
    lease.json             present only while a stage is held
    evidence/
      2030-10-15-qc-1/     <date>-<stage>-<attempt>, or <date>-intake
releases/
  2030-10-17-overnight-slots.md   one record per cutover
```

### The four invariants

1. **The request and the work order are written once.** What was said and what
   someone understood are kept apart, so a wrong reading can be found and
   corrected against the original words.
2. **The event log only grows.** A correction is a new event that cites what
   it corrects; history that can be edited is not evidence.
3. **Status is never stored; it is derived from the last event.** A stored
   status is a second copy of the truth, and copies drift.
4. **The log holds references, never content.** A commit, an image, a path
   under evidence: the log stays small and readable, and the content stays
   where it can be checked.

**Why git:** it already gives an author and a date on every change, a history
that is expensive to falsify, and reach from wherever the work happens. There
is nothing to host.

## Run it

Python 3.8 or later and git. No packages.

```sh
python3 -m unittest discover -s tests -v
```

The tests prove each refusal and each invariant: a duplicate key appends
nothing, secret shapes are refused, an over-long reference is refused, blocked
without a reason is refused, a second work order is refused, the guard rejects
an edited log and passes an extended one. The lease tests build a real bare
remote and two clones in a temporary directory, and show that the second
claimant's rejected push is the lock. `WorkedExampleTests` checks that the
worked example obeys the same rules the tool enforces.

Then read the example's state, derived from its log:

```sh
python3 bin/record.py status TCC-142
```

```
TCC-142
  kind       fix: A booking appears on every UTC day its slot overlaps: in the carrier's dispatcher list, in the shift lead's schedule and in each day's export.
  state      passed report (#22, main-manager)
  rung       verified (#20)
  lease      none
  questions  0 open of 1
  last       #22 2030-10-17T11:02:00Z main-manager report pass
```

To watch the refusals yourself, work in a scratch copy:

```sh
demo=$(mktemp -d) && cp -R bin "$demo"/ && cd "$demo"
printf '%s\n' "The door board shows door 7 as free while a truck is unloading at it." > request.txt
python3 bin/record.py intake TCC-150 --source "shared inbox (shift lead)" \
    --received 2030-10-23T06:10:00Z --text-file request.txt
python3 bin/record.py append TCC-150 --actor qc --stage qc --decision blocked --key qc:TCC-150:1
#   refused: a blocked decision must say what it is blocked on (--blocked-on)
python3 bin/record.py append TCC-150 --actor qc --stage qc --decision blocked --key qc:TCC-150:1 \
    --blocked-on "no staging host this morning"
python3 bin/record.py append TCC-150 --actor qc --stage qc --decision blocked --key qc:TCC-150:1 \
    --blocked-on "no staging host this morning"
#   TCC-150: already recorded as #2 under key 'qc:TCC-150:1'; nothing appended
python3 bin/record.py status TCC-150
```

The secret refusals are left out of this walkthrough on purpose: showing one
would mean writing a secret-shaped line into this file, and this repository
holds none. The tests assemble those inputs from pieces at run time and prove
that each is refused.

`claim` and `release` need a remote to push to; the lease tests show them
working against one.

## The worked example

`tickets/TCC-142/` is one fix, end to end. A booking that runs across midnight
UTC is missing when the carrier's dispatchers open the next day's bookings,
and the shift lead's schedule for that day leaves it out too. Every fixture
had been a mid-morning slot. The first fix selects bookings by interval
overlap instead of by the date of their start, and its local test, with a new
cross-midnight fixture, passes. On staging the hosted journey downloads the
next day's export and reads it, and the booking is not there: the export
builds its own day filter, and the fix had not touched it.

Read it in this order:

1. `request.md`: the operations lead's message, as it arrived.
2. `questions.jsonl`: one question, asked because one answer was irreversible
   (splitting stored bookings into one record per day), and the owner's answer
   verbatim: keep one record, compute the overlap at query time, no migration.
3. `order.json`: kind fix; claims labelled and sourced; one assumption; four
   criteria, each at its hard case: a slot across midnight on both days, a
   slot ending exactly at midnight on its first day only, a single-day slot
   unaffected, and a cross-tenant negative.
4. `events.jsonl`: intake, the work order, leases taken and released, the
   implementer at the implemented rung, QC rejecting on the hosted journey,
   rework, QC passing, the release, the report. Event 18 corrects a wrong
   baseline value in the write-once work order, without touching it.
5. `evidence/`: both journey outputs, the failing one and the passing one,
   with fingerprints before and after.
6. `releases/2030-10-17-overnight-slots.md`: written before the cutover, with
   the rollback target taken from what was live rather than from the work
   order's stale baseline.

The report at event 22 was submitted twice: a retried session pasted it
again. The second submission carried the same idempotency key,
`report:TCC-142:live`, and the tool appended nothing.

## Limits, stated

- **The guard has a blind spot.** With no base commit (a first push, a new
  branch, a forced rewrite) it has nothing to compare and passes. Forced
  pushes are on the deny list, and you should protect the record's main
  branch, requiring the guard to pass before merge. Those cover the gap; the
  guard alone does not.
- **The lease errs toward not starting.** Any concurrent push to the record
  fails a claim, even one about another ticket. Fetch and retry.
- **The deny list is written in a neutral shape.** `agent-settings.json` lists
  command prefixes, or commands described in plain words, with the reason for
  each. `<app: ...>` describes, in plain words, an action of your
  application's own command-line entry point, and `<cluster>` stands for your
  cluster's command-line tool; translate each entry into your coding agent's
  own permission format. The same goes for where `render_agents.py` writes:
  point `--target` at the directory your agent reads definitions from.
- **Intent and enforcement are separate on purpose.** The role files cannot be
  enforced by a tool layer, and the grant file cannot express "never fix what
  you review". Neither is complete alone.

## Adopting it

Copy `bin/`, `tests/`, `roles/`, `PRACTICE.md`, `MANAGER.md` and the workflow
into a new record repository for the system you run. Delete `tickets/TCC-142`
and `releases/`, and the `WorkedExampleTests` group with them. Rewrite the
estate-specific parts of `PRACTICE.md`, `roles/security-gate.md` and
`agent-settings.json` for that system. Then render the agent definitions:

```sh
python3 bin/render_agents.py --target record=<record agent dir> --target product=<product agent dir>
```
