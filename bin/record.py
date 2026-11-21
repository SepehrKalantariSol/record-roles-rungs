#!/usr/bin/env python3
"""record.py: the one write path into the record.

    intake    take in a request, verbatim
    order     place the work order (written once)
    append    append an event to a ticket's log
    ask       open a question
    answer    record a person's answer, verbatim
    status    show the state derived from the log
    claim     take the lease on a stage (commits and pushes)
    release   give the lease back (commits and pushes)

Standard library only. Every subcommand except claim and release writes files
and stops; committing them is the caller's job, path by path. Claim and release
commit and push for themselves, because for a lease the push is the point.

Run `python3 bin/record.py <command> --help` for the arguments.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STAGES = ("intake", "order", "implement", "migrate", "design", "security",
          "qc", "release", "report", "lease")
DECISIONS = ("pass", "reject", "blocked", "note")
RUNGS = ("implemented", "deployed", "verified", "confirmed")
KINDS = ("fix", "build", "investigate", "scenario")
LABELS = ("verified", "assumed", "unknown", "ruling-needed")
AGENT_ROLES = ("main-manager", "project-manager", "implementer", "qc",
               "design-gate", "security-gate", "deployer")
ORDER_FIELDS = ("request_ref", "kind", "resolved_intent", "grounding",
                "assumptions_taken", "surfaces", "acceptance",
                "stages_required", "baseline", "schema_change")
BASELINE_FIELDS = ("deployed_image", "served", "migration_state")

REF_MAX = 200        # a reference points at something; it never carries it
NOTE_MAX = 600
SOURCE_MAX = 120
LEASE_HOURS = 2.0
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"   # fixed-width UTC, so text order is time order
TICKET_ID = re.compile(r"^[A-Z]+-[0-9]+$")
LEASE = "lease.json"
LOG = "events.jsonl"
QUESTIONS = "questions.jsonl"

# Generic secret shapes, no product-specific names. The key-header pattern is
# assembled from pieces so that this file does not itself contain a key header
# for secret scanners to trip on.
SECRET_SHAPES = (
    ("a private key header",
     re.compile("-----BEGIN " + "[A-Z0-9 ]*" + "PRIVATE" + " KEY")),
    ("a credential assignment",
     re.compile(r"(?i)[a-z0-9_.-]*(?:password|passwd|passphrase|secret|token"
                r"|api[_-]?key|access[_-]?key|private[_-]?key|credentials?)"
                r"[a-z0-9_.-]*\s*[:=]\s*\S")),
    ("a URL with embedded credentials",
     re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)),
)


class Refused(Exception):
    """The tool will not do this. The message says what to do instead."""


class Held(Refused):
    """Someone else holds the lease, or the push that would take it was refused."""


# ---------------------------------------------------------------- helpers

def utcnow():
    return datetime.now(timezone.utc).strftime(TIME_FORMAT)


def check_time(value, what):
    try:
        datetime.strptime(value, TIME_FORMAT)
    except (TypeError, ValueError):
        raise Refused(f"{what} must be UTC in the form 2030-10-14T08:47:00Z, "
                      f"not {value!r}")
    return value


def secret_shape(text):
    for name, pattern in SECRET_SHAPES:
        if pattern.search(text or ""):
            return name
    return None


def refuse_secrets(field, text):
    shape = secret_shape(text)
    if shape:
        raise Refused(f"the {field} contains {shape}. A secret never enters the "
                      "record, for any reason: reference where it is kept, "
                      "never the value.")


def ticket_dir(root, ticket, must_exist=True):
    if not TICKET_ID.match(ticket or ""):
        raise Refused(f"{ticket!r} is not a ticket id (expected e.g. TCC-142)")
    path = Path(root) / "tickets" / ticket
    if must_exist and not (path / LOG).exists():
        raise Refused(f"there is no ticket {ticket} under {Path(root) / 'tickets'}")
    return path


def rel(root, path):
    return Path(path).relative_to(Path(root)).as_posix()


def read_jsonl(path):
    entries = []
    if not path.exists():
        return entries
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            try:
                entry = json.loads(line)
            except ValueError:
                raise Refused(f"{path} line {number} is not valid JSON. Stopping "
                              "rather than guessing; restore the line from git.")
            if not isinstance(entry, dict):
                raise Refused(f"{path} line {number} is not a JSON object")
            entries.append(entry)
    return entries


def append_line(path, entry):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_events(tdir):
    events = read_jsonl(tdir / LOG)
    for index, event in enumerate(events, start=1):
        if event.get("seq") != index:
            raise Refused(f"{tdir / LOG}: entry {index} carries seq "
                          f"{event.get('seq')!r}, so the log has been edited")
    return events


# ---------------------------------------------------------------- events

def append_event(root, ticket, actor, stage, decision, key, ref="", note="",
                 read_from=None, blocked_on="", rung="", at=None):
    """Append one event. Returns (event, appended).

    The sequence number is the count plus one. Nothing here stops two writers
    from appending at once; exclusivity comes from the lease, not this tool.
    """
    tdir = ticket_dir(root, ticket)
    events = read_events(tdir)
    if not key:
        raise Refused("every event needs an idempotency key")
    for existing in events:
        if existing.get("idempotency_key") == key:
            return existing, False
    if not actor:
        raise Refused("every event names its actor")
    if stage not in STAGES:
        raise Refused(f"stage {stage!r} is not one of: {', '.join(STAGES)}")
    if decision not in DECISIONS:
        raise Refused(f"decision {decision!r} is not one of: {', '.join(DECISIONS)}")
    if rung and rung not in RUNGS:
        raise Refused(f"rung {rung!r} is not one of: {', '.join(RUNGS)}")
    if len(ref) > REF_MAX:
        raise Refused(f"the reference is {len(ref)} characters and the cap is "
                      f"{REF_MAX}. A reference points at a commit, an image or a "
                      "path under evidence: put the content there and point at it.")
    if len(note) > NOTE_MAX:
        raise Refused(f"the note is {len(note)} characters and the cap is "
                      f"{NOTE_MAX}. Put the detail in evidence and reference it.")
    for field, text in (("reference", ref), ("note", note), ("blocked_on", blocked_on)):
        refuse_secrets(field, text)
    if decision == "blocked" and not blocked_on.strip():
        raise Refused("a blocked decision must say what it is blocked on (--blocked-on)")
    if read_from is None:
        read_from = len(events)
    if not 0 <= read_from <= len(events):
        raise Refused(f"read_from {read_from} does not exist: the log has "
                      f"{len(events)} entries")
    event = {"seq": len(events) + 1,
             "at": check_time(at, "at") if at else utcnow(),
             "actor": actor, "stage": stage, "decision": decision}
    if rung:
        event["rung"] = rung
    if blocked_on:
        event["blocked_on"] = blocked_on
    event.update(ref=ref, note=note, read_from=read_from, idempotency_key=key)
    append_line(tdir / LOG, event)
    return event, True


# ---------------------------------------------------------------- intake

def intake(root, ticket, text, source, received, attachments=(), actor="main-manager"):
    if not (text or "").strip():
        raise Refused("the request is empty. The raw text is the one thing that "
                      "must be kept: take it in exactly as it arrived.")
    if not (source or "").strip() or len(source) > SOURCE_MAX:
        raise Refused(f"say where the request came from, in at most {SOURCE_MAX} "
                      "characters (--source)")
    check_time(received, "received")
    refuse_secrets("source", source)
    shape = secret_shape(text)
    if shape:
        raise Refused(f"the request contains {shape}. A secret never enters the "
                      "record. Ask the sender to rotate it, and take the request "
                      "in with that value replaced by [withheld].")
    tdir = ticket_dir(root, ticket, must_exist=False)
    if tdir.exists():
        raise Refused(f"{ticket} already exists. A request is written once; a "
                      "second request is a second ticket.")
    files = [Path(item) for item in attachments]
    missing = [str(item) for item in files if not item.is_file()]
    if missing:
        raise Refused(f"attachment not found: {', '.join(missing)}")

    evidence = tdir / "evidence"
    evidence.mkdir(parents=True)
    kept = []
    if files:
        target = evidence / f"{received[:10]}-intake"
        target.mkdir()
        for item in files:
            shutil.copy2(str(item), str(target / item.name))
            kept.append(rel(root, target / item.name))

    body = text if text.endswith("\n") else text + "\n"
    fence = "~~~"
    while fence in body:
        fence += "~"
    header = [f"# {ticket}: request", "",
              f"source    {source}",
              f"received  {received}"]
    header += [f"attached  {path}" for path in kept]
    header += ["",
               "Kept exactly as it arrived. It is never tidied, altered or summarised;",
               "readings of it belong in order.json.",
               ""]
    (tdir / "request.md").write_text("\n".join(header) + "\n" + f"{fence}text\n"
                                     + body + f"{fence}\n", encoding="utf-8")
    (tdir / QUESTIONS).write_text("", encoding="utf-8")
    (tdir / LOG).write_text("", encoding="utf-8")
    event, _ = append_event(root, ticket, actor, "intake", "pass",
                            key=f"intake:{ticket}",
                            ref=rel(root, tdir / "request.md"),
                            note=f"from {source}")
    return event


# ---------------------------------------------------------------- work order

def validate_order(order):
    if not isinstance(order, dict):
        raise Refused("a work order is a JSON object")
    missing = [field for field in ORDER_FIELDS if field not in order]
    if missing:
        raise Refused(f"the work order is missing: {', '.join(missing)}")
    kind = order["kind"]
    if kind not in KINDS:
        raise Refused(f"kind {kind!r} is not one of: {', '.join(KINDS)}")
    if not str(order["resolved_intent"]).strip():
        raise Refused("resolved_intent is the intent in one sentence; it is empty")
    if not isinstance(order["grounding"], list):
        raise Refused("grounding is a list of claims")
    for claim in order["grounding"]:
        if not isinstance(claim, dict) or not claim.get("claim"):
            raise Refused("each grounding entry needs a claim")
        if claim.get("label") not in LABELS:
            raise Refused(f"claim {claim['claim']!r}: the label must be one of "
                          f"{', '.join(LABELS)}")
        if claim["label"] == "verified" and not claim.get("source"):
            raise Refused(f"claim {claim['claim']!r} is labelled verified but names "
                          "no source: the file and line, or the command output")
    acceptance = order["acceptance"]
    if kind == "investigate":
        if acceptance:
            raise Refused("an investigation has no acceptance criteria: writing them "
                          "invents an answer nobody has yet. Leave acceptance empty; "
                          "the output is findings.")
    else:
        if not acceptance:
            raise Refused(f"a {kind} needs acceptance criteria")
        for item in acceptance:
            if not isinstance(item, dict) or not item.get("criterion") \
                    or not item.get("hard_case"):
                raise Refused("every criterion names its hard case: give each one "
                              "a criterion and a hard_case")
    stages = order["stages_required"]
    if not isinstance(stages, list):
        raise Refused("stages_required is a list")
    unknown = [stage for stage in stages if stage not in STAGES]
    if unknown:
        raise Refused(f"unknown stages: {', '.join(map(str, unknown))}")
    if kind in ("fix", "build") and "qc" not in stages:
        raise Refused("nothing skips QC: add qc to stages_required")
    if not isinstance(order["schema_change"], bool):
        raise Refused("schema_change is true or false")
    if order["schema_change"]:
        if "migrate" not in stages:
            raise Refused("a schema change needs the migrate stage")
        if "release" in stages and stages.index("migrate") > stages.index("release"):
            raise Refused("schema first, then code: migrate comes before release")
    baseline = order["baseline"]
    if not isinstance(baseline, dict) or any(not baseline.get(f) for f in BASELINE_FIELDS):
        raise Refused(f"the baseline needs {', '.join(BASELINE_FIELDS)}, measured now")
    refuse_secrets("work order", json.dumps(order, ensure_ascii=False))


def place_order(root, ticket, order, actor="project-manager"):
    tdir = ticket_dir(root, ticket)
    path = tdir / "order.json"
    if path.exists():
        raise Refused(f"{ticket} already has a work order, and a work order is "
                      "written once. Record the correction as an event instead: "
                      f"record.py append {ticket} --actor project-manager --stage "
                      "order --decision note --key <new key> "
                      "--note 'correction to <field>: <what was measured>'")
    validate_order(order)
    path.write_text(json.dumps(order, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    event, _ = append_event(root, ticket, actor, "order", "pass",
                            key=f"order:{ticket}", ref=rel(root, path),
                            note=f"kind {order['kind']}; stages "
                                 f"{', '.join(order['stages_required'])}")
    return event


# ---------------------------------------------------------------- questions

def questions_state(tdir):
    entries = read_jsonl(tdir / QUESTIONS)
    asked = [entry["id"] for entry in entries if "id" in entry]
    answered = {entry["answers"] for entry in entries if "answers" in entry}
    return asked, [qid for qid in asked if qid not in answered]


def ask(root, ticket, by, to, text, why=""):
    tdir = ticket_dir(root, ticket)
    if not (text or "").strip():
        raise Refused("the question is empty")
    refuse_secrets("question", text)
    asked, _ = questions_state(tdir)
    entry = {"id": f"Q{len(asked) + 1}", "asked_by": by, "asked_at": utcnow(),
             "to": to, "why": why, "text": text}
    append_line(tdir / QUESTIONS, entry)
    return entry


def answer(root, ticket, qid, by, verbatim, at=None):
    if by in AGENT_ROLES:
        raise Refused(f"{by} is an agent, and an agent never closes a question by "
                      "choosing an answer. Record what the person said, and who.")
    if not (verbatim or "").strip():
        raise Refused("the answer is empty; record the person's words verbatim")
    refuse_secrets("answer", verbatim)
    tdir = ticket_dir(root, ticket)
    asked, still_open = questions_state(tdir)
    if qid not in asked:
        raise Refused(f"{ticket} has no question {qid}")
    if qid not in still_open:
        raise Refused(f"{qid} is already answered. A changed answer is a new "
                      "question, asked again.")
    entry = {"answers": qid, "answered_by": by,
             "answered_at": check_time(at, "at") if at else utcnow(),
             "verbatim": verbatim}
    append_line(tdir / QUESTIONS, entry)
    return entry


# ---------------------------------------------------------------- status

def describe(work):
    if not work:
        return "nothing recorded"
    last = work[-1]
    stage, decision, seq = last["stage"], last["decision"], last["seq"]
    if decision == "pass":
        return f"passed {stage} (#{seq}, {last['actor']})"
    if decision == "reject":
        earlier = [e for e in work[:-1] if e["actor"] != last["actor"]]
        back_to = earlier[-1]["actor"] if earlier else "the previous actor"
        return f"rejected at {stage} (#{seq}): back to {back_to}"
    if decision == "blocked":
        return f"blocked in {stage} (#{seq}) on: {last.get('blocked_on', '?')}"
    return f"note recorded in {stage} (#{seq}); {stage} not finished"


def rung_of(work):
    reached = None
    for event in work:
        if event.get("rung"):
            reached = (event["rung"], event["seq"])
        elif event["decision"] == "reject":
            reached = None
    return f"{reached[0]} (#{reached[1]})" if reached else "none"


def stale_reads(work):
    """An actor that read an entry older than another actor's latest work."""
    warnings = []
    for index, event in enumerate(work):
        others = [e for e in work[:index] if e["actor"] != event["actor"]]
        if others and event.get("read_from", 0) < others[-1]["seq"]:
            warnings.append(f"#{event['seq']} ({event['actor']}) read "
                            f"#{event.get('read_from')}, but #{others[-1]['seq']} "
                            f"({others[-1]['actor']}) came after it")
    return warnings


def read_lease(tdir):
    path = tdir / LEASE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise Refused(f"{path} is not valid JSON")


def status(root, ticket):
    """Derived from the log and the lease only. Status is never written down."""
    tdir = ticket_dir(root, ticket)
    events = read_events(tdir)
    # Lease events are bookkeeping about who may act, not progress of the work.
    work = [e for e in events if e.get("stage") != "lease"]
    order_path = tdir / "order.json"
    if order_path.exists():
        order = json.loads(order_path.read_text(encoding="utf-8"))
        kind = f"{order.get('kind')}: {order.get('resolved_intent')}"
    else:
        kind = "no work order yet"
    lease = read_lease(tdir)
    if lease:
        lease_text = (f"{lease.get('holder')} on {lease.get('stage')} "
                      f"until {lease.get('expires_at')}")
        if lease.get("expires_at", "") <= utcnow():
            lease_text += " (expired: may be taken over)"
    else:
        lease_text = "none"
    asked, still_open = questions_state(tdir)
    questions = f"{len(still_open)} open of {len(asked)}"
    if still_open:
        questions += ": " + ", ".join(still_open)
    rows = [("kind", kind), ("state", describe(work)), ("rung", rung_of(work)),
            ("lease", lease_text), ("questions", questions)]
    rows += [("stale", warning) for warning in stale_reads(work)]
    if events:
        last = events[-1]
        rows.append(("last", f"#{last['seq']} {last.get('at')} {last.get('actor')} "
                             f"{last.get('stage')} {last.get('decision')}"))
    return "\n".join([ticket] + [f"  {name:<10} {value}" for name, value in rows])


# ---------------------------------------------------------------- lease

def git(root, *args):
    return subprocess.run(["git", "-C", str(root)] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)


def require_clean_index(root):
    result = git(root, "diff", "--cached", "--quiet")
    if result.returncode == 1:
        raise Refused("the index already holds staged changes, and a lease commit "
                      "must contain only the lease. Commit or unstage them first.")
    if result.returncode != 0:
        raise Refused(f"{root} is not a git repository; a lease needs a record "
                      "with a remote to push to")


def snapshot(tdir):
    return {name: (tdir / name).read_bytes() if (tdir / name).exists() else None
            for name in (LEASE, LOG)}


def restore(tdir, saved):
    for name, data in saved.items():
        path = tdir / name
        if data is None:
            if path.exists():
                path.unlink()
        else:
            path.write_bytes(data)


def publish(root, tdir, saved, message, refused):
    """Stage the lease and the log, commit, push. The remote's refusal of a
    non-fast-forward push is the lock: if it refuses, undo the local commit."""
    lease_rel, log_rel = rel(root, tdir / LEASE), rel(root, tdir / LOG)
    if (tdir / LEASE).exists():
        steps = [["add", "--", lease_rel]]
    else:
        steps = [["rm", "-q", "--cached", "--ignore-unmatch", "--", lease_rel]]
    steps.append(["add", "--", log_rel])
    steps.append(["commit", "-q", "-m", message])
    for step in steps:
        result = git(root, *step)
        if result.returncode != 0:
            git(root, "reset", "-q", "--", lease_rel, log_rel)
            restore(tdir, saved)
            raise Refused(f"git {step[0]} failed: "
                          f"{(result.stderr or result.stdout).strip()}")
    if git(root, "push", "-q").returncode != 0:
        git(root, "reset", "-q", "HEAD~1")
        restore(tdir, saved)
        raise Held(refused)


def claim(root, ticket, holder, stage, hours=LEASE_HOURS):
    tdir = ticket_dir(root, ticket)
    if stage not in STAGES or stage in ("intake", "lease"):
        raise Refused(f"no lease is taken on stage {stage!r}")
    if not holder:
        raise Refused("a lease names its holder")
    require_clean_index(root)
    now = utcnow()
    current = read_lease(tdir)
    takeover = ""
    if current:
        if current.get("expires_at", "") > now:
            raise Held(f"held by {current.get('holder')} on {current.get('stage')} "
                       f"until {current.get('expires_at')}: do not start")
        takeover = (f"; took over from {current.get('holder')}, whose lease "
                    f"expired {current.get('expires_at')}")
    expires = (datetime.strptime(now, TIME_FORMAT)
               + timedelta(hours=hours)).strftime(TIME_FORMAT)
    saved = snapshot(tdir)
    lease = {"holder": holder, "stage": stage, "taken_at": now, "expires_at": expires}
    (tdir / LEASE).write_text(json.dumps(lease, indent=2) + "\n", encoding="utf-8")
    note = f"take {stage}: {holder} until {expires}{takeover}"
    append_event(root, ticket, holder, "lease", "note",
                 key=f"lease:{ticket}:{stage}:take:{holder}:{now}",
                 ref=rel(root, tdir / LEASE), note=note)
    publish(root, tdir, saved, f"{ticket}: lease {stage} to {holder}",
            refused="the push was refused: held, do not start. Someone else "
                    "pushed to the record first (perhaps about another ticket), "
                    "or the remote could not be reached. Fetch, then try again.")
    return note


def release(root, ticket, holder):
    tdir = ticket_dir(root, ticket)
    current = read_lease(tdir)
    if not current:
        raise Refused(f"{ticket} has no lease to release")
    if current.get("holder") != holder:
        raise Refused(f"the lease belongs to {current.get('holder')}, and only its "
                      "holder releases it. An expired lease is taken over with "
                      "claim, not released by someone else.")
    require_clean_index(root)
    stage = current.get("stage")
    now = utcnow()
    saved = snapshot(tdir)
    (tdir / LEASE).unlink()
    note = f"release {stage}: {holder}"
    append_event(root, ticket, holder, "lease", "note",
                 key=f"lease:{ticket}:{stage}:release:{holder}:{now}",
                 ref=rel(root, tdir / LEASE), note=note)
    publish(root, tdir, saved, f"{ticket}: release lease on {stage}",
            refused="the push was refused, so the lease is still held on the "
                    "remote. Fetch, then release again.")
    return note


# ---------------------------------------------------------------- command line

def build_parser():
    parser = argparse.ArgumentParser(prog="record.py",
                                     description="The one write path into the record.")
    parser.add_argument("--root", default=str(ROOT),
                        help="the record repository (default: the one holding this tool)")
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p = sub.add_parser("intake", help="take in a request, verbatim")
    p.add_argument("ticket")
    p.add_argument("--source", required=True, help="where it came from, e.g. 'shared inbox'")
    p.add_argument("--received", required=True, help="UTC, e.g. 2030-10-14T08:47:00Z")
    p.add_argument("--text-file", help="file holding the request (default: standard input)")
    p.add_argument("--attach", action="append", default=[],
                   help="a file to copy into evidence now (repeatable)")
    p.add_argument("--actor", default="main-manager")

    p = sub.add_parser("order", help="place the work order, once")
    p.add_argument("ticket")
    p.add_argument("--file", required=True, help="the work order as JSON")
    p.add_argument("--actor", default="project-manager")

    p = sub.add_parser("append", help="append an event")
    p.add_argument("ticket")
    p.add_argument("--actor", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--decision", required=True)
    p.add_argument("--key", required=True,
                   help="idempotency key: the same report twice is one event")
    p.add_argument("--ref", default="", help="a commit, an image or a path under evidence")
    p.add_argument("--note", default="")
    p.add_argument("--blocked-on", default="")
    p.add_argument("--rung", default="")
    p.add_argument("--read-from", type=int,
                   help="the entry you read before acting (default: the last)")

    p = sub.add_parser("ask", help="open a question")
    p.add_argument("ticket")
    p.add_argument("--by", required=True)
    p.add_argument("--to", required=True, help="requester or owner")
    p.add_argument("--text", required=True)
    p.add_argument("--why", default="", help="e.g. irreversible")

    p = sub.add_parser("answer", help="record a person's answer, verbatim")
    p.add_argument("ticket")
    p.add_argument("question", help="e.g. Q1")
    p.add_argument("--by", required=True, help="the person, by role")
    p.add_argument("--text", required=True, help="their words, verbatim")
    p.add_argument("--at", help="when they said it, UTC (default: now)")

    p = sub.add_parser("status", help="show the state derived from the log")
    p.add_argument("ticket")

    p = sub.add_parser("claim", help="take the lease on a stage (commits and pushes)")
    p.add_argument("ticket")
    p.add_argument("--holder", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--hours", type=float, default=LEASE_HOURS)

    p = sub.add_parser("release", help="give the lease back (commits and pushes)")
    p.add_argument("ticket")
    p.add_argument("--holder", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    try:
        if args.command == "intake":
            if args.text_file:
                text = Path(args.text_file).read_text(encoding="utf-8")
            else:
                text = sys.stdin.read()
            event = intake(root, args.ticket, text, args.source, args.received,
                           args.attach, args.actor)
            print(f"{args.ticket}: taken in as #{event['seq']}")
        elif args.command == "order":
            try:
                order = json.loads(Path(args.file).read_text(encoding="utf-8"))
            except ValueError as error:
                raise Refused(f"{args.file} is not valid JSON: {error}")
            event = place_order(root, args.ticket, order, args.actor)
            print(f"{args.ticket}: work order placed as #{event['seq']}")
        elif args.command == "append":
            event, appended = append_event(
                root, args.ticket, args.actor, args.stage, args.decision, args.key,
                ref=args.ref, note=args.note, read_from=args.read_from,
                blocked_on=args.blocked_on, rung=args.rung)
            if appended:
                print(f"{args.ticket}: #{event['seq']} {event['stage']} {event['decision']}")
            else:
                print(f"{args.ticket}: already recorded as #{event['seq']} under key "
                      f"{args.key!r}; nothing appended")
        elif args.command == "ask":
            entry = ask(root, args.ticket, args.by, args.to, args.text, args.why)
            print(f"{args.ticket}: asked {entry['id']}")
        elif args.command == "answer":
            answer(root, args.ticket, args.question, args.by, args.text, args.at)
            print(f"{args.ticket}: {args.question} answered by {args.by}")
        elif args.command == "status":
            print(status(root, args.ticket))
        elif args.command == "claim":
            print(f"{args.ticket}: {claim(root, args.ticket, args.holder, args.stage, args.hours)}")
        elif args.command == "release":
            print(f"{args.ticket}: {release(root, args.ticket, args.holder)}")
    except Held as error:
        print(str(error), file=sys.stderr)
        return 3
    except Refused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
