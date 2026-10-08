# Feature groups in the background

Today grouping runs on a button press, regroups the last 80 commits from scratch and is cached per
HEAD: every new commit throws the result away and the user waits again. Goal: a fourth tab in the
project panel that is always ready, grows a little with each commit, and shows who works on what.

## Tab
- Fourth icon tab "Группы фич" in the project panel (desktop sidebar and phone), next to Changes,
  Commits and Files. The "Группы фич" button in Commits goes away.
- Top: "Сейчас" strip, one line per author active in the last 7 days: author chip (same colours as
  in Commits) + the group of their latest commit + "N ч назад". This is "what Denis and Pasha work on".
- Then "Ещё не разобрано": commits newer than the last grouping, as plain commit rows (open the diff
  like in Commits). They are visible at once; the model only sorts them later.
- Then groups, most recently touched first: title, short summary, author chips, commit count, time of
  the last commit. Opening a group lists its commits as now.
- Footer: model and time of the last pass, and "Разобрать сейчас" that only skips the wait. No model
  picker: the order below is fixed.

## Incremental store
- One store per repository (repo root), not per HEAD: groups with stable ids, title, summary, commit
  shas; plus the set of processed shas. 0600 file under the existing cache folder.
- A pass sends the model the existing groups (id, title, one-line summary) and up to 40 new commits
  (sha, subject, author, file names; never code, as now). Answer: each new commit goes to an existing
  group id or a new group; touched groups may get a new summary. Validated like today: only real shas,
  each once; anything left stays "Ещё не разобрано" and is retried next pass.
- First run on a repo seeds the latest 200 commits in batches of 40, oldest first, in the background.
- Old groups (no commit for 90 days) are folded into "Раньше" so the prompt stays small.

## Background worker
- One thread in the panel. Every 5 minutes: repositories of this computer's sessions (session folder
  and worktrees, the same detection as Changes). Each computer groups its own repositories; the gateway
  only shows them, so other computers need no new route.
- A pass starts when there are new commits and the newest is at least 10 minutes old (an agent
  committing in a row is grouped once), or when 20+ commits wait. One pass at a time per repository.
  Polled: repositories of current sessions plus those opened in the tab since the panel started.
- Commits: local branches and remote-tracking branches (`--branches --remotes`), so a collaborator's
  pushed branch appears after a fetch.
- Fetch: a quiet `git fetch` every 15 minutes for those repositories (no prompts, `GIT_TERMINAL_PROMPT=0`,
  existing fetch code), so Pasha's commits arrive without pressing "Получить с GitHub". Always on.

## Model
- Order, each tried when the one before fails: Claude Haiku (`claude -p --model haiku --tools ""`),
  Codex Luna (`codex exec -s read-only --ephemeral --ignore-user-config --ignore-rules`), both CLIs on the
  user's subscription in an empty temporary folder; then Kimi; then the first LM Studio model. With no
  model the tab shows commits only and says why.
- Cost stays small: nothing is sent when there are no new commits; a pass is one short request.
- A commit the model leaves out twice goes to "Без группы" instead of being sent again forever.

## Out of scope
- Grouping by code content (diffs), per-user accounts, notifications about groups.
