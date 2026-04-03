# T17 - FIX-REVIEW: Fly.io docs use wrong import CLI syntax

## Summary

Fixed documentation in `deploy/fly/README.md` to use the correct `--input` flag for import commands. The CLI parser requires `--input` as a named flag, not a positional argument.

## Changes Made

1. **Line 206** (Breaking Migration Procedure):
   - Before: `distillery import /data/backup-before-breaking.json --mode merge`
   - After: `distillery import --input /data/backup-before-breaking.json --mode merge`

2. **Line 242** (Rollback from Backup):
   - Before: `fly ssh console -C "distillery import /data/backup-YYYYMMDD.json --mode replace" --app <app-name>`
   - After: `fly ssh console -C "distillery import --input /data/backup-YYYYMMDD.json --mode replace" --app <app-name>`

## Verification

- [x] T17-01-verification.txt: Confirmed both lines now use --input flag correctly
- [x] CLI implementation verified (src/distillery/cli.py lines 117-122)
- [x] Documentation now matches CLI argument parser definition

## Status

**COMPLETE** - Both import command examples in the Fly.io deployment guide now use the correct `--input` flag syntax as required by the CLI parser.
