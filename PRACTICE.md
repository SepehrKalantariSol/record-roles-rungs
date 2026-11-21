# Practice

How work moves through this record, and why each rule exists. It binds every
role, the main manager included.

**Precedence, stated once.** The product repository's own AGENTS.md wins on
facts about that codebase: how its tests run, where things live, what a module
is for. This file wins on process: who does what, in what order, and what
counts as done. An owner's instruction written into the ticket overrides both.

In the system this was extracted from, every rule cited the incident that
produced it. Here, two incidents are told in full (§8 and §9) and the other
rules carry their reasoning instead.

---

## 1 · The record

The record is a git repository with one directory per ticket. README.md shows
the layout and the four invariants. What follows is how to use it.

- **Split at intake.** One ticket per outcome that a person could accept or
  reject on its own. *"The export leaves out cancelled bookings, and the door
  board is slow after six"* is two tickets, because either could be fixed and
  accepted without the other.
- **The request is kept verbatim**, with where it came from and when. Not
  tidied, not altered, not summarised. Attachments are copied into evidence
  at intake, because a screenshot in a chat thread is not there when someone
  needs it a month later.
- **The reading is kept apart from the words.** The work order is the project
  manager's reading of the request. When a reading turns out wrong, the
  verbatim text is still there to read again, and the fix is a new event that
  cites it. Nothing is rewritten to look as if it had been right all along.
- **The record is the memory.** A fresh session with no context runs
  `record.py status` and resumes where a dead session stopped. If something
  matters and it is not in the record, it did not happen.
- **References, not content.** An event points at a commit, an image or a file
  under evidence. Logs, screenshots and output live in evidence; the event
  says where.
- **The record is guarded.** `bin/guard.py` runs in CI on every push and pull
  request, and fails any change that edits, reorders, truncates or deletes an
  append-only log, or touches a write-once file. When there is no base to
  compare with (a first push, a new branch, a forced rewrite) it has nothing
  to check, and passes. That gap is closed by two things outside it: forced
  pushes are on the deny list, and the record's main branch is protected.

## 2 · One write path

Every write to a ticket goes through `bin/record.py`. Not because agents are
careless, but because a rule that depends on everyone remembering it is a
rule that holds until the first busy afternoon. The tool refuses the known
failure modes:

- an empty request, since the raw text is the one thing that must be kept;
- a second work order, with a message saying to append a correction instead;
- a stage or a decision outside the fixed vocabularies (decisions are `pass`,
  `reject`, `blocked` and `note`);
- an event whose `idempotency_key` is already in the log. The tool says which
  entry holds it and appends nothing, so a report pasted twice is one event;
- a reference longer than the cap, so content cannot travel as a "reference";
- anything shaped like a secret in a note or a reference: a private-key
  header, an assignment to a password, secret, token or key, or a URL with
  credentials in it. A secret never enters the record, for any reason;
- a blocked decision that does not say what it is blocked on;
- a log line that is not valid JSON. The tool stops rather than guess.

Every event carries `read_from`: the entry its actor read before acting,
defaulting to the last. Status flags any event whose actor read an entry older
than another actor's latest work. A stage that acted on stale input shows up
as stale, instead of looking like a disagreement.

**Status is never stored.** It is derived from the last event that is not a
lease event: passed at a stage; rejected at a stage, so back to the actor
before it; blocked in a stage, on a named thing; or a note recorded, stage not
finished. A stored status is a second copy of the truth, and the two copies
will disagree.

The sequence number is the count plus one. The tool does not stop two writers
appending at once; the lease does.

## 3 · The lease

Before taking a stage on a ticket, an agent runs `record.py claim`. The tool
writes `lease.json` in the ticket (holder, stage, time taken, expiry, two hours
by default), commits it with a lease event, and pushes.

- **If the push is rejected, the claim fails.** The tool undoes the local
  commit, restores the files, and reports "held, do not start". The remote's
  refusal to accept a non-fast-forward push is the lock. There is no lock
  server, because git already has the one property a lock needs.
- An unexpired lease is refused by name: who holds it, until when.
- An expired lease may be taken over, and the takeover event names the
  previous holder.
- `record.py release` removes the file in a commit, and pushes.
- Times are fixed-format UTC (`2030-10-15T08:30:00Z`), so they compare
  correctly as text.
- The main manager reads the lease before dispatching anyone to a stage.

**Its honest edge.** Any concurrent push to the record makes a claim fail,
including a push about a different ticket. The failure is therefore in the
direction of not starting, which is the safe one. Retry: fetch, then claim
again.

## 4 · Roles, grants and the deny list

Each role in `roles/` is one file: what it reads, what it produces, and what
it **must not do**. The last part matters most. A role changes only through a
pull request. The main manager composes roles for a ticket but never defines
one, and no agent grants itself a tool.

The "must not" lines are intent, and intent is not enforcement.
`roles/toolbelt.json` maps each role to the tools it may use, which is the
part a tool layer can enforce, but a grant list cannot express "never fix what
you are reviewing". Neither is complete alone, so both exist.
`bin/render_agents.py` joins each role file with its grants into an agent
definition, stamps it "generated, edit the source instead", and writes it into
each repository that needs it: the record and the product repository. One
definition, many repositories, no drift between copies.

Behind both sits a deny list, `agent-settings.json`: commands no role may run
whatever its instructions say. Forced pushes. Staging everything at once.
Changing the schema outside the migration stage (§9). Changing the cluster
directly: even the deployer changes the cluster only by committing to the
configuration repository, and a hand change is the owner's.

## 5 · The work order

The project manager writes the work order into the record, through
`record.py order`, before any work starts. A work order discussed in chat and
never written down does not exist. It is written once; afterwards it is
corrected only by events.

### Fields

| field | holds |
|---|---|
| `request_ref` | the verbatim request it reads |
| `resolved_intent` | the intent, in one sentence |
| `grounding` | each factual claim, with a label and a source |
| `assumptions_taken` | what was assumed without asking; each one reappears in the final report |
| `surfaces` | every place the change has to land |
| `acceptance` | the criteria, each with its `hard_case` |
| `kind` | fix, build, investigate or scenario |
| `stages_required` | the stages, in order |
| `baseline` | measured now: `deployed_image`, `served` (what the live host actually serves), `migration_state` |
| `schema_change` | true or false |

**Surfaces are where a change hides.** A change to how bookings are assigned
to days lands in the day query, the dispatcher's list, the shift lead's
schedule, the day export, and the fixtures that test them, and any of those
may decide the day for itself. A new booking field lands in the form, the
validation, the door board, the delivery document and the export. List them
all, or one of them ships unchanged.

### Claim labels

Every claim in `grounding` carries one of four labels:

- `verified`, with its source: the file and line, or the command and its output;
- `assumed`, with why the assumption is reasonable;
- `unknown`, with what it would take to find out;
- `ruling-needed`: a decision only a person can make, which becomes a question.

"Unknown" is an acceptable answer. A confident wrong one is not.

### Grounding

- Measure the deployed state fresh, every time. Never quote an earlier report.
- Documents go stale. When a document and a measurement disagree, the
  measurement is `verified` and the document is `unknown` until someone
  reconciles them.
- Find the authority in the code: where the value is actually decided, not
  where you remember it being decided.
- A human answer is recorded verbatim, with who said it and when.

### The four kinds

The kind decides what a work order even is.

- **Fix.** Criteria come before code, each at its hard case. The fix is
  assumed and proceeds; questions only at the threshold below.
- **Build.** Confirm the shape before building, in one message rather than a
  meeting: the surfaces, the states, which roles see it, and what it does when
  it is empty or the input is wrong. Split it if it has more than one outcome
  a person could accept or reject on its own.
- **Investigate.** **No acceptance criteria**, because writing criteria for an
  investigation invents an answer nobody has yet. The output is findings, each
  labelled with how it was observed. The work is read-only. A finding that
  needs work becomes its own ticket. "Nothing found" is a result.
- **Scenario.** Walk named paths **as a named product role**, against the
  deployment, in a real browser. The output is a table of pass, fail or
  blocked that records what was observed, not what was concluded. A site
  administrator reading a carrier's bookings proves nothing about what that
  carrier's dispatcher can reach. Each failure becomes a ticket; the sweep
  itself fixes nothing.

### Every criterion names the hard case

A test that only ever meets the easy input passes while the feature is broken.
Five classes come up again and again:

1. **Awkward input at a boundary, when every fixture sat in the easy middle
   of its range.** Door 9 is booked 05:00 to 06:00 by one carrier and 06:00 to
   07:00 by another. The clash check must accept both, because a slot is
   half-open and the first one leaves the door free at 06:00, and must still
   refuse a third booking from 05:30 to 06:30.
2. **The second visit, when every test started from an empty database.** A
   dispatcher who books door 6 for 06:00, cancels, and books it again must not
   collide with the cancelled booking's row, which a fresh database never has.
3. **The broken asset that passes a visibility check.** The delivery-document
   link is present and returns success, and the PDF behind it has zero pages
   and is a few hundred bytes. Measure the thing itself: page count at least
   one, size above a floor, the booking reference in its text.
4. **The rendered value against the declared constant.** The rule says door
   numbers on the door board render at least 1.5 times body size, and the
   constant says so. A later rule for compact rows overrides it on the element.
   Measure the computed size on the element, in the browser.
5. **The user who is not the owner.** Signed in as a dispatcher at one
   carrier, request another carrier's delivery document by its direct
   address. Expect not-found, and nothing in the response that names the other
   carrier. Every tenant-scoped change carries a cross-tenant negative test.

### When to stop and ask

Three layers: resolve it from the repository; ask the requester; escalate to
the owner. **The threshold is reversibility, not uncertainty.** Stop only when:

- the decision cannot be cheaply undone: a data migration, a permission
  change, a project setting;
- two readings lead to materially different work; or
- the request contradicts something already approved.

Otherwise take the most reasonable reading, record it in `assumptions_taken`,
carry on, and surface it in the report. Review happens after the work, not in
front of it. An engagement where every doubt becomes a question is one where
nothing moves until the owner is free.

## 6 · Rungs, and the hosted journey

**The rungs.**

1. **Implemented**: code and tests written, local checks pass.
2. **Deployed**: live, with the version recorded.
3. **Verified**: the hosted journey passed against that deployment.
4. **Client-confirmed.**

A change ticket closes at verified; if confirmation later finds something
wrong, it reopens. An investigation or scenario ticket closes when its
findings or its table are in the record and every ticket it raised exists.

**A report names the rung it reached, and never a higher one.** "It builds" is
not a rung. Silence about what was not verified is read as "verified", so it
has to be said.

**The hosted journey** is QC's required check, every time: a real browser
against the deployed host, signed in as the role each criterion is about. It
takes a fingerprint before and after: table count, row count, a content
digest, migration state, and stored-object count and digest. Then it compares
the two. That one check observes real composition, auth and cookies, the
deployed clock and real time boundaries, content security policy, storage,
actual rendering, and any residue the test itself left behind.

None of these substitutes for it:

- a passing build;
- a visibility assertion on an asset;
- a unit test that reads a declared constant;
- a test that starts from a fresh database;
- a green health probe, or a process that is running.

Each of them is green in the most common failure there is: fine locally,
broken on the deployment. The worked example in `tickets/TCC-142/` is that
failure, caught by this check.

## 7 · Design rules are measured, not invented

The design gate checks rules, not taste, and its rules carry numbers, so the
numbers have to come from somewhere other than preference.

They came from measuring a reference site, chosen by the owner, in a real
browser at a phone width (390 px) and a desktop width (1440 px). The rules
adopt **ratios**, not the reference's absolute values: heading to body size,
the gap between sections against body line height, the minimum tap target.
Every number cites the
measurement it came from. Whatever the measurement could not establish is
labelled unknown, not guessed. Illustratively:

| rule | value | from |
|---|---|---|
| page heading : body size | 1.8 at phone width, 2.4 at desktop | measure/phone-type, measure/desktop-type |
| section gap : body line height | 3.0 | measure/phone-rhythm |
| tap target, smallest side | 44 px | measure/phone-targets |
| body line length | unknown | the reference's text columns were too short to tell |

The gate and the tests compare **rendered** values on the live page with these
rules: the computed size of the element, not the constant in the stylesheet.

## 8 · Automation owns only what it created

The nightly scenario sweep books slots as a test carrier and walks the dock
clerk's check-in screen. One night it booked six slots on doors 14 to 17
between 05:00 and 07:00 the next morning, walked them, and then cleaned up by
cancelling every booking on doors 14 to 17 in that window. Two real carriers
had booked those doors for that morning, and their nine bookings went with the
sweep's six. The sweep reported success, because by its own account it had
removed the bookings it made. What disagreed was the fingerprint, which
counted fifteen cancellations where the sweep had created six; a shift lead's
message about two carriers arriving to cancelled slots came in shortly after.
The nine were restored from the dump taken with the fingerprint.

**The rule.** Anything that deletes, cancels or changes data targets only
records it created, identified by something it owns.

- Each run mints its own mark (`jt-heron-02` in the example), writes it into
  every record it creates, and cleans up by that mark and nothing else.
- Cleanup by a shared prefix, a date range, a door range or a status is not
  allowed, however narrow it looks. Real data shares attributes; it never
  shares your run's mark.
- Seeds are idempotent: run twice, they leave the same state as once.
- A fingerprint is taken before any milestone, so damage is detectable and
  repairable.

This applies to agents as much as to scripts. An agent tidying up after itself
is a cleanup job with better manners and the same blast radius.

## 9 · A rollback is not finished until the re-promoter is dealt with

A release added notes to dock doors. The shift lead's door board and the
carrier's booking page both read a new column, and the migration that adds it
had been queued to run after the cutover instead of before. For the minutes in
between, both pages failed with a server error, while the health probe, which
opens a database connection and reads nothing new, stayed green, and the
rollout was declared healthy. The deployer cancelled the pending migration and
rolled the cluster back by hand to the previous image, correctly. The pages
recovered and the rollback was verified. Forty minutes later, a commit to the
configuration repository that corrected one sentence in its README triggered a
sync. The GitOps controller applied the head of the repository, which still
named the new image, and the door board failed again, this time with no
migration coming at all. Nothing about a documentation commit looks like a
deploy, and the rollback had already been checked.

**The rule.** A rollback is not finished until whatever would re-promote the
bad build has been dealt with. Here that means a revert commit in the
configuration repository, so that its head names the good image, or auto-sync
paused, recorded in the release record with who resumes it. The usual
rollback is the revert itself; a hand change to the cluster is the owner's,
and pauses auto-sync first.

**Schema first, then code.** The migration is its own stage because its order
relative to the cutover is a correctness property, not a preference. Code
shipped ahead of its migration fails misleadingly: the pages that read the new
column break, and the health probe, which reads nothing new, stays green. A
migration ships before the code that needs it, and must leave the schema
usable by the code still running, so that the old image survives the new
schema for as long as a rollback might need it.

**The release record** exists before the deployment, in `releases/`. It names:

- the tickets shipped;
- the image reference, and that it is the image QC tested;
- which migration ran and when, relative to the cutover;
- the rollback target, measured from what is live, not taken from a document;
- **what would undo the rollback**, and how the rollback avoids it;
- where the pre-release dump is;
- after the cutover, the hosted journey's result and the rung reached.

The deployer refuses to cut over if no rollback target can be named.
