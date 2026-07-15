# Output contract

Read only the exact `input/` paths named by the task. Never list directories, inspect
`AGENTS.md`, or inspect `output/`. Write only the contracted UTF-8 artifacts under `output/`
and do not re-read them after writing. Do not write `output/manifest.json`: the trusted
NovelWiki stop hook creates the strict manifest and calculates sizes and hashes. Stop
immediately after the last contracted artifact. Never fabricate missing work.
