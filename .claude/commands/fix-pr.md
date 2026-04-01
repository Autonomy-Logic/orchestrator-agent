Fix unresolved review comments on PR #$ARGUMENTS.

> **Why a command, not a skill:** This has significant side effects (commits, issues, thread resolution) but `$ARGUMENTS` is required, which prevents accidental invocation. No need for `disable-model-invocation: true`.

## Instructions

### Step 1 — Gather context

1. Fetch the PR metadata:
   ```
   gh pr view $ARGUMENTS
   ```

2. Fetch **all review threads** (including resolution status) using GraphQL:
   ```
   gh api graphql -f query='
     query {
       repository(owner: "Autonomy-Logic", name: "orchestrator-agent") {
         pullRequest(number: $ARGUMENTS) {
           reviewThreads(first: 100) {
             nodes {
               id
               isResolved
               comments(first: 10) {
                 nodes {
                   id
                   body
                   path
                   line
                   author { login }
                 }
               }
             }
           }
         }
       }
     }'
   ```

3. Filter to **unresolved threads only** (where `isResolved` is `false`). If there are no unresolved threads, report that and stop.

4. Fetch the PR diff to understand the current code context:
   ```
   gh pr diff $ARGUMENTS
   ```

### Step 2 — Classify comments

For each unresolved review thread, read **all comments in the thread** (not just the first one). Replies often contain critical context:
- The PR author may have acknowledged the issue, explained why it exists, or proposed an alternative fix.
- The reviewer may have narrowed or expanded the scope of the original comment.
- A reply may reclassify the issue (e.g., "this is actually a blocker" or "this can wait, let's track it as an issue").
- A reply may mark the comment as partially resolved (e.g., "I fixed the naming, but the extraction can be done later").

Use the **entire conversation** — not just the root comment — to determine the classification, the scope of the fix, and whether the item is still actionable.

Classify each thread into one of two categories:

**Essential (fix on this PR):**
- Comments prefixed with :x: (blocking issues)
- Security vulnerabilities
- Bugs or broken functionality
- Violations of Clean Architecture dependency rule (imports pointing outward)
- Incorrect layer placement (e.g., use case importing from controllers or repos)
- Type errors or missing type hints that break contracts
- Broken repository interface contracts

**Deferrable (candidate for Jira issue):**
- Comments prefixed with :warning: (suggestions/warnings)
- Code improvement suggestions (refactoring, extraction candidates)
- Style or naming convention suggestions
- Documentation improvements
- Nice-to-have enhancements
- Forward-looking concerns (e.g., "consider adding X when Y is built")

**When a comment fits both categories**, classify as Essential. The prefix (:x:/:warning:) is a strong signal but the content takes precedence — a :warning: comment describing a security concern or bug is still Essential.

Present the full classification to the user in this format:

```
## Unresolved Comments on PR #<number>

### Essential — to fix on this PR
1. **[file:line]** <summary of issue> (Thread ID: <id>)
2. ...

### Deferrable — candidates for Jira issues
1. **[file:line]** <summary of issue> (Thread ID: <id>)
2. ...
```

### Step 3 — Check for existing Jira issues

Load the Jira configuration from `.claude/jira.json` to get the `cloudId`, `projectKey`, and `defaultIssueType`.

For each deferrable item, search existing Jira issues to see if a matching issue already exists. Use the `mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql` tool:
- `cloudId`: from `.claude/jira.json`
- `jql`: `project = "<projectKey>" AND status != Done AND summary ~ "<relevant keywords>"`

Report any matches found:
```
### Existing issues found
- Deferrable item 1 → matches RTOP-123 "<title>"
- Deferrable item 3 → no existing issue
```

Remove items that already have a matching open issue from the deferrable list. Mark their review threads as resolved with a reply linking to the existing issue.

### Step 4 — Prompt for Jira issue creation

Use the `AskUserQuestion` tool to ask the user which remaining deferrable items should become Jira issues. Items **not** deferred to issues will be fixed on this PR alongside the essential items.

Present options:
- **Defer all to issues** — create Jira issues for all remaining deferrable items
- **Fix all on this PR** — fix all remaining deferrable items on this PR (no issues created)
- **Choose specific to defer** — pick which to defer to Jira issues; the rest will be fixed on this PR

If the user chooses "Choose specific to defer", ask a follow-up multi-select question listing each deferrable item. Any items **not** selected for deferral will be fixed on this PR.

### Step 5 — Create Jira issues

For each confirmed deferrable item, create a Jira issue using the `mcp__claude_ai_Atlassian__createJiraIssue` tool with:
- `cloudId`: from `.claude/jira.json`
- `projectKey`: from `.claude/jira.json`
- `issueTypeName`: from `.claude/jira.json` (`defaultIssueType`)
- `summary`: concise title describing the issue
- `description`: markdown body with this format:
  ```
  ## Context
  From PR #<number> review comment on `<file>:<line>`.

  ## Description
  <Full comment body>

  ## Suggested fix
  <If the review comment included a suggestion, include it here>

  ---
  _Auto-created from PR #<number> review thread._
  ```

After creating each issue, resolve the corresponding review thread by:
1. Replying to the thread with a link to the created Jira issue:
   ```
   gh api repos/Autonomy-Logic/orchestrator-agent/pulls/$ARGUMENTS/comments -f body="Tracked in [<issue_key>](https://autonomylogic.atlassian.net/browse/<issue_key>)" -F in_reply_to=<comment_id>
   ```
2. Resolving the thread via GraphQL:
   ```
   gh api graphql -f query='
     mutation {
       resolveReviewThread(input: {threadId: "<thread_id>"}) {
         thread { isResolved }
       }
     }'
   ```

### Step 6 — Fix essential items and remaining deferrable items

Combine the essential items with any deferrable items not deferred to Jira issues. Sort the combined list by priority/severity:
1. Security vulnerabilities
2. Bugs / broken functionality
3. Clean Architecture violations (dependency rule, layer placement)
4. Type errors
5. Broken repository interface contracts
6. Remaining deferrable items (code improvements, style, naming, etc.)

**Each fix must be its own commit** — one commit per review thread. This keeps the history granular so individual fixes can be reverted independently.

For each item, in priority order:

1. **Read the relevant file(s)** and understand the issue. Re-read all replies in the thread — they may contain the PR author's preferred approach, constraints, or partial fixes already applied.
2. **Implement the fix.** Make the minimal change needed to address the review comment. If a reply narrowed the scope or suggested a specific approach, follow that.
3. **Stage and commit** the fix as a separate commit with a message referencing the review:
   ```
   git add <changed files>
   git commit -m "$(cat <<'EOF'
   fix: <concise description of what was fixed>

   Addresses review comment on <file>:<line>.
   PR #$ARGUMENTS

   Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```
4. **Reply to the review thread** confirming the fix:
   ```
   gh api repos/Autonomy-Logic/orchestrator-agent/pulls/$ARGUMENTS/comments -f body="Fixed in <commit_sha>" -F in_reply_to=<comment_id>
   ```
5. **Resolve the thread** via GraphQL:
   ```
   gh api graphql -f query='
     mutation {
       resolveReviewThread(input: {threadId: "<thread_id>"}) {
         thread { isResolved }
       }
     }'
   ```

### Step 7 — Summary

After all items are processed, post a summary comment on the PR:
```
gh pr comment $ARGUMENTS --body "$(cat <<'EOF'
## Review Comments Addressed

### Fixed in this PR
- <commit_sha> — <description> (`file:line`)
- ...

### Deferred to Jira issues
- [<issue_key>](https://autonomylogic.atlassian.net/browse/<issue_key>) — <title> (`file:line`)
- ...

### Already tracked
- [<issue_key>](https://autonomylogic.atlassian.net/browse/<issue_key>) — <title> (existing issue)
- ...

All review threads resolved.
EOF
)"
```

Report the final status to the user.
