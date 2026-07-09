# Comment mentions with Wagtail 7.4 compatibility

Status: approved design, including the Wagtail 8 primary-branch and Wagtail 7.4 compatibility strategy

Primary development base: the current pull-request branch on Wagtail 8.0 alpha

Compatibility floor: Wagtail `stable/7.4.x`, including Django 5.2 and 6.0 and Wagtail's supported custom user models

## Context

This change adds `@` mentions to page comments and replies. A page editor can select another eligible editor while writing, the selected text is retained as a structured mention, and a newly mentioned user can receive the existing updated-comments email with wording that distinguishes a direct mention from an ordinary subscription notification.

The current pull request proves the basic interaction on Wagtail 8.0 alpha code, but it has correctness problems that require a substantial redesign rather than incremental patching:

- Page creation crashes while serializing the suggestion URL because it attempts to reverse an edit-page route with a page ID of `None`.
- Mentions entered while creating a page are returned to the browser but are neither persisted nor notified.
- The browser always submits an empty mention list, while the form has no relation-derived initial value. Saving a page can therefore treat another author's unchanged comment as edited or erase its mentions.
- Existing mentions are re-authorized as though they were new. A later account deactivation or permission change can make an otherwise unrelated page save fail.
- Mention identity is inferred from mutable, non-unique email-shaped text. Empty or duplicate email addresses, renamed accounts, repeated display names, and forged mention payloads are not handled safely.
- Mention rows are saved after the page revision or publish transaction. Invalid or duplicate payloads can fail after part of the page save has already succeeded.
- Notification deduplication happens globally by recipient, so a subscription notification for one changed comment can suppress a direct-mention notification for another. Mention rows are then marked notified even when no message was sent.
- The custom `contenteditable` implementation does not preserve the browser's native textarea guarantees for multiline text, selection replacement, paste, undo, IME composition, mobile input, or assistive technology. It also has stale-query and stale-caret races.
- The shared author serialization exposes commenter email addresses and user-management URLs to page editors who do not necessarily have permission to manage users.
- The suggestion endpoint does unbounded filtering with per-result permission checks, has avoidable query growth, and remains reachable when comments are disabled.
- Replies cannot contain mentions, mention-only edits are missing from audit data, and edited comments can be presented as "new comments" in email.

The implementation will be rebuilt on the current pull-request branch. Feature logic and data contracts will remain independent of Wagtail 8-only routing APIs, and a real backport worktree will prove that the result works on `stable/7.4.x` with only the expected route-registration, migration-dependency, and test-location adaptations.

## Goals

- Support creating, editing, removing, rendering, serializing, auditing, and notifying mentions in both top-level comments and replies.
- Support the full page lifecycle: page creation, draft save, autosave, publish, submit for moderation, and later edit.
- Preserve normal comment and page-save behavior when an existing mentioned user is renamed, deactivated, deleted, or loses page permission.
- Treat mention identity and text placement as structured server-validated data, without parsing saved prose to recover identity.
- Preserve native character editing, keyboard access, screen-reader semantics, mobile input, IME composition, paste, selection, and text undo behavior; occurrence identity follows the explicit sidecar rules below.
- Avoid expanding the comment payload with separate raw email fields or user-management URLs. On an email-as-username user model, Wagtail's canonical display identity can itself be an email address and remains usable wherever Wagtail would normally display that identity.
- Keep mention persistence atomic with the comment or reply save and make notification behavior deterministic.
- Work with integer, UUID, and converted custom user primary keys supported by Wagtail's test configurations.
- Bound suggestion and submitted-mention work to predictable limits.

## Non-goals

- Mentions do not grant page access, add users to workflows, subscribe users permanently, or bypass notification preferences.
- Saved mention text is not dynamically rewritten when a user's profile changes.
- Arbitrary pasted `@text` is not automatically converted into a mention.
- Cross-site, external-email, group, role, and team mentions are outside this change.
- Rich-text formatting inside comments is outside this change.
- The first version will not link rendered mentions to the user-management interface. This avoids both permission-sensitive links and navigation away from unsaved page edits.
- Delivery retries and durable email outboxes are outside this change; mention mail follows Wagtail's existing comment-email delivery guarantees.
- This work does not publish a second pull request or release branch for 7.4. The required 7.4 deliverable is a retained, committed local compatibility branch plus reproducible evidence that the primary feature can be backported; publishing that branch requires separate authorization.

## Considered approaches

### Native textarea plus structured ranges

Keep the existing native textarea as the editing surface and store selected mention occurrences as ranges alongside the plain comment text. A suggestion list is visually anchored to the textarea, but text input and selection remain browser-native.

This approach has the smallest editing surface, supports both comments and replies consistently, and makes the data contract independently testable. It is the selected approach.

### Draft.js entities plus structured ranges

Draft.js could provide inline entity highlighting while editing and Wagtail already carries related frontend experience. It would nevertheless introduce a rich-editor state model for a plain-text field, require conversion and hydration logic, and add keyboard, screen-reader, and lifecycle complexity to a small feature. It is not selected.

### Harden the custom contenteditable and relational occurrence model

The current pull request could be extended with DOM normalization, custom selection bookkeeping, IME handling, relation-derived form initial values, and transactional relation saves. This retains inline styling during editing but preserves the largest browser-specific risk and the invasive reverse-relation behavior on `Comment.save()`. It is not selected.

## Data model

`Comment` and `CommentReply` each gain a `mentions` JSON field with `default=list`. Each list entry represents one occurrence in that individual message:

```json
{
  "key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb",
  "user_id": "42",
  "start": 14,
  "end": 26,
  "label": "@Jane Smith"
}
```

- `key` is a client-generated UUID for the occurrence. It remains stable while an occurrence is retained and distinguishes a retained occurrence from a newly added occurrence.
- `user_id` is the target user's primary key serialized through the model field's supported string representation. Server lookup and validation use the user model field rather than assuming an integer.
- `start` and `end` are half-open offsets into the saved plain text, measured in UTF-16 code units. JavaScript selection offsets already use this unit. Python validation uses a dedicated UTF-16 boundary helper so emoji and other non-BMP characters have identical offsets on both sides.
- `label` is the exact snapshot inserted into the text. It is `@` plus Wagtail's display name for the user, with line breaks and runs of whitespace collapsed. If that result has no usable name, `user.get_username()` is used as the fallback. On an email-as-username model this fallback is intentionally the email-valued canonical identity; the API does not add a second email field. A label longer than 255 UTF-16 code units is truncated on a code-point boundary and ends with a single ellipsis within that limit. The server supplies and validates this value for new occurrences.

The list is stored sorted by `(start, end, key)`. Occurrence keys must be unique within a message, ranges must not overlap, and every range must fall on UTF-16 code-point boundaries and select text exactly equal to `label`.

Each comment or reply may contain at most 20 mention occurrences. A normalized label is limited to 255 UTF-16 code units using the deterministic truncation rule above, so overlong display names do not create a post-permission candidate window or hide later eligible results. The UTF-8 encoded mention field is limited to 16 KiB before JSON parsing. Repeated occurrences and duplicate display names are supported. Notifications are deduplicated by target user within a message, but the occurrences remain distinct for rendering and editing.

The JSON fields replace the proposed `CommentMention` relation and `notified_at` state. The primary migration is based on the current branch's migration graph and adds empty lists for existing rows. The 7.4 compatibility backport regenerates only the migration dependency or filename if its graph requires that mechanical difference; the operations and resulting schema remain identical. No data backfill from an unreleased schema is required. Removing the relation also removes the proposed `Comment.save()` workaround for reverse fields.

## Editing interaction

Comments and replies continue to use a native `<textarea>`. For query recognition, token characters are Unicode letters and numbers plus `_`, `.`, `+`, `-`, `'`, and `@`. An active query starts with an `@` at the beginning of the text or after a non-token character, then contains between 1 and 64 UTF-16 code units made only from token characters. Whitespace, a newline, or other punctuation closes it. These rules allow partial names, usernames, and email addresses while avoiding a trigger inside ordinary `person@example.com` text. Results match active Wagtail admin users by display name, username, or email, but the response contains only the identifier and display fields required by this control.

Selecting a result replaces the active `@query` range with the server-provided label and records its occurrence range. Multiple occurrences may target the same user. Because identity is carried by the occurrence record, users with identical labels remain unambiguous; a secondary username in each suggestion distinguishes them before selection.

The saved label remains ordinary selectable text in the textarea. The control reconciles ranges with every native text change using the edit delta between the previous and current value:

- An edit entirely before an occurrence shifts its range.
- An edit entirely after an occurrence leaves its range unchanged.
- An edit that intersects an occurrence removes its structured identity, leaving the resulting characters as ordinary text.

This intentionally avoids immutable token behavior. Backspace, selection replacement, cut, paste, mobile editing, and IME composition remain native. Native typing, deletion, cut, and paste participate in the browser's character undo stack; application-driven suggestion insertion is not promised as a native undo entry. The browser's undo and redo stack governs characters only, not the sidecar occurrence metadata. Once an edit intersects an occurrence, its identity is removed for the rest of that editing session; later undo can restore the label characters but not the identity. Selecting the user again is the explicit way to create a new occurrence key. Copying a mention produces plain text, and pasting that text does not create a mention until the user selects a suggestion again.

The suggestion popup follows the accessible textbox-with-listbox pattern while leaving focus in the native textarea:

- The textarea keeps its implicit multiline textbox role and has an accessible name, `aria-autocomplete="list"`, `aria-haspopup="listbox"`, `aria-controls`, and `aria-activedescendant` while an option is active. It does not use `role="combobox"` or `aria-expanded`, which are not valid for a native multiline textarea; opening, closing, loading, empty, and error states are conveyed through the visible popup and live status text.
- Results use listbox and option semantics with stable IDs and selected state.
- Arrow keys move the active result, Enter selects it, Escape closes the list, and Tab retains its normal focus-navigation behavior.
- Pointer selection works without losing the current text selection.
- Loading, empty, and error states are announced through a restrained status region.
- Results have visible focus/selection styling in normal and forced-colors modes.

Queries use a 200 ms debounce. Starting a new query aborts the preceding request, clears stale selectable results, and tags the request so an out-of-order response cannot replace newer results. Composition events do not trigger premature matching. Blur, form cancellation, comment deletion, and component unmount close the popup and abort outstanding work.

The hidden form field is rendered for every comment and reply form. Its model-form initial value is the canonical stored occurrence list, and the browser submits the complete hydrated list for every participating form, including unchanged forms. Unchanged metadata therefore compares equal to its relation-derived initial value. Cancel restores both the text and the occurrence list. Dirty-state comparisons include occurrence metadata so adding or removing a mention without otherwise changing the visible text is still a real edit. Older or custom clients that omit the field retain the backward-compatible preserve behavior defined below; the backend detects omission with an explicit sentinel rather than collapsing it to an empty list.

After save, the ordinary comment display renders the referenced ranges as styled mention spans. Deleted or inaccessible users keep their saved label and styling; they do not become broken links. Rendering operates on validated ranges and escapes the surrounding text and labels normally.

## Suggestions and permissions

There are two parent-scoped suggestion contexts:

- On an existing page, the endpoint resolves the saved page. Its candidate base is `page_permission_policy.users_with_permission_for_instance("change", page)`, which is Wagtail 7.4's database-level expression of who can edit that instance, including the add-only owner rule and superusers.
- During page creation, the endpoint resolves the parent page and requested child model. A shared future-child candidate service mirrors the same policy from `GroupPagePermission` rows on `parent.get_ancestors(inclusive=True)`: users with `change` permission are eligible, superusers are eligible, and a user with only `add` permission is eligible only when that user will own the child. The create action then saves the child provisionally inside the same atomic transaction, rechecks every newly selected target with `users_with_permission_for_instance("change", page)`, and commits the page, comments, and mentions only if that recheck succeeds.

The existing-page endpoint requires the same authenticated-user and `page.permissions_for_user(request.user).can_edit()` gate as the page edit view. The create endpoint requires the same parent permission, child-model `can_create_at`, and page-type checks as the Wagtail 7.4 create view. Both return no results when `WAGTAILADMIN_COMMENTS_ENABLED` is false or the resolved edit handler has no `CommentPanel`. A request cannot broaden the parent, page, content type, or model scope encoded by its URL and server-side view context.

Candidates must be active, have usable Wagtail admin access, and pass the relevant page permission check. A missing email address does not invalidate the visible mention, but it prevents email delivery. This is consistent with comments being collaboration metadata rather than an access-control mechanism.

The candidate service expresses page permission, active status, and `wagtailadmin.access_admin` membership as Django database permission filters before applying search, `distinct()`, deterministic ordering by the configured username field and primary key, and a 10-row slice. This intentionally follows Wagtail's database-backed page/admin permission policies rather than attempting to execute arbitrary dynamic authentication-backend `has_perm()` logic in a queryset. There is no pre-permission candidate window and therefore no false-negative window or per-result permission query. The endpoint independently enforces the 64-UTF-16-unit query limit. Empty queries do not enumerate all users. UUID and other custom primary keys are serialized without URL pre-quoting or double encoding.

The response uses the exact wire shape `{"results": [{"id": "canonical-pk", "label": "@Display name", "username": "secondary-name"}]}`. `username` is omitted when `user.get_username()` does not add a distinct disambiguator. The response does not add a separate email field, user-edit URL, notification preference, or permission detail. Email can be a search input without becoming an additional response field; on an email-as-username model the canonical username/display value can itself be an email address.

## Form validation and persistence

Mention payloads are validated before page revisions, workflow submissions, publish actions, or comment notifications are committed. Validation is shared by comments and replies and enforces:

- The raw field is no larger than 16 KiB in UTF-8 before parsing.
- The outer value is a list and every occurrence is a dictionary containing exactly the supported scalar fields.
- Occurrence keys are valid UUIDs and unique within the message.
- User IDs are valid for the configured user primary-key field; aliases such as numeric `1` and string `"1"` cannot produce duplicate canonical targets by accident.
- Offsets are integers, sorted, non-overlapping, bounded, and aligned to UTF-16 code-point boundaries.
- The selected text exactly matches each saved label, and the label is no longer than 255 UTF-16 code units.
- No message exceeds 20 occurrences.
- Newly added occurrences reference a current eligible candidate and use the exact current server-generated label.

Existing occurrences are compared by `key`. A retained occurrence may shift as surrounding text changes, but its canonical user ID and label cannot change under the same key. It is validated for structure, range, and text integrity but is not re-authorized against the target's current account or page permissions. This prevents permission drift, deactivation, deletion, or renaming from blocking unrelated edits. Changing a target or label requires a new occurrence key and therefore current authorization.

Form omission and explicit clearing have different meanings:

- If the mention field is absent because the client did not edit or does not support mentions, preserve the stored list.
- If the field is present with an empty list, remove every occurrence from that message.

An unchanged comment or reply owned by another user must not become changed merely because the form was submitted. Allowed resolve and reposition operations preserve its mention metadata. Unauthorized text or occurrence edits continue to use the existing comment authorization errors.

Validated mention JSON is assigned to the comment or reply before its normal save. The page revision, comment objects, reply objects, occurrence metadata, and audit entry participate in the same transaction boundary. A malformed or unauthorized occurrence produces a form error and no partial revision, publish, workflow action, or notification.

## Serialization, rendering, and privacy

The comment API serializes occurrence lists independently for comments and replies. Each occurrence already contains the only data needed for presentation: a stable target identifier, safe snapshot label, and validated range. It does not bulk-load referenced users or emit a mention-user map. Existing author serialization retains its pre-feature name/avatar contract and gains no mention-specific email addresses or user-management URLs.

Mention spans are presentation, not authorization, and are never linked to admin user records. Deleting a target user therefore changes neither the serialized occurrence nor its styling; notification code resolves users only for newly added targets during validation.

Server-rendered email and HTML must not trust the JSON label as markup. All text is escaped, and range slicing uses the same UTF-16 helper used by validation.

## Notifications

Notification planning happens after validation and successful persistence and delivery is scheduled with `transaction.on_commit`. One recipient-specific payload is built by merging:

- global page-comment subscribers,
- participants in affected comment threads under the existing rules, and
- users newly mentioned in an affected comment or reply.

"Newly mentioned" is the set of target users associated with new occurrence keys compared with the saved pre-edit list. Moving a retained occurrence does not notify again. Removing and later re-adding a user creates a new occurrence key and may notify again. Multiple new occurrences for the same user in one message produce one direct-mention reason.

Recipient deduplication occurs only after all reasons and affected messages have been merged. Consequently, a user who is both subscribed and directly mentioned receives one email containing the complete relevant set and explicit reason metadata; a notification for comment A cannot suppress their direct mention in comment B. The actor never receives mail for their own action.

The existing updated-comments notification preference applies to mention mail. Inactive users, deleted users, users with no deliverable email address, and users who opted out remain visibly mentioned but receive no email.

The notification template contract is exact and translatable:

- If the payload contains a direct mention, the subject source string is `{{ editor }} mentioned you in comments on "{{ title }}"`. Otherwise the existing updated-comments subject is unchanged.
- A mention-bearing body begins with `{{ editor }} mentioned you in comments on "{{ title }}".`
- A `Mentions:` section comes first. A top-level occurrence is rendered as `Comment: "{{ comment.text }}"`; a reply is rendered as `Reply to "{{ comment.text }}": "{{ reply.text }}"` so its thread context is unambiguous.
- Remaining existing sections follow in their current order: `New comments:`, `Resolved comments:`, `Deleted comments:`, and `New replies:`. A message already shown in `Mentions:` is omitted from a later section for that recipient, so it appears exactly once.
- Within a section, messages retain the formset change order, and occurrence order does not affect message order. The HTML template mirrors the same headings and ordering.
- The existing page-edit link and normal Wagtail mail context are retained.

An edited mentioned message is therefore never presented as a new comment, while a recipient who has both subscription and mention reasons still receives every relevant changed message in one email.

There is no per-occurrence `notified_at` flag. Wagtail attempts at most one email per recipient after each successful save. Send failures are logged under the existing email failure policy and are not converted into a retry state by this feature. This avoids marking unsent rows as delivered while remaining consistent with the current non-durable comment mail system.

Audit data for comment and reply creation or edit includes added and removed mention user IDs and occurrence keys. It contains stable identifiers rather than email addresses and does not log search queries.

## Failure behavior

- A suggestion failure leaves typed text untouched, closes or marks the list unavailable, and allows ordinary comment editing and saving.
- A target disappearing between suggestion and submit produces a validation error for a new occurrence. The page and comment remain unsaved rather than silently changing the intended recipient.
- A target losing access between child-page suggestion and the provisional child save leaves the label as ordinary submitted text only if the user explicitly removes the structured occurrence; otherwise validation reports that the new mention is no longer eligible and the atomic create transaction rolls back.
- A retained target disappearing after an earlier save does not block later page saves.
- An email failure does not roll back an already committed page or comment.
- Invalid stored JSON is not expected because the field is new, but read paths are defensive. Serialization and model-form initialization run the same per-entry sanitizer: valid entries are retained, invalid entries are omitted from decoration and browser state, and a warning records the message ID without logging comment text or the malformed payload. The sanitized initial value keeps an unchanged other-author form unchanged. An omitted field preserves the stored value; the next authorized save that changes that comment or reply persists the sanitized list atomically. No malformed entry is ever interpolated into HTML or email, and all new writes remain strictly validated.

## Compatibility and branch strategy

PR 1 remains based on its current Wagtail 8-era `main` branch. Existing mention code may be replaced freely, but unrelated upstream code and commits remain untouched. Core range handling, validation, candidate selection, form semantics, serialization, notifications, and frontend state live in modules and interfaces shared with Wagtail 7.4; they must not depend on Wagtail 8-only page-viewset behavior.

Routing is the deliberate compatibility seam. The primary branch registers the shared suggestion views through Wagtail 8's `PageViewSet` structure. The 7.4 backport registers those same views through the direct page edit/create URL configuration used by `stable/7.4.x`. Any other source difference discovered during the backport is treated as a compatibility defect unless it is limited to migration dependency numbering or test-file placement.

Before implementation and again before final verification, the official branches are refreshed with `git fetch --no-tags https://github.com/wagtail/wagtail.git +refs/heads/main:refs/remotes/upstream/main +refs/heads/stable/7.4.x:refs/remotes/upstream/stable/7.4.x`, and both fetched commit IDs are recorded. Compatibility is then proved continuously on a committed local `compat/comment-mentions-7.4` branch in a separate worktree based on that exact 7.4 commit. The current feature diff relative to PR 1's recorded base is exported and applied after each coherent backend/frontend slice; it is not inferred from the stale pre-redesign commits.

The compatibility branch is retained through final handoff. A committed report at `docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md` records the primary base/head, official 7.4 base/head, runtime-feature patch checksum, commit mapping, `git range-diff` output or an explicit explanation where a one-to-one commit mapping is impossible, file-level name/status and stat comparisons, every adaptation, and all verification commands and results. The runtime patch and equivalence comparison exclude primary-only design/plan/compatibility reports, pull-request administration, changelog, contributor, and release-note files. The report and local branch are the compatibility deliverable; a clean compile or theoretical API comparison is not sufficient. The report must show that runtime and test adaptations are limited to the declared routing, migration-dependency, or test-location seams, or identify a design defect that must be corrected on the primary branch.

Both branches must preserve their supported Python, Django, database, browser, and custom-user configurations rather than depending on PostgreSQL-only JSON operations, integer primary keys, or APIs introduced after 7.4.

The final PR branch contains only commits relevant to comment mentions, tests, and necessary user/developer documentation. Wagtail's contributor guide reserves `CHANGELOG.txt`, `docs/releases/8.0.md`, and `CONTRIBUTORS.md` updates for core committers after human review and acceptance, so this unreviewed contributor branch does not edit them; the pull request supplies suggested release-note and contributor copy for the accepting maintainer. Before publishing, its commit range is checked against the current upstream `main` merge base, while the compatibility worktree is separately checked against the current `stable/7.4.x` merge base. The pull request description uses `.github/PULL_REQUEST_TEMPLATE.md`, explains the behavior and architectural tradeoffs, highlights range validation, create-page authorization, notification merging, and the 7.4 backport evidence for careful review, and includes the required AI-assistance disclosure.

## Test strategy

Implementation is test-driven and covers the contract at five layers.

### Model and migration tests

- Existing comments and replies receive empty mention lists.
- Both models round-trip valid occurrence JSON across supported databases.
- Malformed stored entries are sanitized on read, warn without sensitive payload data, render only escaped plain text, do not make another author's form dirty, and are cleaned on the next authorized standard-browser save.
- The primary and 7.4-backport migration graphs each leave no pending migration and produce the same JSON-field schema.
- Saving comments no longer needs special handling for a reverse mention relation.

### Form, lifecycle, and endpoint tests

- Missing fields preserve metadata; explicit empty lists remove it; unchanged other-author forms remain unchanged.
- Retained mentions survive target rename, deactivation, deletion, and permission loss.
- Malformed JSON, wrong shapes, extra or missing fields, invalid UUID keys, invalid and aliased user IDs, duplicate keys, overlaps, unsorted ranges, out-of-bounds offsets, surrogate splits, forged labels, invisible mentions, labels over 255 UTF-16 units, fields over 16 KiB, and the 20-occurrence limit fail cleanly.
- UTF-16 validation covers emoji before and inside surrounding edits.
- Create-page GET succeeds with comments enabled and does not reverse a route with a missing page ID.
- Page create, draft save, autosave, publish, and submit-for-moderation persist valid mentions without partial saves on failure.
- Comment resolve and reposition preserve another author's mentions.
- Reply create, edit, remove, cancel, reload, and notification behavior match top-level comments.
- Existing-page and create-page suggestions enforce the exact 7.4 page-policy behavior for direct group permissions, inherited permissions, add-only ownership, and superusers; requester access; admin access; page comments enabled state; 64-unit queries; deterministic 10-result limits; complete eligible results without a candidate window; empty results; inactive users; UUID/custom primary keys; and bounded query counts.

### Notification and audit tests

- Actor exclusion, preference opt-out, inactive users, missing email, subscriber overlap, thread-participant overlap, repeated occurrences, and multiple changed messages produce the intended recipient payloads.
- A global notification for one message cannot suppress a direct mention in another.
- Direct-mention and combined-reason subjects, introductory copy, section ordering, comment/reply representation, and de-duplication match the exact translatable template contract without calling an edit a new comment.
- Failed delivery follows the declared no-retry contract and does not affect saved data.
- Audit records distinguish mention additions and removals for comments and replies without exposing email addresses.

### Frontend unit tests

- Query recognition, the 64-unit client limit, 200 ms debounce, server-result selection, and exact always-rendered hidden-field payloads work for comments and replies.
- Range reconciliation shifts, retains, or drops occurrences for edits before, after, and through labels.
- Duplicate names, repeated targets, emoji, multiline input, selected-range paste, cut, native text undo/redo, the declared non-restoration of dropped mention identity, and cancel/hydration behavior are covered.
- Keyboard navigation, Escape, ordinary Tab behavior, pointer selection, ARIA state, status messages, and forced-colors classes are deterministic.
- Debounce, abort, stale and out-of-order responses, malformed responses, composition, blur, deletion, and unmount cannot insert stale data or leak requests.

### Browser and regression tests

- Keyboard-only users can create, edit, and remove mentions in a comment and reply, save, autosave, reload, and see the same result.
- Multiline text, emoji, selection replacement, paste, caret movement, and character undo behave as native textarea operations, with the specified sidecar non-restoration behavior asserted separately.
- Automated accessibility checks run with the popup closed, loading, empty, and populated.
- The comment mention Playwright regression runs in Chromium in automated verification. Before the pull request is published, the same keyboard, multiline, paste, emoji, reload, and popup-accessibility scenario is run manually in current Firefox and the result is recorded in the pull request. WebKit/Safari remains an encouraged reviewer check rather than a release gate because the repository's current integration setup is Chromium-only.

### Cross-version verification matrix

The primary Wagtail 8-era branch and committed 7.4 compatibility branch each run:

- the complete focused comment, reply, create/edit page, suggestion, notification, audit, permission, migration, serialization, and custom-user backend suites;
- the surrounding existing page create/edit and comment regression suites;
- the frontend mention unit suites, TypeScript checks, ESLint, formatting, style linting, and production build;
- migration consistency checks; and
- the Chromium mention Playwright scenario with Axe checks, including both edit-page and create-page suggestion routing.

The 7.4 branch additionally runs its Django 5.2 and Django 6.0 test environments and UUID email-user configuration. The primary branch runs its repository-declared Django/default-user matrix plus the UUID email-user configuration. The required manual Firefox scenario runs against the primary branch; the automated 7.4 Chromium run covers the version-specific browser routing seam.

## Acceptance criteria

The implementation is ready when:

1. The complete cross-version matrix above passes on the primary Wagtail 8-era branch and committed compatibility branch based on a freshly fetched and recorded official `stable/7.4.x` commit.
2. Existing page create/edit, comment, reply, notification, audit, and permission suites pass unchanged or with intentional assertions added on both branches.
3. Django 5.2 and Django 6.0 pass on 7.4, and each branch's UUID email-user configuration passes.
4. Frontend type checking, linting, formatting, style linting, production build, Chromium mention regression, and Axe checks pass on both branches; the required primary-branch Firefox manual scenario and version are recorded.
5. Migration checks pass on both branches and produce the same schema operations without database-specific behavior outside Wagtail's supported contract.
6. The retained compatibility branch and committed report contain the recorded OIDs, patch checksum, commit/diff comparison, exhaustive adaptation list, and command output required to reproduce the compatibility conclusion.
7. A final diff and commit-history review confirms PR 1 remains based on current upstream `main`, contains no unrelated commits, leaves core-committer release files unchanged while providing suggested copy in the PR, and uses the required pull request template and AI disclosure; the compatibility report confirms that the 7.4 runtime/test backport differs only at the declared compatibility seams.
