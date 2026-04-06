Review PR #$ARGUMENTS using the checklist defined in `.claude/pr-review-checklist.md`.

## Instructions

### Step 0 — Detect previous reviews (incremental mode)

1. Get the PR head commit:
   ```
   gh pr view $ARGUMENTS --json headRefOid -q '.headRefOid'
   ```

2. Search PR comments for a previous review marker:
   ```
   gh api repos/Autonomy-Logic/orchestrator-agent/issues/$ARGUMENTS/comments --jq '
     [.[] | select(.body | test("autonomy-review-head: [a-f0-9]+"))]
     | last
     | .body
     | capture("autonomy-review-head: (?<sha>[a-f0-9]+)")
     | .sha'
   ```

3. Determine the review mode:
   - **No marker found** → **Full review.** Proceed with `gh pr diff $ARGUMENTS` for the complete PR diff.
   - **Marker found but SHA equals current head** → Report "No new commits since last review" and stop.
   - **Marker found and SHA differs** → **Incremental review.** Use the compare API for only the new changes:
     ```
     gh api repos/Autonomy-Logic/orchestrator-agent/compare/{last_reviewed_sha}...{head_sha} \
       -H "Accept: application/vnd.github.v3.diff"
     ```
     Also fetch the full PR diff with `gh pr diff $ARGUMENTS` for context, but **only review the incremental diff**. The full diff is available as reference to understand surrounding code.

4. When in incremental mode, prefix the review output with:
   ```
   > **Incremental review:** reviewing commits {last_reviewed_sha_short}..{head_sha_short} ({N} new commit(s)). Previous commits were reviewed in an earlier pass.
   ```

### Step 0.5 — Check PR author

1. **Get the current authenticated GitHub user:**
   ```
   gh api user --jq '.login'
   ```

2. **Get the PR author:**
   ```
   gh pr view $ARGUMENTS --json author -q '.author.login'
   ```

3. **If the PR author matches the current user**, the review must use `event="COMMENT"` only — never `APPROVE` or `REQUEST_CHANGES`. Skip formal approval/rejection in both the review submission (Step 3, item 6) and the verdict (Step 3, item 7). The verdict line should read **"Comment only (self-authored PR)"** instead of Approve/Request Changes.

4. **If the PR author is someone else**, proceed normally with `APPROVE`, `REQUEST_CHANGES`, or `COMMENT` as appropriate.

### Step 1 — Fetch context and classify

1. **Fetch the PR description** using `gh pr view $ARGUMENTS`.

2. **Fetch the diff** (determined by Step 0):
   - Full review → `gh pr diff $ARGUMENTS`
   - Incremental review → compare API diff (with full diff as background context)

3. **Classify changed files by layer.** Group every changed file into one of these layers based on its path:
   - `src/entities/` → Domain (Entities)
   - `src/use_cases/` → Business Logic (Use Cases)
   - `src/controllers/` → Transport (Controllers)
   - `src/repos/` → Persistence (Repositories)
   - `src/tools/` → Infrastructure (Tools)
   - `src/index.py`, `src/bootstrap.py` → Composition Root
   - `tests/` → Tests
   - `install/` → Installation / Deployment
   - Root-level files → Root / Config

### Step 2 — Review

4. **Review each layer independently.** For every layer that has changed files, run through the full checklist from `.claude/pr-review-checklist.md`. Apply only the sections relevant to that layer:
   - **Clean Architecture** applies to all `src/` layers — verify dependency rule for each changed file.
   - **Python Conventions** applies to all `src/` layers.
   - **Python & Code Quality** and **Security** apply to all layers.
   - **Code Improvements & Refactoring Opportunities** applies to all layers — scoped per layer. Compare new code against the entire codebase of that same layer (e.g., new use case code checked against all of `src/use_cases/`, new controller code against all of `src/controllers/`). Do NOT cross layer boundaries for these checks.

5. **For Code Improvements specifically:**
   - Read the existing codebase of each affected layer (not just changed files) to identify duplication, extraction candidates, and inconsistencies introduced by the PR.
   - Check if the PR introduces patterns already solved elsewhere in the same layer.
   - Check if repeated logic across the PR's own files should be extracted.

### Step 3 — Post results

6. **Leave inline review comments on the PR** for every issue found. Use `gh api` to post a PR review with inline comments:

   - For each issue (:x: or :warning:), create an inline comment on the specific file and line where the issue occurs.
   - Comment body must include: the checklist item name, a clear description of the issue, and a suggested fix if applicable.
   - Prefix blocking issues with :x: and suggestions/warnings with :warning:.

   Post the review using a single `gh api` call:
   ```
   gh api repos/Autonomy-Logic/orchestrator-agent/pulls/{pr_number}/reviews \
     -f event="COMMENT" \
     -f body="<overall review summary>" \
     -f 'comments=[{"path":"<file>","line":<line>,"body":"<comment>"}]'
   ```

   If there are blocking issues (:x:), use `event="REQUEST_CHANGES"`. If all checks pass or only warnings exist, use `event="COMMENT"`.

7. **Also post a top-level summary comment** on the PR using `gh pr comment $ARGUMENTS --body "<summary>"` with this format:

   ```
   # PR #<number> Review

   ## Summary
   <Brief description of what the PR does>

   ## Layer: <Layer Name>

   ### Checklist Results
   - :white_check_mark: **Item name** — passes (only list if notable)
   - :x: **Item name** — <issue with file:line reference>
   - :warning: **Item name** — <warning or suggestion>

   ### Code Improvement Findings
   - <Duplication, extraction candidates, inconsistencies found against the layer's full codebase>

   (Repeat for each affected layer)

   ## Cross-Layer Observations
   <Issues spanning layers: dependency rule violations, contract mismatches between use cases and repos, inconsistencies between controllers and use cases, etc.>

   ## Verdict
   - **Approve** / **Request Changes** / **Comment**
   - <Summary of blocking issues if any>

   <!-- autonomy-review-head: <full_head_commit_sha> -->
   ```

   The `<!-- autonomy-review-head: ... -->` marker is **required**. It records the PR head commit at the time of this review so that subsequent runs can detect new commits and switch to incremental mode. Always use the full 40-character SHA.

8. **Be specific.** Every issue must reference a file path and line number. Do not make vague observations.
