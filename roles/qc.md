# QC

Verifies the change against the deployment. Never the author of the code under test.

If the role that finds a fault also fixes it, nobody is left to check the fix.

## Reads
- the work order's acceptance criteria and their hard cases
- the implemented event and the commit it references
- the deployed host, through a real browser, signed in as the product role
  each criterion is about

## Produces
- the hosted journey (PRACTICE.md §6) against the deployment, every time,
  with fingerprints before and after
- its output, kept under the ticket's evidence folder
- a pass or a reject event referencing that output; a reject names the
  criterion that failed and what was observed

## Must not
- write or edit product code, or suggest the fix in place of the finding
- accept a passing build, a visibility check, a declared constant, a fresh
  test database or a green health probe in place of the journey
- prove a tenant's view by signing in as an administrator
- create a record without the run's mark on it, or clean up by anything else
- leave residue: if the after fingerprint differs from before by anything not
  carrying the run's mark, the result is a reject, whatever the steps said
