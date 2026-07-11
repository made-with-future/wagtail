# Comment mentions for Wagtail 7.4 and Wagtail 8.0 prerelease

Status: approved design, including required Wagtail 7.4 and Wagtail 8.0 beta-or-later prerelease support

Primary development base: the current pull-request branch on Wagtail 8.0 alpha

Compatibility floor: Wagtail `stable/7.4.x`, including Django 5.2 and 6.0 and Wagtail's supported custom user models

Required 8.0 target: an official Wagtail 8.0 beta-or-later prerelease (`beta` or `rc`), or Wagtail 8.0 final if it is released before verification completes. Alpha/main verification is useful during development but does not satisfy this release gate.

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
- The custom `contenteditable` implementation does not preserve reliable multiline text, selection replacement, paste, undo, IME composition, mobile input, or assistive-technology behavior. It also has stale-query and stale-caret races and recreates entity tracking that Draftail already provides.
- The shared author serialization exposes commenter email addresses and user-management URLs to page editors who do not necessarily have permission to manage users.
- The suggestion endpoint does unbounded filtering with per-result permission checks, has avoidable query growth, and remains reachable when comments are disabled.
- Replies cannot contain mentions, mention-only edits are missing from audit data, and edited comments can be presented as "new comments" in email.

The implementation will be rebuilt on the current pull-request branch. Feature logic and data contracts will remain independent of Wagtail 8-only routing APIs, a real backport worktree will prove that the result works on `stable/7.4.x` with only the expected route-registration, migration-dependency, and test-location adaptations, and final verification will run after the primary branch is based on an official Wagtail 8.0 beta-or-later prerelease.

## Goals

- Support creating, editing, removing, rendering, serializing, auditing, and notifying mentions in both top-level comments and replies.
- Support the full page lifecycle: page creation, draft save, autosave, publish, submit for moderation, and later edit.
- Preserve normal comment and page-save behavior when an existing mentioned user is renamed, deactivated, deleted, or loses page permission.
- Treat mention identity and text placement as structured server-validated data, without parsing saved prose to recover identity.
- Preserve reliable character editing, keyboard access, screen-reader semantics, mobile input, IME composition, paste, selection, and undo behavior by using Wagtail's established Draftail entity model instead of a bespoke editor.
- Keep `Comment.text` and `CommentReply.text` as plain strings while rendering mention entities inline during editing and as styled spans after save.
- Hydrate the configured email field's current value as narrowly scoped mention metadata without expanding ordinary comment-author records or adding user-management URLs.
- Maintain exact-message relational indexes so a user's top-level comment and reply mentions can be queried efficiently without database-specific JSON lookups.
- Keep mention persistence atomic with the comment or reply save and make notification behavior deterministic.
- Work with integer, UUID, and converted custom user primary keys supported by Wagtail's test configurations.
- Bound suggestion and submitted-mention work to predictable limits.
- Support both Wagtail 7.4 and Wagtail 8.0 beta-or-later with the complete backend, frontend, migration, browser, and accessibility matrix.

## Non-goals

- Mentions do not grant page access, add users to workflows, subscribe users permanently, or bypass notification preferences.
- Saved mention text is not dynamically rewritten when a user's profile changes.
- Arbitrary pasted `@text` is not automatically converted into a mention.
- Cross-site, external-email, group, role, and team mentions are outside this change.
- Rich-text formatting inside comments is outside this change.
- A global email-versus-display-name mention-label setting is outside this change. The data model preserves label snapshots so such a setting can govern future mentions without rewriting existing comments.
- The first version will not link rendered mentions to the user-management interface. This avoids both permission-sensitive links and navigation away from unsaved page edits.
- Delivery retries and durable email outboxes are outside this change; mention mail follows Wagtail's existing comment-email delivery guarantees.
- This work does not publish a second pull request or release branch for 7.4. The required 7.4 deliverable is a retained, committed local compatibility branch plus reproducible evidence that the primary feature can be backported; publishing that branch requires separate authorization.

## Considered approaches

### Mini Draftail entities plus structured ranges

Use Draftail with no toolbar, formatting controls, links, or other rich-text features. Mention entities provide inline highlighting and established selection/entity behavior while the editor still extracts an ordinary plain-text value. The persisted occurrence sidecar makes the entity contract independently server-validatable and reconstructs the entities on hydration.

This follows the [Mini Draftail RFC](https://github.com/emilytoppm/rfcs/blob/d4cdf48e9a19e4c4bcb46df0e7c7cd9b1c3fe06f/text/000-mini-draftail.md): Draftail acts as an admin utility layer for entities attached to general text entry, without changing the database representation of the text field. It is the selected approach.

### Native textarea plus structured ranges

A native textarea would have the smallest editing surface and strongest direct browser guarantees. It cannot render styled spans around individual mentions, however, and requires application code to reconcile occurrence ranges after every edit. It is not selected because inline mention identity should remain visible while composing.

### Canvas, overlays, or bespoke contenteditable behavior

A canvas would require reimplementing text selection, caret movement, clipboard, undo, IME, mobile input, and assistive-technology semantics. A textarea overlay would add fragile scroll, wrapping, zoom, and forced-colors synchronization. Hardening the current custom `contenteditable` would retain the same browser-specific risk. These approaches are not selected.

## Data model

`Comment` and `CommentReply` each gain a `mentions` JSON field with `default=list`. Each list entry represents one occurrence in that individual message:

```json
{
  "key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb",
  "user_id": "42",
  "start": 14,
  "end": 31,
  "label": "@jane@example.com"
}
```

- `key` is a client-generated UUID for the occurrence. It remains stable while an occurrence is retained and distinguishes a retained occurrence from a newly added occurrence.
- `user_id` is the target user's primary key serialized through a model-field-supported string representation. Some custom fields accept distinct display and prepared strings for the same primary key; validation preserves a submitted representation that round-trips, while lookup, deduplication, and metadata hydration compare the field's prepared identity. Server logic never assumes an integer.
- `start` and `end` are half-open offsets into the saved plain text, measured in UTF-16 code units. JavaScript selection offsets already use this unit. Python validation uses a dedicated UTF-16 boundary helper so emoji and other non-BMP characters have identical offsets on both sides.
- `label` is the exact snapshot inserted into the plain text. For this release it is `@` plus the user's current configured email value, with line breaks and runs of whitespace collapsed. A blank email falls back to Wagtail's display name and then `user.get_username()`. A future global label-mode setting may choose the display name first for newly inserted mentions, but it never rewrites saved labels. A label longer than 255 UTF-16 code units is truncated on a code-point boundary and ends with a single ellipsis within that limit. The server supplies and validates this value for new occurrences.

The list is stored sorted by `(start, end, key)`. Occurrence keys must be unique within a message, ranges must not overlap, and every range must fall on UTF-16 code-point boundaries and select text exactly equal to `label`.

Each comment or reply may contain at most 20 mention occurrences. A normalized label is limited to 255 UTF-16 code units using the deterministic truncation rule above, so overlong email, display-name, or username values do not create a post-permission candidate window or hide later eligible results. The UTF-8 encoded mention field is limited to 16 KiB before JSON parsing. Bound-form redisplay preserves the submitted string without parsing it a second time, and parser digit-limit, recursion, encoding, or shape errors all become the same translated validation error. Repeated occurrences and duplicate display labels are supported. Notifications are deduplicated by target user within a message, but the occurrences remain distinct for rendering and editing.

The occurrence JSON is the authoritative per-message editing, rendering, audit, and notification record. Two normalized lookup models provide efficient inverse queries without attempting cross-database containment queries over JSON arrays:

- `CommentMention(comment, user)` has one row per distinct user referenced by a top-level comment, unique on `(comment, user)`.
- `CommentReplyMention(reply, user)` has one row per distinct user referenced by a reply, unique on `(reply, user)`.

Both foreign keys on both lookup models use `related_name="+"`; inverse queries go through `CommentMention.objects` or `CommentReplyMention.objects` rather than adding reverse fields to `Comment`, `CommentReply`, or the user model. Repeated occurrences for the same user create one lookup row. A reply lookup reaches its thread through the existing `CommentReply.comment` relation. The lookup rows contain no range, label, occurrence key, delivery state, or `notified_at` field and are never used to decide whether a mention is newly added. They are synchronized from validated JSON inside the same transaction as the message save. Deleting a user cascades the lookup rows while leaving the saved JSON label and range intact; a deleted target therefore remains visible as historical text but no longer has an inverse user lookup.

The primary migration replaces the prototype relation with both JSON fields and the two lookup models based on the current branch's migration graph. The 7.4 compatibility backport changes only the migration dependency or filename if its graph requires that mechanical difference; the operations and resulting schema remain identical. No data backfill from an unreleased schema is required. The derived lookup models do not participate in `Comment.save()` field discovery, so the prototype's reverse-relation workaround is removed.

## Editing interaction

Comments and replies use a Mini Draftail editor: `DraftailEditor` with no toolbar, inline styles, block types beyond ordinary paragraphs, links, or other rich-text features. Its only entity type is `MENTION`. The editor extracts plain text with newline separators for `Comment.text` or `CommentReply.text`; raw Draft.js content is never persisted. Hydration reconstructs Draft.js entity ranges from the validated occurrence JSON. This keeps the model and all existing plain-text consumers unchanged while showing highlighted mention spans during composition.

Each Draft.js mention entity carries the occurrence `key`, canonical `user_id`, and snapshot `label` and uses Draft.js `MUTABLE` mutability. After every editor change, normalization compares each entity's current text with its snapshot label and immediately removes the complete mismatched entity association while preserving the resulting characters as ordinary text. The normalized content is installed with `EditorState.set` in the same undo frame as the text edit, so association removal does not create a second undo entry. Current email metadata is hydrated separately and is not entity identity or saved content. For query recognition, token characters are Unicode letters and numbers plus `_`, `.`, `+`, `-`, `'`, and `@`. An active query starts with an `@` at the beginning of the current plain text or after a non-token character, then contains between 1 and 64 UTF-16 code units made only from token characters. Whitespace, a newline, or other punctuation closes it. After finding that candidate token, the editor rejects it if any character in its range belongs to a live `MENTION` entity. This includes a collapsed caret at the entity's half-open end, where the candidate token covers the existing entity text. These rules allow partial names, usernames, and email addresses while avoiding triggers inside ordinary `person@example.com` text or already-selected mentions.

Selecting a result replaces the active `@query` range with the server-provided label and applies a new `MENTION` entity with a client-generated occurrence key. Multiple occurrences may target the same user. Because identity is carried by the occurrence record, users with identical labels remain unambiguous; current email and a secondary username can distinguish them before selection.

Draft.js maintains entity positions as text is edited. Serialization flattens ordinary blocks with `\n`, walks the resulting entity ranges, converts block-local offsets to absolute UTF-16 offsets, and emits the canonical sorted occurrence list. An edit entirely before or after an occurrence shifts or preserves its entity range through Draft.js. An edit that changes any part of a mention makes its entity text differ from the snapshot label; same-frame normalization then removes the full remaining association while leaving all resulting characters as ordinary text.

Draftail's editor state owns text and entity undo/redo together. Suggestion insertion is one undoable editor change, and undoing or redoing an intersecting edit restores or removes the associated identity consistently with the text. Cut and paste are normalized through the plain-text path: copied mention text is ordinary text when pasted and does not gain an entity until the user selects a suggestion. Multiline text, selection replacement, mobile input, and IME composition use Draftail and Draft.js behavior rather than custom DOM range or caret walkers.

The suggestion popup follows the accessible textbox-with-listbox pattern while leaving focus in Draftail's editing surface:

- The Draftail editing surface keeps its multiline textbox semantics and accessible name. The mention-editor wrapper applies and tests the list-autocomplete relationship, popup ownership, expanded state, and active-option announcement on the actual focusable editing surface rather than adding a second input.
- Results use listbox and option semantics with stable IDs and selected state.
- Arrow keys move the active result, Enter selects it, Escape closes the list, and Tab retains its normal focus-navigation behavior.
- Pointer selection works without losing the current text selection.
- Loading, empty, and error states are announced through a restrained status region.
- Results have visible focus/selection styling in normal and forced-colors modes.

Queries use a 200 ms debounce. Starting a new query aborts the preceding request, clears stale selectable results, and tags the request so an out-of-order response cannot replace newer results. Composition events do not trigger premature matching. Blur, form cancellation, comment deletion, and component unmount close the popup and abort outstanding work.

The hidden form field is rendered for every comment and reply form. Its model-form initial value is the canonical stored occurrence list, and the browser submits the complete entity-derived list for every participating form, including unchanged forms. Unchanged metadata therefore compares equal to its model-derived initial value. Cancel restores the prior Draftail state, plain text, and occurrence list. Dirty-state comparisons include canonical occurrence metadata so adding or removing a mention without otherwise changing visible text is still a real edit. Older or custom clients that omit the field retain the backward-compatible preserve behavior defined below; the backend detects omission with an explicit sentinel rather than collapsing it to an empty list.

Successful create/edit JSON hydration rebases current values as the new originals, clears processed removals and errors, and preserves the existing success focus behavior. A create/edit JSON validation failure may instead carry safely serialized bound `comments`, with only a generic per-message `mention_error` attached to the affected comment or reply. Rejected hydration preserves the prior originals and removal state, retains genuinely dirty working values, keeps rejected unsaved messages, and restores each message's exact edit or create mode. Only structurally valid submitted occurrence lists rejected for target eligibility or permission are retained as working values. Structurally invalid raw occurrence payloads, including malformed, parser, size, or shape failures, are never echoed; those responses use sanitized initial values or omit `comments` when safe serialization is unavailable. The editor renders a generic message visibly with alert semantics and `aria-describedby`; target and permission details remain private.

During editing, Draftail's mention decorator renders each entity as a styled span. After save, the ordinary comment display renders the referenced ranges with the same visual treatment. Deleted or inaccessible users keep their saved label and styling; they do not become broken links. Rendering operates on validated ranges and escapes the surrounding text and labels normally.

## Suggestions and permissions

There are two parent-scoped suggestion contexts:

- On an existing page, the endpoint resolves the saved page. Its candidate base is `page_permission_policy.users_with_permission_for_instance("change", page)`, which is Wagtail 7.4's database-level expression of who can edit that instance, including the add-only owner rule and superusers.
- During page creation, the endpoint resolves the parent page and requested child model. A shared future-child candidate service mirrors the same policy from `GroupPagePermission` rows on `parent.get_ancestors(inclusive=True)`: users with `change` permission are eligible, superusers are eligible, and a user with only `add` permission is eligible only when that user will own the child. The create action then saves the child provisionally inside the same atomic transaction, rechecks every newly selected target with `users_with_permission_for_instance("change", page)`, and commits the page, comments, and mentions only if that recheck succeeds.

The existing-page endpoint requires the same authenticated-user and `page.permissions_for_user(request.user).can_edit()` gate as the page edit view, and rejects a stale page content type whose concrete model class can no longer be loaded. The create endpoint requires the same parent permission, child-model `can_create_at`, and page-type checks as the Wagtail 7.4 create view. Its route selects the viewset from the requested child app/model, not the parent page type. Both return no results when `WAGTAILADMIN_COMMENTS_ENABLED` is false or the resolved edit handler has no `CommentPanel`. A request cannot broaden the parent, page, content type, or model scope encoded by its URL and server-side view context.

Candidates must be active, have usable Wagtail admin access, and pass the relevant page permission check. A missing email address falls back to display name or username for the visible label and prevents email delivery. This is consistent with comments being collaboration metadata rather than an access-control mechanism.

The candidate service expresses page permission, active status, and `wagtailadmin.access_admin` membership as Django database permission filters before applying search, `distinct()`, deterministic ordering by the configured username field and primary key, and a 10-row slice. This intentionally follows Wagtail's database-backed page/admin permission policies rather than attempting to execute arbitrary dynamic authentication-backend `has_perm()` logic in a queryset. There is no pre-permission candidate window and therefore no false-negative window or per-result permission query. The endpoint independently enforces the 64-UTF-16-unit query limit. Empty queries do not enumerate all users. UUID and other custom primary keys are serialized without URL pre-quoting or double encoding.

The response uses the exact wire shape `{"results": [{"id": "canonical-pk", "label": "@current@example.com", "email": "current@example.com", "username": "secondary-name"}]}`. `email` is the current configured email-field value and may be an empty string when the label used a fallback. `username` is omitted when `user.get_username()` does not add a distinct disambiguator. The response never adds a user-edit URL, notification preference, or permission detail. Only active, currently eligible candidates appear in this response.

## Form validation and persistence

Mention payloads are validated before page revisions, workflow submissions, publish actions, or comment notifications are committed. Validation is shared by comments and replies and enforces:

- The raw field is no larger than 16 KiB in UTF-8 before parsing.
- The outer value is a list and every occurrence is a dictionary containing exactly the supported scalar fields.
- Occurrence keys are valid UUIDs and unique within the message.
- User IDs convert through the configured user primary-key field and pass that field's validators in prepared form; aliases such as numeric `1` and string `"1"`, or distinct prepared/display strings, cannot produce duplicate targets by accident or reach the database adapter out of range.
- Offsets are integers, sorted, non-overlapping, bounded, and aligned to UTF-16 code-point boundaries.
- The selected text exactly matches each saved label, and the label is no longer than 255 UTF-16 code units.
- No message exceeds 20 occurrences.
- Newly added occurrences reference a current eligible candidate and use the exact current server-generated label. Resolution is occurrence-order aligned across the flattened form batch because occurrence keys are unique only within one individual message; invalid indices map back to the exact comment or reply field.

Existing occurrences are compared by `key`. A retained occurrence may shift as surrounding text changes, but its canonical user ID and label cannot change under the same key. It is validated for structure, range, and text integrity but is not re-authorized against the target's current account or page permissions. This prevents permission drift, deactivation, deletion, or renaming from blocking unrelated edits. Changing a target or label requires a new occurrence key and therefore current authorization.

Form omission and explicit clearing have different meanings:

- If the mention field is absent because the client did not edit or does not support mentions, preserve the stored list.
- If the field is present with an empty list, remove every occurrence from that message.

An unchanged comment or reply owned by another user must not become changed merely because the form was submitted. Allowed resolve and reposition operations preserve its mention metadata. Unauthorized text or occurrence edits continue to use the existing comment authorization errors.

Validated mention JSON is assigned to the comment or reply before its normal save. After message primary keys exist, the distinct current target-user set synchronizes the appropriate `CommentMention` or `CommentReplyMention` lookup rows inside the same transaction. Prepared/display aliases resolve to one user and one lookup row. Repeated occurrences do not create duplicate rows, a retained occurrence whose user has since been deleted remains in JSON without recreating a lookup row, and deleting a parent comment skips all nested reply synchronization after the database cascade. The page revision, comment objects, reply objects, occurrence metadata, lookup rows, and audit entry participate in the same transaction boundary. A malformed or unauthorized occurrence produces a form error and no partial revision, publish, workflow action, lookup update, or notification.

## Serialization, rendering, and privacy

The comment API serializes occurrence lists independently for comments and replies. Each occurrence contains the stable target identifier, safe snapshot label, and validated range needed to reconstruct the Draftail entity. In one bulk user query across the sanitized occurrence IDs, it also emits a separate exact map of current metadata:

```json
{
  "mentioned_users": {
    "42": {"email": "current@example.com"}
  }
}
```

The map contains only still-existing users referenced by a serialized occurrence and only the configured email-field value; missing users are omitted and blank email values remain blank. Each entry is keyed by the exact `user_id` string carried by the occurrence, so two supported aliases can hydrate the same current user without rewriting stored JSON. All user identifiers in the wire payload are strings. This current email is presentation metadata, is never written into saved text or occurrence JSON during hydration, and does not make a form dirty. Existing author serialization retains its pre-feature name/avatar contract, keeps the current editor available for new-comment identity, and gains no email addresses or user-management URLs. Mention-only targets do not expand `authors`. The mention payload likewise contains no user-management URL, notification preference, or permission details.

Mention spans are presentation, not authorization, and are never linked to admin user records. Deleting a target user therefore changes neither the serialized occurrence nor its styling; it removes the inverse lookup row and live metadata entry. Renaming a user or changing their email updates only the separately hydrated metadata, not the snapshot label. Notification code resolves users from newly added occurrence targets rather than treating lookup-row creation as a notification event.

Server-rendered HTML must not trust message text or a JSON label as markup and uses normal Django autoescaping. The subject and text alternative are plain MIME text rather than markup, so they retain literal readable values instead of HTML-entity encoding ordinary punctuation. Range slicing uses the same UTF-16 helper used by validation.

## Notifications

Notification planning happens after validation and successful persistence and delivery is scheduled with `transaction.on_commit`. One recipient-specific payload is built by merging:

- global page-comment subscribers,
- participants in affected comment threads under the existing rules, and
- users newly mentioned in an affected comment or reply.

Global subscribers receive the existing new/resolved/deleted-comment and new-reply sections. Thread-only participants retain Wagtail's narrower existing scope: resolved comments and new replies only for threads where they authored the comment or an extant reply. A page subscription with comment notifications disabled removes only the subscription reason; it does not suppress an independent direct mention.

"Newly mentioned" is the set of target users associated with new occurrence keys compared with the saved pre-edit list. Targets are resolved from each added occurrence's `user_id` through the configured primary-key field, including prepared/display aliases and UUIDs; occurrence keys and inverse lookup-row creation are never used to resolve targets or infer novelty. Moving a retained occurrence does not notify again. Removing and later re-adding a user creates a new occurrence key and may notify again. Multiple new occurrences for the same user in one message produce one direct-mention reason.

Recipient deduplication occurs only after all reasons and affected messages have been merged into independently owned per-recipient lists. Consequently, pruning a mentioned message for one recipient cannot alter another recipient's ordinary sections, and a user who is both subscribed and directly mentioned receives one email containing the complete relevant set and explicit reason metadata; a notification for comment A cannot suppress their direct mention in comment B. Exact message identity, including comment-versus-reply type and unsaved/deleted object identity, governs deduplication. The actor never receives mail for their own action.

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
- After a provisional create rollback, Wagtail rebuilds the page, subscription, bound form, nested comment/reply instances, and refreshed parent tree state before redisplay. The exact generic comment/reply mention error and structurally valid submitted occurrence list remain attached to the rebuilt form; no rolled-back PK/path/depth state leaks into the response.
- A retained target disappearing after an earlier save does not block later page saves.
- A retained target rename, deactivation, or permission loss leaves the saved occurrence and inverse lookup intact without producing a new comment audit entry, mention delta, or notification. Target deletion leaves the saved occurrence snapshot intact but cascades the inverse lookup; hydration provides no live metadata for the missing target and produces no comment audit entry, mention delta, or notification.
- A comment/reply mention field error prevents an invalid-form workflow-cancel request from cancelling the workflow. An unrelated invalid page field retains Wagtail's existing cancel-anyway behavior.
- A `before_publish_page` response retains its existing semantics: the draft revision and synchronized mention indexes commit, while publish, mention audit, and mention notifications are suppressed.
- An email failure does not roll back an already committed page or comment.
- Atomic guarantees cover Wagtail database state and mention email callbacks. External side effects performed directly by third-party hooks or signal receivers are outside that rollback guarantee.
- Invalid stored JSON is not expected because the field is new, but read paths are defensive. Serialization and model-form initialization run the same per-entry sanitizer: valid entries are retained, invalid entries are omitted from decoration and browser state, and a warning records the message ID without logging comment text or the malformed payload. The sanitized initial value keeps an unchanged other-author form unchanged. An omitted field preserves the stored value; the next authorized save that changes that comment or reply persists the sanitized list atomically. No malformed entry is ever interpolated into HTML or email, and all new writes remain strictly validated.

## Compatibility and branch strategy

PR 1 remains based on the Wagtail 8.0 `main` branch. Existing mention code may be replaced freely, but unrelated upstream code and commits remain untouched. The current checkout reports 8.0 alpha, so its results are provisional. The current release checkpoint only records freshly observed official branch and immutable tag state as `PENDING_OFFICIAL_8_RELEASE` or `REPLAN_REQUIRED`; it performs no rebase, integration, compatibility-report update, push, or publication. Core range handling, validation, candidate selection, form semantics, serialization, notifications, and frontend state live in modules and interfaces shared with Wagtail 7.4; they must not depend on Wagtail 8-only page-viewset behavior.

Routing is the deliberate compatibility seam. The primary branch registers the shared suggestion views through Wagtail 8's `PageViewSet` structure. The 7.4 backport registers those same views through the direct page edit/create URL configuration used by `stable/7.4.x`. Any other source difference discovered during the backport is treated as a compatibility defect unless it is limited to migration dependency numbering or test-file placement.

Before implementation, the official branches are refreshed with `git fetch --no-tags https://github.com/wagtail/wagtail.git +refs/heads/main:refs/remotes/upstream/main +refs/heads/stable/7.4.x:refs/remotes/upstream/stable/7.4.x`, and both fetched commit IDs plus the primary Wagtail version tuple are recorded. Compatibility is then proved continuously on a committed local `compat/comment-mentions-7.4` branch in a separate worktree based on that exact 7.4 commit. The current feature diff relative to PR 1's recorded base is exported and applied after each coherent backend/frontend slice; it is not inferred from the stale pre-redesign commits. Final completion still requires freshly verified evidence on official `stable/7.4.x` and an immutable official Wagtail 8.0 beta, release-candidate, or final ref, with exact OIDs and versions recorded. If the checkpoint observes that release state or any other upstream change, it records `REPLAN_REQUIRED` and stops; an independently reviewed future plan must authorize and define any rebase, integration, two-release rerun, report refresh, or publication.

The compatibility branch is retained through final handoff. A committed report at `docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md` initially records the exact provisionally tested Wagtail 8.0 alpha and 7.4 versions, primary base/head, official 7.4 base/head, runtime-feature patch checksum, commit mapping, `git range-diff` output or an explicit explanation where a one-to-one commit mapping is impossible, file-level name/status and stat comparisons, every adaptation, and all verification commands and results. Only the independently reviewed future release plan may replace that provisional primary evidence with immutable official Wagtail 8.0 beta, release-candidate, or final evidence and refresh the corresponding compatibility proof. The runtime patch and equivalence comparison exclude primary-only design/plan/compatibility reports, pull-request administration, changelog, contributor, and release-note files. The report and local branch are the compatibility deliverable; a clean compile or theoretical API comparison is not sufficient. The report must show that runtime and test adaptations are limited to the declared routing, migration-dependency, or test-location seams, or identify a design defect that must be corrected on the primary branch.

Mini Draftail uses the Draftail and Draft.js dependencies already shipped by both target branches; this feature adds no editor dependency and does not store raw Draft.js content. Both branches must preserve their supported Python, Django, database, browser, and custom-user configurations rather than depending on PostgreSQL-only JSON operations, integer primary keys, or APIs introduced after 7.4.

The final PR branch contains only commits relevant to comment mentions, tests, and necessary user/developer documentation. Wagtail's contributor guide reserves `CHANGELOG.txt`, `docs/releases/8.0.md`, and `CONTRIBUTORS.md` updates for core committers after human review and acceptance, so this unreviewed contributor branch does not edit them; the pull request supplies suggested release-note and contributor copy for the accepting maintainer. Before publishing, its commit range is checked against the current upstream `main` merge base, while the compatibility worktree is separately checked against the current `stable/7.4.x` merge base. The pull request description uses `.github/PULL_REQUEST_TEMPLATE.md`, explains the behavior and architectural tradeoffs, highlights range validation, create-page authorization, notification merging, and the 7.4 backport evidence for careful review, and includes the required AI-assistance disclosure.

## Test strategy

Implementation is test-driven and covers the contract at five layers.

### Model and migration tests

- Existing comments and replies receive empty mention lists.
- Both models round-trip valid occurrence JSON across supported databases.
- `CommentMention` and `CommentReplyMention` enforce exact-message/user uniqueness, collapse repeated occurrences, support efficient inverse lookups, and reach reply threads through `CommentReply.comment`.
- Lookup rows synchronize atomically from valid occurrence JSON, disappear when their user is deleted, and do not remove or rewrite the historical occurrence JSON.
- Malformed stored entries are sanitized on read, warn without sensitive payload data, render only escaped plain text, do not make another author's form dirty, and are cleaned on the next authorized standard-browser save.
- The primary and 7.4-backport migration graphs each leave no pending migration and produce the same JSON-field and lookup-table schema.
- Saving comments no longer needs special handling for reverse-relation field discovery.

### Form, lifecycle, and endpoint tests

- Missing fields preserve metadata; explicit empty lists remove it; unchanged other-author forms remain unchanged.
- Retained mentions survive target rename, deactivation, deletion, and permission loss.
- Malformed JSON, wrong shapes, extra or missing fields, invalid UUID keys, invalid and aliased user IDs, duplicate keys, overlaps, unsorted ranges, out-of-bounds offsets, surrogate splits, forged labels, invisible mentions, labels over 255 UTF-16 units, fields over 16 KiB, and the 20-occurrence limit fail cleanly.
- UTF-16 validation covers emoji before and inside surrounding edits.
- Create-page GET succeeds with comments enabled and does not reverse a route with a missing page ID.
- Page create, draft save, autosave, publish, and submit-for-moderation persist valid mentions without partial saves on failure.
- Comment resolve and reposition preserve another author's mentions.
- Reply create, edit, remove, cancel, reload, and notification behavior match top-level comments.
- Existing-page and create-page suggestions enforce the exact 7.4 page-policy behavior for direct group permissions, inherited permissions, add-only ownership, and superusers; requester access; admin access; page comments enabled state; 64-unit queries; deterministic 10-result limits; complete eligible results without a candidate window; empty results; inactive users; UUID/custom primary keys; exact current-email metadata; and bounded query counts.
- Comment serialization bulk-loads current email metadata only for referenced users, updates that metadata after an email change without rewriting or dirtying saved text, omits deleted users, and never expands ordinary author records with email or management URLs.

### Notification and audit tests

- Actor exclusion, preference opt-out, inactive users, missing email, subscriber overlap, thread-participant overlap, repeated occurrences, and multiple changed messages produce the intended recipient payloads.
- A global notification for one message cannot suppress a direct mention in another.
- Direct-mention and combined-reason subjects, introductory copy, section ordering, comment/reply representation, and de-duplication match the exact translatable template contract without calling an edit a new comment.
- Failed delivery follows the declared no-retry contract and does not affect saved data.
- Audit records distinguish mention additions and removals for comments and replies without exposing email addresses.

### Frontend unit tests

- Query recognition, the 64-unit client limit, 200 ms debounce, server-result selection, and exact always-rendered hidden-field payloads work for comments and replies.
- Mini Draftail hydrates plain text plus occurrence JSON into `MENTION` entities, renders no formatting toolbar, and extracts the same plain text plus absolute UTF-16 occurrence ranges.
- Draft.js entity tracking shifts, retains, or removes occurrences for edits before, after, and through labels; partial entity text never survives as a forged mention.
- Duplicate names, repeated targets, emoji, multiline input, selected-range paste, cut, plain-text paste, text-and-entity undo/redo, current-email metadata changes, and cancel/hydration behavior are covered.
- Keyboard navigation, Escape, ordinary Tab behavior, pointer selection, ARIA state, status messages, and forced-colors classes are deterministic.
- Debounce, abort, stale and out-of-order responses, malformed responses, composition, blur, deletion, and unmount cannot insert stale data or leak requests.

### Browser and regression tests

- Keyboard-only users can create, edit, and remove mentions in a comment and reply, save, autosave, reload, and see the same result.
- The default settings-UI browser user proves that `user_id` is handled as an opaque string. UUID and other custom-primary-key behavior is backend and frontend-wire evidence unless a separate UUID browser environment is actually provisioned and recorded.
- The toolbar-free Mini Draftail editor highlights mention entities inline while preserving multiline text, emoji, selection replacement, plain-text paste, caret movement, composition-event gating, and text/entity undo behavior. Synthetic composition events prove only that matching is gated during composition; any claim about real IME input requires a recorded native-input run with an installed IME.
- Automated accessibility checks run with the popup closed, loading, empty, and populated.
- The comment mention Playwright regression runs in Chromium in automated verification. Before the pull request is published, native IME, caret, pointer, keyboard, multiline, paste, emoji, reload, and popup-accessibility behavior is recorded against the exact primary head in current Chromium and Firefox. WebKit/Safari remains an encouraged reviewer check rather than a release gate because the repository's current integration setup is Chromium-only.

### Cross-version verification matrix

The primary Wagtail 8.0 beta-or-later branch and committed 7.4 compatibility branch each run:

- the complete focused comment, reply, create/edit page, suggestion, notification, audit, permission, migration, serialization, and custom-user backend suites;
- the surrounding existing page create/edit and comment regression suites;
- the frontend mention unit suites, TypeScript checks, ESLint, formatting, style linting, and production build;
- migration consistency checks; and
- the Chromium mention Playwright scenario with Axe checks, including both edit-page and create-page suggestion routing.

The 7.4 branch additionally runs its Django 5.2 and Django 6.0 test environments and UUID email-user configuration. The 8.0 branch runs its repository-declared Django/default-user matrix plus the UUID email-user configuration. Those UUID runs prove backend and frontend-wire behavior, not a UUID browser scenario. The required native-input Firefox scenario runs against the beta-or-later 8.0 branch; the automated 7.4 Chromium run covers the version-specific browser routing seam with opaque string IDs. Any matrix run while `VERSION` still reports 8.0 alpha is recorded as provisional. The alpha checkpoint does not repeat or integrate the matrix; it records `PENDING_OFFICIAL_8_RELEASE` or `REPLAN_REQUIRED`, and a newly reviewed plan is required before the beta-or-later and refreshed 7.4 proofs can run.

## Acceptance criteria

The implementation is ready when:

1. The complete cross-version matrix above passes on both a primary branch based on an immutable official Wagtail 8.0 beta, release-candidate, or final ref and the committed compatibility branch based on a freshly fetched official `stable/7.4.x` commit; both exact OIDs and version strings are recorded under a newly reviewed release-integration plan.
2. Existing page create/edit, comment, reply, notification, audit, and permission suites pass unchanged or with intentional assertions added on both branches.
3. Django 5.2 and Django 6.0 pass on 7.4, and each branch's UUID email-user configuration passes.
4. Frontend type checking, linting, formatting, style linting, production build, Chromium mention regression, and Axe checks pass on both branches; recorded native-input runs in current Chromium and Firefox on the exact primary head support any real IME claim.
5. Migration checks pass on both branches and produce the same JSON-field and inverse-index schema operations without database-specific behavior outside Wagtail's supported contract.
6. The retained compatibility branch and committed report contain the recorded OIDs, patch checksum, commit/diff comparison, exhaustive adaptation list, and command output required to reproduce the compatibility conclusion.
7. A final diff and commit-history review confirms PR 1 remains based on current upstream `main`, contains no unrelated commits, leaves core-committer release files unchanged while providing suggested copy in the PR, and uses the required pull request template and AI disclosure; the compatibility report confirms that the 7.4 runtime/test backport differs only at the declared compatibility seams.
