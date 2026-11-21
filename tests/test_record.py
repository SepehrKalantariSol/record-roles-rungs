"""Tests for the record tool and the guard.

    python3 -m unittest discover -s tests -v

Each test proves one refusal or one invariant. Without them, the invariants in
PRACTICE.md are only claims. The lease tests build a real remote and two
clones in a temporary directory, with git's global configuration isolated.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

import guard   # noqa: E402
import record  # noqa: E402

TICKET = "TCC-101"
REQUEST = ("The door board shows door 7 as free while a truck is still "
           "unloading at it.\n")

# Secret-shaped inputs are assembled at run time, so that this file does not
# itself carry anything a secret scanner should stop on. None is a real value.
SECRET_SHAPED = (
    "api_" + "token" + "=" + "<placeholder>",
    "-----BEGIN " + "PRIVATE" + " KEY-----",
    "https://" + "deploy:<placeholder>" + "@" + "files.tollaven.example/dumps",
)


def make_ticket(root, ticket=TICKET):
    record.intake(root, ticket, REQUEST, "shared inbox (shift lead)",
                  "2030-10-23T06:10:00Z")
    return Path(root) / "tickets" / ticket


def valid_order(kind="fix"):
    return {
        "request_ref": f"tickets/{TICKET}/request.md",
        "kind": kind,
        "resolved_intent": "The door board shows a door as taken for exactly its booked slots.",
        "grounding": [{"claim": "The door board reads the clash check.", "label": "verified",
                       "source": "the door board module, line 12"}],
        "assumptions_taken": [],
        "surfaces": ["door board"],
        "acceptance": [] if kind == "investigate" else [
            {"criterion": "A slot ending at 06:00 leaves its door free at 06:00.",
             "hard_case": "back-to-back slots at one door, 05:00 to 06:00 and 06:00 to 07:00"}],
        "stages_required": ["implement", "qc", "release"],
        "baseline": {"deployed_image": "portal:overnight-slots-2030-10-17",
                     "served": "measured", "migration_state": "mig-0031"},
        "schema_change": False,
    }


def log_lines(tdir):
    return (tdir / "events.jsonl").read_text(encoding="utf-8").splitlines()


class TempRecord(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="record-test-"))
        self.addCleanup(shutil.rmtree, str(self.root), ignore_errors=True)


class IntakeTests(TempRecord):
    def test_an_empty_request_is_refused(self):
        with self.assertRaises(record.Refused):
            record.intake(self.root, TICKET, "  \n", "shared inbox", "2030-10-23T06:10:00Z")
        self.assertFalse((self.root / "tickets" / TICKET).exists())

    def test_the_request_is_kept_verbatim_and_the_first_event_goes_through_append(self):
        tdir = make_ticket(self.root)
        self.assertIn(REQUEST, (tdir / "request.md").read_text(encoding="utf-8"))
        events = record.read_events(tdir)
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["stage"], events[0]["idempotency_key"]),
                         ("intake", f"intake:{TICKET}"))
        self.assertTrue((tdir / "questions.jsonl").exists())

    def test_attachments_are_copied_into_evidence_at_intake(self):
        note = self.root / "forwarded.txt"
        note.write_text("door 6 export, empty\n", encoding="utf-8")
        record.intake(self.root, TICKET, REQUEST, "shared inbox", "2030-10-23T06:10:00Z",
                      attachments=[str(note)])
        kept = self.root / "tickets" / TICKET / "evidence" / "2030-10-23-intake" / "forwarded.txt"
        self.assertEqual(kept.read_text(encoding="utf-8"), "door 6 export, empty\n")

    def test_a_request_is_written_once(self):
        make_ticket(self.root)
        with self.assertRaises(record.Refused):
            make_ticket(self.root)

    def test_a_request_carrying_a_secret_is_refused(self):
        with self.assertRaises(record.Refused):
            record.intake(self.root, TICKET, "please use this for the upload: " + SECRET_SHAPED[0],
                          "shared inbox", "2030-10-23T06:10:00Z")


class OrderTests(TempRecord):
    def setUp(self):
        super().setUp()
        self.tdir = make_ticket(self.root)

    def test_a_second_work_order_is_refused(self):
        record.place_order(self.root, TICKET, valid_order())
        before = (self.tdir / "order.json").read_bytes()
        with self.assertRaises(record.Refused) as caught:
            record.place_order(self.root, TICKET, valid_order())
        self.assertIn("record.py append", str(caught.exception))
        self.assertEqual((self.tdir / "order.json").read_bytes(), before)

    def test_an_investigation_with_acceptance_criteria_is_refused(self):
        order = valid_order("investigate")
        order["acceptance"] = [{"criterion": "x", "hard_case": "y"}]
        with self.assertRaises(record.Refused):
            record.place_order(self.root, TICKET, order)

    def test_a_criterion_without_its_hard_case_is_refused(self):
        order = valid_order()
        order["acceptance"] = [{"criterion": "A slot ending at 06:00 leaves its door free at 06:00."}]
        with self.assertRaises(record.Refused):
            record.place_order(self.root, TICKET, order)

    def test_a_verified_claim_without_a_source_is_refused(self):
        order = valid_order()
        order["grounding"] = [{"claim": "The door board reads the clash check.", "label": "verified"}]
        with self.assertRaises(record.Refused):
            record.place_order(self.root, TICKET, order)

    def test_nothing_skips_qc(self):
        order = valid_order()
        order["stages_required"] = ["implement", "release"]
        with self.assertRaises(record.Refused):
            record.place_order(self.root, TICKET, order)

    def test_a_schema_change_needs_its_migration_first(self):
        order = valid_order()
        order["schema_change"] = True
        order["stages_required"] = ["implement", "qc", "release", "migrate"]
        with self.assertRaises(record.Refused):
            record.place_order(self.root, TICKET, order)


class AppendTests(TempRecord):
    def setUp(self):
        super().setUp()
        self.tdir = make_ticket(self.root)

    def append(self, **fields):
        base = dict(actor="qc", stage="qc", decision="note", key="qc:TCC-101:1")
        base.update(fields)
        return record.append_event(self.root, TICKET, **base)

    def test_a_duplicate_key_is_a_no_op(self):
        first, appended = self.append(stage="report", decision="pass",
                                      key="report:TCC-101:live", actor="main-manager")
        self.assertTrue(appended)
        again, appended = self.append(stage="report", decision="pass",
                                      key="report:TCC-101:live", actor="main-manager")
        self.assertFalse(appended)
        self.assertEqual(again["seq"], first["seq"])
        self.assertEqual(len(log_lines(self.tdir)), 2)

    def test_secret_shapes_are_refused_in_note_and_reference(self):
        for value in SECRET_SHAPED:
            with self.subTest(value=value[:12]):
                with self.assertRaises(record.Refused):
                    self.append(note=value)
                with self.assertRaises(record.Refused):
                    self.append(ref=value)
        self.assertEqual(len(log_lines(self.tdir)), 1)

    def test_an_over_long_reference_is_refused(self):
        with self.assertRaises(record.Refused):
            self.append(ref="evidence/" + "x" * record.REF_MAX)

    def test_blocked_without_a_reason_is_refused(self):
        with self.assertRaises(record.Refused):
            self.append(decision="blocked")
        event, _ = self.append(decision="blocked", blocked_on="no staging host")
        self.assertEqual(event["blocked_on"], "no staging host")

    def test_stage_and_decision_come_from_fixed_vocabularies(self):
        with self.assertRaises(record.Refused):
            self.append(stage="tidy-up")
        with self.assertRaises(record.Refused):
            self.append(decision="approve")

    def test_read_from_defaults_to_the_last_entry(self):
        event, _ = self.append()
        self.assertEqual((event["seq"], event["read_from"]), (2, 1))

    def test_a_line_that_is_not_json_stops_the_tool(self):
        with open(self.tdir / "events.jsonl", "a", encoding="utf-8") as handle:
            handle.write("not json\n")
        with self.assertRaises(record.Refused):
            self.append()
        with self.assertRaises(record.Refused):
            record.status(self.root, TICKET)


class StatusTests(TempRecord):
    def setUp(self):
        super().setUp()
        self.tdir = make_ticket(self.root)

    def test_status_is_derived_from_the_last_event_and_never_stored(self):
        record.append_event(self.root, TICKET, "implementer", "implement", "pass",
                            key="implement:1", rung="implemented", ref="commit-ash")
        self.assertRegex(record.status(self.root, TICKET), r"rung\s+implemented \(#2\)")
        record.append_event(self.root, TICKET, "qc", "qc", "reject", key="qc:1",
                            ref="tickets/TCC-101/evidence/2030-10-23-qc-1/journey.txt")
        shown = record.status(self.root, TICKET)
        self.assertIn("rejected at qc (#3): back to implementer", shown)
        self.assertRegex(shown, r"rung\s+none")
        self.assertEqual(sorted(p.name for p in self.tdir.iterdir()),
                         ["events.jsonl", "evidence", "questions.jsonl", "request.md"])

    def test_a_stale_read_is_shown(self):
        record.append_event(self.root, TICKET, "project-manager", "order", "note",
                            key="order:note:1", note="correction to surfaces: export too")
        record.append_event(self.root, TICKET, "implementer", "implement", "pass",
                            key="implement:1", read_from=1)
        self.assertRegex(record.status(self.root, TICKET),
                         r"stale\s+#3 \(implementer\) read #1, but #2 \(project-manager\)")

    def test_questions_are_counted_and_only_a_person_answers(self):
        record.ask(self.root, TICKET, "project-manager", "owner",
                   "A slot ending at 06:00: is its door free for a booking from 06:00?",
                   "two readings")
        self.assertRegex(record.status(self.root, TICKET), r"questions\s+1 open of 1: Q1")
        with self.assertRaises(record.Refused):
            record.answer(self.root, TICKET, "Q1", "project-manager", "yes")
        record.answer(self.root, TICKET, "Q1", "owner", "Yes, free from 06:00.")
        self.assertRegex(record.status(self.root, TICKET), r"questions\s+0 open of 1")
        with self.assertRaises(record.Refused):
            record.answer(self.root, TICKET, "Q1", "owner", "Actually, no.")


class GuardTests(unittest.TestCase):
    LOG = "tickets/TCC-101/events.jsonl"
    OLD = b'{"seq": 1, "decision": "pass"}\n'

    def test_an_extended_log_passes(self):
        self.assertIsNone(guard.check(self.LOG, self.OLD, self.OLD + b'{"seq": 2}\n'))

    def test_an_edited_log_is_rejected(self):
        self.assertIsNotNone(guard.check(self.LOG, self.OLD, b'{"seq": 1, "decision": "reject"}\n'))

    def test_a_truncated_or_deleted_log_is_rejected(self):
        self.assertIsNotNone(guard.check(self.LOG, self.OLD, b""))
        self.assertIsNotNone(guard.check(self.LOG, self.OLD, None))

    def test_a_reordered_log_is_rejected(self):
        old = self.OLD + b'{"seq": 2}\n'
        self.assertIsNotNone(guard.check(self.LOG, old, b'{"seq": 2}\n' + self.OLD))

    def test_an_unterminated_last_line_cannot_be_extended(self):
        self.assertIsNotNone(guard.check(self.LOG, b'{"seq": 1', b'{"seq": 1}\n'))

    def test_a_write_once_file_cannot_change_or_go(self):
        path = "tickets/TCC-101/order.json"
        self.assertIsNotNone(guard.check(path, b"{}\n", b'{"kind": "fix"}\n'))
        self.assertIsNotNone(guard.check(path, b"{}\n", None))
        self.assertIsNone(guard.check(path, b"{}\n", b"{}\n"))

    def test_new_files_and_other_paths_pass(self):
        self.assertIsNone(guard.check(self.LOG, None, self.OLD))
        self.assertIsNone(guard.check("README.md", b"a\n", b"b\n"))
        self.assertIsNone(guard.check("tickets/TCC-101/lease.json", b"{}\n", None))


class WorkedExampleTests(unittest.TestCase):
    """The shipped example ticket obeys the same rules the tool enforces."""

    TDIR = ROOT / "tickets" / "TCC-142"

    def test_the_example_derives_to_verified_and_reported(self):
        shown = record.status(ROOT, "TCC-142")
        self.assertIn("passed report (#22, main-manager)", shown)
        self.assertRegex(shown, r"rung\s+verified \(#20\)")
        self.assertRegex(shown, r"questions\s+0 open of 1")
        self.assertNotIn("stale", shown)

    def test_the_example_work_order_validates(self):
        record.validate_order(json.loads((self.TDIR / "order.json").read_text(encoding="utf-8")))

    def test_every_example_event_is_one_the_tool_would_accept(self):
        keys = set()
        for event in record.read_events(self.TDIR):
            self.assertIn(event["stage"], record.STAGES)
            self.assertIn(event["decision"], record.DECISIONS)
            self.assertLessEqual(len(event["ref"]), record.REF_MAX)
            self.assertLessEqual(len(event["note"]), record.NOTE_MAX)
            self.assertIsNone(record.secret_shape(event["note"] + " " + event["ref"]))
            self.assertLess(event["read_from"], event["seq"])
            self.assertNotIn(event["idempotency_key"], keys)
            keys.add(event["idempotency_key"])
            if event["stage"] != "lease" and event["ref"].startswith(("tickets/", "releases/")):
                self.assertTrue((ROOT / event["ref"]).exists(), event["ref"])


class LeaseTests(TempRecord):
    """A rejected push is the lock. Uses a real bare remote and two clones."""

    def setUp(self):
        super().setUp()
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        isolated = {"HOME": str(self.root), "XDG_CONFIG_HOME": str(self.root),
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "record-test", "GIT_AUTHOR_EMAIL": "record-test",
                    "GIT_COMMITTER_NAME": "record-test", "GIT_COMMITTER_EMAIL": "record-test"}
        patcher = mock.patch.dict(os.environ, isolated)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("GIT_CONFIG_GLOBAL", None)

        self.remote = self.root / "remote.git"
        self.git(self.root, "init", "-q", "--bare", str(self.remote))
        seed = self.root / "seed"
        self.git(self.root, "init", "-q", str(seed))
        make_ticket(seed)
        self.git(seed, "add", "tickets")
        self.git(seed, "commit", "-q", "-m", f"{TICKET}: intake")
        self.git(seed, "push", "-q", str(self.remote), "HEAD")

    def git(self, where, *args):
        result = subprocess.run(["git", "-C", str(where)] + list(args),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def clone(self, name):
        path = self.root / name
        self.git(self.root, "clone", "-q", str(self.remote), str(path))
        return path

    def lease(self, clone):
        return clone / "tickets" / TICKET / "lease.json"

    def test_a_refused_push_means_held_and_leaves_nothing_behind(self):
        a, b = self.clone("a"), self.clone("b")
        record.claim(a, TICKET, "implementer-s1", "implement")
        with self.assertRaises(record.Held):
            record.claim(b, TICKET, "implementer-s2", "implement")
        self.assertFalse(self.lease(b).exists())
        self.assertEqual(self.git(b, "status", "--porcelain").stdout, "")
        self.assertEqual(len(log_lines(b / "tickets" / TICKET)), 1)

        self.git(b, "pull", "-q", "--ff-only")
        with self.assertRaises(record.Held) as caught:
            record.claim(b, TICKET, "implementer-s2", "implement")
        self.assertIn("held by implementer-s1", str(caught.exception))

    def test_an_expired_lease_is_taken_over_and_the_previous_holder_named(self):
        a, b = self.clone("a"), self.clone("b")
        record.claim(a, TICKET, "qc-s1", "qc", hours=0)
        self.git(b, "pull", "-q", "--ff-only")
        note = record.claim(b, TICKET, "qc-s2", "qc")
        self.assertIn("took over from qc-s1", note)

    def test_release_removes_the_lease_and_records_both_ends(self):
        a = self.clone("a")
        record.claim(a, TICKET, "deployer-s1", "release")
        with self.assertRaises(record.Refused):
            record.release(a, TICKET, "deployer-s2")
        record.release(a, TICKET, "deployer-s1")
        self.assertFalse(self.lease(a).exists())
        notes = [e["note"] for e in record.read_events(a / "tickets" / TICKET)[1:]]
        self.assertEqual([n.split(":")[0] for n in notes], ["take release", "release release"])
        self.assertEqual(self.git(a, "status", "--porcelain").stdout, "")


if __name__ == "__main__":
    unittest.main()
