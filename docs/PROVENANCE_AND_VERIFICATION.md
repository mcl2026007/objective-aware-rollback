# Provenance and verification notes

- The frozen configuration specifies four policies (B0–B3), 140 scenario templates (40 development, 100 held-out-labelled), and 560 policy–scenario executions.
- The archived frozen metrics record Python 3.12.3 on Windows 11 and CPU-only execution.
- The supplied historical Windows environment log describes an earlier candidate revision with three policies and 420 runs. It is not evidence of a Windows rerun of this four-policy frozen revision.
- The supplied archive's final submission verification records 28 passing tests and a successful independent evaluation rerun in its analysis environment. These records are historical evidence, not a guarantee that a second student's machine will pass.
- The README setup/run commands are therefore marked `[TEST REQUIRED]` for an independent reproduction.
- The environment diagnostic was adjusted in this package to check `frozen_scenarios.jsonl` instead of the obsolete `candidate_scenarios.jsonl` path.
- No software/data license was included in the source archive. A license must be selected by the rights holder before public redistribution.
- The source archive also contained a separate manuscript submission package with personal author/contact details. That package was deliberately excluded from this public software bundle; confirm author metadata separately before releasing the manuscript.
