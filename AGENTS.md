# BRAMANDA repository rules

- Preserve existing work, application behavior, payment security, database
  relationships, migrations, source, tests, configuration, docs, and uploaded media.
- Never create disposable logs, temporary tests, diagnostic reports, or random
  backups in the project root. Prefer terminal output or in-memory diagnostics.
- When files are needed, use unique directories under the OS temporary directory
  (`$env:TEMP` or Python `tempfile`); clean up task-created disposable artifacts
  after successful verification when safe. Explain any retained artifacts and paths.
- Never delete files still needed for investigation or recovery. Before deleting
  existing files, check dependencies and obtain approval for the exact paths.
- Database backups require a genuine recovery need and explicit approval before
  creation. Store approved backups outside the project root at an agreed location.
- Never delete, overwrite, replace, flush, or reset the active database. Do not run
  destructive migrations or delete customer, order, payment, or inventory data.
- Never expose or log credentials, customer personal information, signed invoice
  tokens, or private payment data. Report sanitized statuses and counts instead.
- Avoid unnecessary files and dependencies; modify existing files where appropriate
  rather than creating redundant alternatives. Keep the Django structure organized.
- Create reports or documentation only when requested or when they provide lasting
  project value. Do not create Markdown progress reports for routine tasks.
- Never commit, push, deploy, or modify Git history without explicit permission.
  Do not run destructive database or Git operations, reset, or discard existing work.
- Run appropriate checks and tests after changes. Report results in the terminal
  or conversation, with pre-existing failures distinguished from new failures.
- Git ignore rules prevent accidental tracking; they do not authorize deletion or
  justify hiding necessary source, tests, migrations, or documentation.
