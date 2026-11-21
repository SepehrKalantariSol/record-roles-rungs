#!/usr/bin/env python3
"""guard.py: fail any push or pull request that rewrites the record.

    python3 bin/guard.py --base <commit> [--head <commit>]

For every path that changed between base and head:
  - an append-only log that existed at base must begin, byte for byte, with
    its content at base. Editing, reordering, truncating or deleting it fails;
  - a write-once file that existed at base must not change or disappear;
  - new files pass.

Its limit, stated rather than hidden: with no base to compare against (a first
push, a new branch, a history rewritten by force) there is nothing to check,
and the guard passes. The agents' deny list forbids forced pushes, and the
record repository's main branch should be protected; those cover the gap.

Standard library only.
"""

import argparse
import re
import subprocess
import sys

APPEND_ONLY = re.compile(r"^tickets/[^/]+/(events|questions)\.jsonl$")
WRITE_ONCE = re.compile(r"^tickets/[^/]+/(request\.md|order\.json)$")
INSTEAD = "Record the correction as a new event (bin/record.py append) instead."


def kind_of(path):
    if APPEND_ONLY.match(path):
        return "append-only"
    if WRITE_ONCE.match(path):
        return "write-once"
    return None


def check(path, old, new):
    """old and new are bytes, or None where the file is absent.
    Returns a failure message, or None if the change is allowed."""
    kind = kind_of(path)
    if kind is None or old is None:
        return None
    if kind == "append-only":
        if new is None:
            return f"{path}: an append-only log was deleted. Restore it. {INSTEAD}"
        if old and not old.endswith(b"\n") and new != old:
            return (f"{path}: its last line at base had no newline, so anything "
                    f"added changes that line. {INSTEAD}")
        if not new.startswith(old):
            return (f"{path}: lines that existed at base were edited, reordered or "
                    f"removed. Only appending is allowed; restore them. {INSTEAD}")
        return None
    if new is None:
        return f"{path}: a write-once file was deleted. Restore it. {INSTEAD}"
    if new != old:
        return f"{path}: a write-once file was changed. Restore it. {INSTEAD}"
    return None


def git(*args):
    return subprocess.run(["git"] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def blob(commit, path):
    result = git("cat-file", "blob", f"{commit}:{path}")
    return result.stdout if result.returncode == 0 else None


def resolvable(commit):
    if not commit or set(commit) == {"0"}:
        return False
    return git("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}").returncode == 0


def changed_paths(base, head):
    result = git("diff", "--name-only", "--no-renames", "-z", base, head)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"guard: git diff failed, so nothing was checked: {detail}")
    return [p for p in result.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="guard.py", description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="", help="the pull request's base, or the commit before the push")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)

    if not resolvable(args.base):
        print("guard: no base commit to compare against (a first push, a new branch, "
              "or rewritten history). Nothing was checked. This is the guard's stated "
              "limit; the deny list and branch protection cover it.")
        return 0

    paths = changed_paths(args.base, args.head)
    failures = [message for message in
                (check(path, blob(args.base, path), blob(args.head, path)) for path in paths)
                if message]
    for message in failures:
        print(f"guard: {message}")
    if failures:
        return 1
    print(f"guard: {len(paths)} changed path(s) checked against {args.base}; "
          "the record was only extended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
