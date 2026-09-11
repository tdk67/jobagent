# JobAgent JOURNAL (append-only)

## 2026-09-12 — F1 done (PII purge, by lead agent)
Real personal data (name, home address, personal email, mobile, CV filenames) was committed
in `tests/test_cover_letter.py` (old commit 362aead) and pushed to the public repo.
What changed: fixture rewritten to Jane Doe dummy data (test still passes); entire history
squashed into orphan commit `04e93ae` with GitHub-noreply author; force-pushed; old commit
verified unreachable from a fresh clone; local reflog expired + gc pruned.
Lesson: any fixture copied from a local profile must be scrubbed before commit — add the
`logs/tasks/pii_patterns.txt` grep to pre-commit habits.
