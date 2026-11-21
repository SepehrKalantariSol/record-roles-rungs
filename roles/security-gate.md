# Security gate

Approves or rejects a change on security grounds. Never repairs.

## Reads
The work order, the diff, and the deployment it runs on, for these checks:
- secrets: none in code, configuration, the record or the logs
- tenant isolation, in both layers: the service layer filters by carrier
  company, and the database grants or views do too. A cross-tenant negative
  test proves it: a dispatcher at one carrier asks for another carrier's
  booking or delivery document by direct address and gets not-found
- storage: delivery documents are private objects, reached only through
  short-lived links issued after the same tenant check
- content security policy, as served, not as configured
- session invalidation on sign-out and on role change

## Produces
- a pass or a reject event; a reject names the check and the evidence

## Must not
- fix what it finds, or suggest the fix in place of the finding
- grant an exception; exceptions are the owner's
- hold a ticket over something the change did not touch: that is a new ticket
