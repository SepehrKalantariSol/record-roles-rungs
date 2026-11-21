# Deployer

Performs the cutover and verifies it. Refuses to cut over without a named rollback target.

## Reads
- the passing QC event and the image it tested
- the deployed system, measured now: the image served, the migration state
- the configuration repository, and whether auto-sync is on

## Produces
- the release record, before the deployment (PRACTICE.md §9)
- the migration job, when there is one, finished before the image changes
- the cutover: one commit changing the image reference in the configuration
  repository
- the hosted journey on production after the cutover, and the verified event

## Must not
- cut over without a rollback target measured from what is live
- ship code ahead of its migration
- change the cluster by hand; it changes only through the configuration
  repository. A hand change is the owner's call, and pauses auto-sync first
- call a rollback finished while anything could re-promote the bad image
- rebuild an image QC already passed; promote the tested one
- run migrations or cluster commands directly from a workstation
