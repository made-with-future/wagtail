# Comment Mentions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PR 1's unsafe email-token prototype with structured, accessible `@` mentions for page comments and replies, with the complete feature proven on both Wagtail 7.4 and an official Wagtail 8.0 beta-or-later prerelease.

**Architecture:** Keep comment and reply text as plain strings, store validated occurrence ranges as JSON, and maintain unique relational lookup rows per exact message/user for efficient inverse queries. Use toolbar-free Mini Draftail `MENTION` entities to track and highlight occurrences during editing, hydrate current email as separate metadata, and keep validation, audit, notification, and permission logic independent of Wagtail 8-only routing.

**Tech Stack:** Python 3.10+, Django 5.2/6.0, Wagtail modelcluster and page permission policy, React/Redux/TypeScript, Jest/Enzyme, Sass/Stylelint, Playwright/Axe, SQLite-focused tox verification, Git worktrees.

## Global Constraints

- Primary development stays on PR 1's Wagtail 8.0 `main` branch; official `main` and `stable/7.4.x` refs plus the primary version string must be freshly fetched and recorded before code work and final verification.
- Wagtail 8.0 alpha results are provisional. Final compatibility requires the complete matrix on Wagtail 8.0 `beta`, `rc`, or final as well as on `stable/7.4.x`; do not claim or publish cross-version completion while the primary version still reports alpha.
- Comments and replies share the exact occurrence contract: `{key, user_id, start, end, label}` with half-open UTF-16 offsets.
- Each message allows at most 20 occurrences, a 16 KiB UTF-8 JSON payload, and 255 UTF-16 units per server-generated label.
- For this release, labels use the current configured email value, fall back to Wagtail display name and then `user.get_username()`, normalize whitespace, and truncate on a code-point boundary with an ellipsis when needed.
- Suggestion queries allow 1-64 UTF-16 units, debounce for 200 ms, and return at most 10 results as `{id, label, email, username?}`.
- Candidate filtering uses Django's database-backed `wagtailadmin.access_admin` and Wagtail page-permission semantics before the ten-row slice.
- Candidate filtering always applies `is_active=True` before search and slicing.
- Omitted mention fields preserve stored metadata; an explicit `[]` clears it; unchanged other-author forms remain unchanged.
- Retained occurrence keys preserve user ID and label without re-authorizing the target; new keys require current target eligibility and the exact current label.
- `CommentMention(comment, user)` and `CommentReplyMention(reply, user)` are unique inverse indexes derived from occurrence JSON; both foreign keys use `related_name="+"`, and lookup-row changes never determine notification novelty.
- The editor is toolbar-free Mini Draftail with only `MUTABLE` `MENTION` entities and immediate full-association removal when edited entity text differs from its snapshot label. It persists neither raw Draft.js content nor rich-text formatting and never uses canvas, a textarea overlay, user-management links, or email in ordinary author records.
- Draftail owns text and entity undo/redo together; paste is normalized to plain text, partial mention edits remove entity identity, and serialization extracts newline-flattened text plus absolute UTF-16 occurrence ranges.
- Comment hydration returns current configured email values only in a separate `mentioned_users` map; live metadata never rewrites snapshot labels or dirties a form.
- Notification reasons are merged per recipient after all changed messages are collected; the actor is excluded and the existing updated-comments preference remains authoritative.
- Mention JSON, inverse-index writes, audit data, and revision/page actions must not partially commit. Email is scheduled with `transaction.on_commit` and retains Wagtail's no-retry delivery contract.
- New user-facing strings use Django `gettext` or the frontend `gettext` helper.
- A future global email-versus-display-name label setting is supported by snapshot labels but is not implemented in this pull request.
- Keep this as one focused contribution on the existing feature branch and PR: include a descriptive title, issue link/context, assumptions, before/after UI evidence, and explicit browser/accessibility results; push fixes to the same branch and never open a replacement PR for the same work.
- Do not edit `CHANGELOG.txt`, `docs/releases/8.0.md`, or `CONTRIBUTORS.md` before human acceptance; put suggested maintainer copy in the PR description.
- Do not publish the compatibility branch or create a 7.4 PR without separate user authorization.

## File and Responsibility Map

**Create:**

- `wagtail/admin/comment_mentions.py` — occurrence schema, UTF-16 helpers, labels, canonical IDs, candidate querysets, structural/retained/new-target validation, and safe rendering segments.
- `wagtail/admin/forms/comment_mentions.py` — hidden JSON form field, omission sentinel, and reusable comment/reply form mixin.
- `wagtail/admin/views/pages/comment_mentions.py` — saved-page and create-page suggestion GET views only.
- `wagtail/admin/commenting.py` — change collection and mention-aware audit dispatch shared by edit/create views.
- `wagtail/admin/comment_notifications.py` — recipient payload construction, grouping, exact template context, and on-commit delivery.
- `wagtail/admin/tests/test_comment_mentions.py` — focused schema, form, candidate, endpoint, serialization, and privacy tests.
- `wagtail/admin/tests/test_comment_notifications.py` — recipient, copy, ordering, delivery, and audit tests.
- `client/src/components/CommentApp/utils/mentions.ts` — wire types/conversion, query recognition, live metadata types, and display segmentation.
- `client/src/components/CommentApp/utils/mentions.test.ts` — pure wire/query/display contract tests.
- `client/src/components/CommentApp/components/MentionEditor/draftail.ts` and `.test.ts` — plain-text/occurrence hydration, `MENTION` entity creation, absolute UTF-16 extraction, and entity normalization.
- `client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.ts` and `.test.tsx` — debounced, abortable, stale-safe request state.
- `client/src/components/CommentApp/components/MentionEditor/index.tsx` and `index.test.tsx` — toolbar-free Draftail editing, entity decoration, autocomplete, and accessible listbox integration.
- `client/src/components/CommentApp/components/MentionText/index.tsx` and `index.test.tsx` — escaped, non-linked range rendering.
- `client/src/components/CommentApp/components/Comment/index.test.tsx` and `components/CommentReply/index.test.tsx` — comment/reply lifecycle integration.
- `client/src/components/CommentApp/main.test.tsx` — hydration/autosave round-trip.
- `client/tests/integration/comment-mentions.test.js` — Chromium/Axe create/edit/comment/reply browser regression.
- `docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md` — final reproducible backport report.

**Replace or delete:**

- Replace `wagtail/migrations/0098_commentmention.py` with `wagtail/migrations/0098_comment_mentions.py`.
- Replace the prototype `CommentMention` with the lookup-only `(comment, user)` model, add `CommentReplyMention`, and delete all `notified_at` handling.
- Delete `client/src/components/CommentApp/components/Comment/CommentText.tsx` and its current email-link test after `MentionText` replaces them.
- Delete the prototype `client/src/components/CommentApp/components/MentionTextArea/` implementation after `MentionEditor` replaces it; remove every bespoke contenteditable/caret-walker path.

**Modify:**

- Models/forms/panels: `wagtail/models/pages.py`, `wagtail/models/__init__.py`, `wagtail/admin/forms/comments.py`, `wagtail/admin/forms/pages.py`, `wagtail/admin/panels/comment_panel.py`.
- Lifecycle/routing/templates: `wagtail/admin/views/pages/edit.py`, `wagtail/admin/views/pages/create.py`, `wagtail/admin/viewsets/pages.py`, `wagtail/admin/urls/pages.py`, and the three `updated_comments*` templates.
- Backend tests: `wagtail/tests/test_comments.py`, `wagtail/admin/tests/test_edit_handlers.py`, `wagtail/admin/tests/pages/test_edit_page.py`, and `wagtail/admin/tests/pages/test_create_page.py`.
- Frontend state/UI: CommentApp fixtures, state, selectors, forms, main loader, comment/reply components, and comment styles.

---

### Task 1: Refresh Official Bases and Freeze the Redesign Baseline

**Files:** None.

**Interfaces:**
- Consumes: current clean `worktree/comment-mentions` branch.
- Produces: `/tmp/comment-mentions-bases.env` containing `PRIMARY_WORKTREE`, `OFFICIAL_MAIN`, `OFFICIAL_STABLE`, `PRIMARY_BASE`, `REDESIGN_BASE`, and `PRIMARY_VERSION`, plus a verified baseline from which later compatibility patches and before/after UI evidence are generated.

- [ ] **Step 1: Verify the primary checkout is clean and identify the obsolete source commits**

Run:

```bash
git status --short --branch
git log --oneline --decorate -8
```

Expected: no unstaged/staged files; the history contains obsolete prototype commits `ea4a8c43f0`, `136e3acb83`, and `52ebbcc9ca`, which must never be used as the backport series.

- [ ] **Step 2: Refresh official refs and record exact OIDs**

Run with network approval:

```bash
git fetch --no-tags https://github.com/wagtail/wagtail.git \
  +refs/heads/main:refs/remotes/upstream/main \
  +refs/heads/stable/7.4.x:refs/remotes/upstream/stable/7.4.x

git ls-remote https://github.com/wagtail/wagtail.git \
  refs/heads/main refs/heads/stable/7.4.x

OFFICIAL_MAIN=$(git rev-parse refs/remotes/upstream/main)
OFFICIAL_STABLE=$(git rev-parse refs/remotes/upstream/stable/7.4.x)
PRIMARY_BASE=$(git merge-base "$OFFICIAL_MAIN" HEAD)
PRIMARY_WORKTREE=$(git rev-parse --show-toplevel)
REDESIGN_BASE=$(git rev-parse HEAD)
PRIMARY_VERSION=$(python -c 'import wagtail; print(wagtail.__version__)')
printf '%s\n' "$OFFICIAL_MAIN" "$OFFICIAL_STABLE" "$PRIMARY_BASE" "$PRIMARY_WORKTREE" "$REDESIGN_BASE" "$PRIMARY_VERSION"

{
  printf 'PRIMARY_WORKTREE=%s\n' "$PRIMARY_WORKTREE"
  printf 'OFFICIAL_MAIN=%s\n' "$OFFICIAL_MAIN"
  printf 'OFFICIAL_STABLE=%s\n' "$OFFICIAL_STABLE"
  printf 'PRIMARY_BASE=%s\n' "$PRIMARY_BASE"
  printf 'REDESIGN_BASE=%s\n' "$REDESIGN_BASE"
  printf 'PRIMARY_VERSION=%s\n' "$PRIMARY_VERSION"
} > /tmp/comment-mentions-bases.env
```

Expected: the fetched and `ls-remote` OIDs match for both branches. Record the current `8.0aN`, `8.0bN`, `8.0rcN`, or `8.0` string exactly; an alpha value permits implementation but remains provisional until Task 16.

- [ ] **Step 3: Enforce the main-base gate**

Run:

```bash
source /tmp/comment-mentions-bases.env
test "$PRIMARY_BASE" = "$OFFICIAL_MAIN"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$(git rev-parse HEAD)"
python -c 'from wagtail import VERSION; assert VERSION[:3] == (8, 0, 0)'
```

Expected: exit 0. If it fails, stop implementation and obtain approval to rebuild/rebase the PR on official main; do not layer new code over an outdated base or blindly rebase the obsolete prototype series.

- [ ] **Step 4: Reconfirm the known prototype regression before replacing it**

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.pages.test_create_page.TestCommenting.test_comments_enabled_by_default
```

Expected before Task 5: FAIL with `NoReverseMatch` from reversing the edit suggestion URL with `page_id=None`. Preserve the output as the red regression evidence.

- [ ] **Step 5: Preserve the actual pre-redesign visual baseline**

Run the current prototype with `wagtail.test.settings_ui` using the same migrated test site, `admin` account, and 1024-by-768 Chromium viewport specified in Task 13. Because the known prototype regression breaks the create-page route, create one `StandardPage(title="Mention redesign baseline", slug="mention-redesign-baseline")` under page 2 through `wagtail/test/manage.py shell`, print its PK, and open `/admin/pages/<pk>/edit/`. Open the first comment editor, type the representative multiline message with emoji used by Task 13, and select `admin` from `@adm`. Save `/tmp/wagtail-comment-mentions-pr/before-redesign.png`, and record `REDESIGN_BASE`, page PK, viewport, OS, and browser version beside it. This is the actual “before” evidence required by Wagtail's contribution guide; do not commit the image.

---

### Task 2: Structured Occurrence and UTF-16 Primitives

**Files:**
- Create: `wagtail/admin/comment_mentions.py`
- Create: `wagtail/admin/tests/test_comment_mentions.py`

**Interfaces:**
- Consumes: Django's configured user model, its configured email field, and Wagtail `user_display_name`.
- Produces: `MentionOccurrence`, `MentionChanges`, constants, UTF-16 helpers, `current_mention_email`, structural validation, stored-value sanitization, retained-key validation, label generation, and text segmentation used by every later backend task.

- [ ] **Step 1: Write failing primitive and validation tests**

Start `wagtail/admin/tests/test_comment_mentions.py` with these exact classes and representative assertions; use subtests to cover every row in the table after the code block.

```python
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from wagtail.admin.comment_mentions import (
    compare_mentions,
    sanitize_stored_mentions,
    split_text_by_mentions,
    utf16_length,
    utf16_slice,
    validate_mention_occurrences,
)


class TestUTF16Helpers(SimpleTestCase):
    def test_non_bmp_character_uses_two_units(self):
        self.assertEqual(utf16_length("A😀B"), 4)
        self.assertEqual(utf16_slice("A😀B", 1, 3), "😀")

    def test_surrogate_split_is_rejected(self):
        with self.assertRaises(ValidationError):
            utf16_slice("A😀B", 1, 2)


class TestMentionOccurrenceValidation(TestCase):
    def test_valid_occurrence_is_canonicalized(self):
        value = [{
            "key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb",
            "user_id": "1",
            "start": 4,
            "end": 7,
            "label": "@Jo",
        }]
        self.assertEqual(
            validate_mention_occurrences(value, text="A😀 @Jo"),
            tuple(value),
        )
```

Validation table:

| Case | Expected |
|---|---|
| outer dict/string/null | `ValidationError` |
| missing or extra occurrence key | `ValidationError` |
| invalid/duplicate UUID key | `ValidationError` |
| bool/collection/null user ID | `ValidationError` |
| numeric `1` and string `"1"` | same canonical string ID |
| bool/float/string offsets | `ValidationError` |
| unsorted, overlapping, negative, out-of-range ranges | `ValidationError` |
| UTF-16 surrogate split | `ValidationError` |
| selected text differs from label | `ValidationError` |
| 21 occurrences | `ValidationError` |
| 256-unit label | `ValidationError` |
| malformed stored entry | omitted with a warning containing message ID but not text/payload |
| retained key changes target/label | `ValidationError` |
| retained key shifts with same target/label | accepted |
| repeated target with distinct keys/ranges | accepted |
| current configured email exists | label is `@` plus normalized current email |
| configured email is blank | label falls back to display name, then username |
| current email changes after save | stored label is unchanged; live metadata changes separately |

- [ ] **Step 2: Run the focused module and verify red state**

Run:

```bash
python runtests.py -- wagtail.admin.tests.test_comment_mentions
```

Expected: FAIL with `ModuleNotFoundError: wagtail.admin.comment_mentions`.

- [ ] **Step 3: Implement the shared public contract**

Create these exact public names in `wagtail/admin/comment_mentions.py`:

```python
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Sequence, TypedDict

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from wagtail.admin.templatetags.wagtailadmin_tags import user_display_name

MAX_MENTIONS = 20
MAX_MENTION_LABEL_UTF16 = 255
MAX_MENTION_JSON_BYTES = 16 * 1024
MAX_QUERY_UTF16 = 64
RESULT_LIMIT = 10

logger = logging.getLogger("wagtail.admin.comment_mentions")


class MentionOccurrence(TypedDict):
    key: str
    user_id: str
    start: int
    end: int
    label: str


@dataclass(frozen=True)
class MentionChanges:
    added: tuple[MentionOccurrence, ...] = ()
    removed: tuple[MentionOccurrence, ...] = ()


def utf16_length(value: str) -> int:
    try:
        return len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError as error:
        raise ValidationError("Invalid UTF-16 text boundary.") from error


def utf16_slice(value: str, start: int, end: int) -> str:
    encoded = value.encode("utf-16-le")
    try:
        return encoded[start * 2 : end * 2].decode("utf-16-le")
    except UnicodeDecodeError as error:
        raise ValidationError("Invalid UTF-16 text boundary.") from error


def truncate_utf16(value: str, limit: int) -> str:
    if utf16_length(value) <= limit:
        return value
    result = ""
    for character in value:
        if utf16_length(result + character + "…") > limit:
            break
        result += character
    return result + "…"


def current_mention_email(user) -> str:
    email_field = user.get_email_field_name()
    return re.sub(r"\s+", " ", str(getattr(user, email_field, "") or "")).strip()


def normalize_mention_label(user) -> str:
    identity = current_mention_email(user)
    if not identity:
        identity = re.sub(r"\s+", " ", user_display_name(user)).strip()
    if not identity:
        identity = re.sub(r"\s+", " ", str(user.get_username())).strip()
    return truncate_utf16(f"@{identity}", MAX_MENTION_LABEL_UTF16)
```

Complete `validate_mention_occurrences` with this fixed order: require a list; enforce count and compact UTF-8 size; require exactly five fields; canonicalize UUID text; reject boolean/collection user IDs; convert through `get_user_model()._meta.pk.to_python`, prepare through that field, and run its validators against the prepared value so out-of-range IDs fail before a database query; require integer non-boolean offsets; require sorted non-overlapping ranges; require UTF-16 boundaries; require `utf16_slice(text, start, end) == label`; and return a tuple sorted by `(start, end, key)`. Preserve a submitted PK string when it matches either the parsed or prepared round-tripping representation. Implement `validate_retained_mentions` by key, `compare_mentions` by key, `sanitize_stored_mentions` as per-entry defensive validation with one warning per invalid entry, and `split_text_by_mentions` as escaped-data-ready `(text, is_mention)` segments without producing markup.

- [ ] **Step 4: Run focused tests and formatting**

Run:

```bash
python runtests.py -- wagtail.admin.tests.test_comment_mentions
ruff format --check wagtail/admin/comment_mentions.py wagtail/admin/tests/test_comment_mentions.py
ruff check wagtail/admin/comment_mentions.py wagtail/admin/tests/test_comment_mentions.py
```

Expected: all focused tests PASS; Ruff reports no changes/errors.

- [ ] **Step 5: Commit the primitive contract**

```bash
git add wagtail/admin/comment_mentions.py wagtail/admin/tests/test_comment_mentions.py
git commit -m "Add structured comment mention validation"
```

---

### Task 3: Add Occurrence Storage and Exact-Message Lookup Models

**Files:**
- Modify: `wagtail/models/pages.py`
- Modify: `wagtail/models/__init__.py`
- Modify: `wagtail/tests/test_comments.py`
- Delete: `wagtail/migrations/0098_commentmention.py`
- Create: `wagtail/migrations/0098_comment_mentions.py`

**Interfaces:**
- Consumes: validated occurrence lists from Task 2.
- Produces: `Comment.mentions` and `CommentReply.mentions`, both `models.JSONField(default=list)`, plus lookup-only `CommentMention` and `CommentReplyMention` models with no delivery state or reverse accessor.

- [ ] **Step 1: Add failing storage and ordinary-save regressions**

Add `TestCommentMentionStorage` to `wagtail/tests/test_comments.py`:

```python
class TestCommentMentionStorage(CommentTestingUtils, TestCase):
    fixtures = ["test.json"]

    def test_comment_and_reply_default_to_empty_mentions(self):
        comment = self.create_comment(self.revision_1)
        reply = CommentReply.objects.create(
            comment=comment,
            user=get_user_model().objects.first(),
            text="reply",
        )
        self.assertEqual(comment.mentions, [])
        self.assertEqual(reply.mentions, [])

    def test_occurrences_round_trip(self):
        comment = self.create_comment(self.revision_1)
        occurrence = {
            "key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb",
            "user_id": str(comment.user_id),
            "start": 0,
            "end": 3,
            "label": "@Jo",
        }
        comment.mentions = [occurrence]
        comment.save()
        comment.refresh_from_db()
        self.assertEqual(comment.mentions, [occurrence])
```

Add lookup assertions using a target who is not the comment author:

```python
def test_exact_message_lookup_rows_are_unique_and_queryable(self):
    comment = self.create_comment(self.revision_1)
    reply = CommentReply.objects.create(
        comment=comment,
        user=get_user_model().objects.first(),
        text="reply",
    )
    target = get_user_model().objects.exclude(pk=comment.user_id).first()

    CommentMention.objects.create(comment=comment, user=target)
    CommentReplyMention.objects.create(reply=reply, user=target)

    self.assertEqual(
        CommentMention.objects.get(user=target).comment,
        comment,
    )
    self.assertEqual(
        CommentReplyMention.objects.select_related("reply__comment")
        .get(user=target)
        .reply.comment,
        comment,
    )
```

Also assert repeated `(message, user)` insertion raises `IntegrityError` while the same target on a second message and a second target on the same message remain valid. Deleting the target removes both lookup rows without changing stored occurrence JSON, neither lookup model appears in `Comment._meta.get_fields()` / `CommentReply._meta.get_fields()`, comment and reply occurrences both round-trip, and an ordinary `comment.save()` preserves staged modelcluster reply add/edit/delete operations. Add a focused regression for the standard `comment.save(update_fields=["mentions"])` string-name API because Task 4 relies on it.

- [ ] **Step 2: Run and verify the relation-based implementation fails**

Run:

```bash
python runtests.py -- wagtail.tests.test_comments.TestCommentMentionStorage
```

Expected: FAIL because `comment.mentions` is a related manager, replies have no `mentions` field, and `CommentReplyMention` does not exist.

- [ ] **Step 3: Implement the model and migration schema**

Add to both models:

```python
mentions = models.JSONField(default=list)
```

Replace the prototype lookup model and add the reply lookup after `CommentReply`:

```python
class CommentMention(models.Model):
    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        related_name="+",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["comment", "user"],
                name="unique_comment_mention_user",
            )
        ]
        verbose_name = _("comment mention")
        verbose_name_plural = _("comment mentions")


class CommentReplyMention(models.Model):
    reply = models.ForeignKey(
        CommentReply,
        on_delete=models.CASCADE,
        related_name="+",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reply", "user"],
                name="unique_comment_reply_mention_user",
            )
        ]
        verbose_name = _("comment reply mention")
        verbose_name_plural = _("comment reply mentions")
```

Export both lookup models from `wagtail/models/__init__.py`, delete `notified_at`, remove the prototype's `get_all_child_relations` import, and restore clean-main `Comment.save()` behavior while normalizing either standard string field names or internal field objects before filtering `position`/`id`. `related_name="+"` keeps the lookup foreign keys out of reverse field discovery while direct `CommentMention.objects` / `CommentReplyMention.objects` queries retain indexed forward and inverse lookup.

Replace migration `0098_commentmention.py` with:

```python
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("wagtailcore", "0097_baselogentry_uuid_action_timestamp_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="comment",
            name="mentions",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="commentreply",
            name="mentions",
            field=models.JSONField(default=list),
        ),
        migrations.CreateModel(
            name="CommentMention",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "comment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="wagtailcore.comment",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "comment mention",
                "verbose_name_plural": "comment mentions",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("comment", "user"),
                        name="unique_comment_mention_user",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="CommentReplyMention",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "reply",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="wagtailcore.commentreply",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "comment reply mention",
                "verbose_name_plural": "comment reply mentions",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("reply", "user"),
                        name="unique_comment_reply_mention_user",
                    )
                ],
            },
        ),
    ]
```

- [ ] **Step 4: Verify models and migration graph**

Run:

```bash
python runtests.py -- wagtail.tests.test_comments
DJANGO_SETTINGS_MODULE=wagtail.test.settings \
  python -m django makemigrations --check --dry-run
ruff format --check wagtail/models/pages.py wagtail/migrations/0098_comment_mentions.py wagtail/tests/test_comments.py
ruff check wagtail/models/pages.py wagtail/migrations/0098_comment_mentions.py wagtail/tests/test_comments.py
```

Expected: tests PASS; `No changes detected`; Ruff passes.

- [ ] **Step 5: Commit structured persistence**

```bash
git add wagtail/models/pages.py wagtail/models/__init__.py wagtail/tests/test_comments.py wagtail/migrations
git commit -m "Store and index structured comment mentions"
```

---

### Task 4: Forms, Lookup Synchronization, and Live-Metadata Serialization

**Files:**
- Create: `wagtail/admin/forms/comment_mentions.py`
- Modify: `wagtail/admin/comment_mentions.py`
- Modify: `wagtail/admin/forms/comments.py`
- Modify: `wagtail/admin/forms/pages.py`
- Modify: `wagtail/admin/panels/comment_panel.py`
- Modify: `wagtail/admin/tests/test_comment_mentions.py`
- Modify: `wagtail/admin/tests/test_edit_handlers.py`

**Interfaces:**
- Consumes: Task 2 validators/current-email helper and Task 3 JSON fields/lookup models.
- Produces: `CommentMentionsField`, `MentionedMessageFormMixin`, `CommentFormSet.sync_mention_lookups()`, form-level `mention_changes`, comment/reply wire serialization with `mentioned_users`, safe omission handling, and parent-page context for create forms.

- [ ] **Step 1: Write failing form and serialization tests**

Add tests with exact browser-shaped keys for both `comments-0-mentions` and `comments-0-replies-0-mentions`:

```python
def test_omitted_field_preserves_stored_mentions(self):
    self.comment.mentions = [self.valid_occurrence]
    self.comment.save(update_fields=["mentions"])
    form = self.make_page_form(comment_mentions_key_is_absent=True)
    self.assertTrue(form.is_valid(), form.errors)
    self.assertEqual(
        form.formsets["comments"].forms[0].cleaned_data["mentions"],
        [self.valid_occurrence],
    )

def test_explicit_empty_list_removes_mentions(self):
    form = self.make_page_form(comment_mentions="[]")
    self.assertTrue(form.is_valid(), form.errors)
    self.assertEqual(
        form.formsets["comments"].forms[0].mention_changes.removed,
        (self.valid_occurrence,),
    )
```

Cover: unchanged browser payload for another author; resolve/reposition with omitted and hydrated fields; an omitted field redisplaying its canonical initial value when an unrelated page field fails; retained target rename/deactivation/deletion/permission loss; malformed/blank/oversize/digit-limit/recursive JSON and escaped-surrogate redisplay; comment/reply parity; repeated occurrences collapsing to one lookup row; prepared/display PK aliases resolving to one target while retaining both exact metadata keys; explicit clearing removing the exact message's lookup row; deleted targets not being recreated; a deleted parent skipping nested reply synchronization; invalid stored entries sanitized without dirtying another-author form; all user wire IDs remaining strings under the UUID user model; author JSON remaining exactly name/avatar with the current editor retained; mention-only targets excluded from authors; and current email appearing only under `mentioned_users`. Assert serialization performs one profile-aware author query and one mentioned-user query regardless of message count.

Add an exact live-metadata assertion:

```python
self.target.email = "new-address@example.com"
self.target.save(update_fields=[self.target.get_email_field_name()])
data = self.form.formsets["comments"].serialize(bound=False, user=self.editor)
self.assertEqual(
    data["mentioned_users"],
    {str(self.target.pk): {"email": "new-address@example.com"}},
)
self.assertEqual(data["comments"][0]["mentions"], [self.valid_occurrence])
self.assertNotIn("email", data["authors"][str(self.comment.user_id)])
```

- [ ] **Step 2: Run the focused form tests and verify failure**

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.test_comment_mentions \
  wagtail.admin.tests.test_edit_handlers.TestCommentPanel
```

Expected: FAIL because the prototype field collapses omission to empty, replies lack mention forms, and serialization exposes email/edit URLs.

- [ ] **Step 3: Implement the omission-aware hidden JSON field**

Create `wagtail/admin/forms/comment_mentions.py` with this public contract:

```python
import json

from django import forms
from django.core.exceptions import ValidationError
from django.forms.fields import InvalidJSONInput
from django.utils.translation import gettext_lazy as _

from wagtail.admin.comment_mentions import (
    MAX_MENTION_JSON_BYTES,
    MentionChanges,
    compare_mentions,
    sanitize_stored_mentions,
    validate_mention_occurrences,
    validate_retained_mentions,
)

MENTIONS_OMITTED = object()


class CommentMentionsInput(forms.HiddenInput):
    def value_from_datadict(self, data, files, name):
        if name not in data:
            return MENTIONS_OMITTED
        return data[name]


class CommentMentionsField(forms.JSONField):
    widget = CommentMentionsInput
    default_error_messages = {
        "invalid": _("Enter a valid mention list."),
    }

    def bound_data(self, data, initial):
        if data is MENTIONS_OMITTED:
            return initial
        # Hidden JSON is validated during cleaning. Preserve explicit bound text
        # verbatim so redisplay never performs a second, resource-unbounded parse.
        return InvalidJSONInput(data if isinstance(data, str) else "")

    def _validate_raw_value(self, value):
        if not isinstance(value, str) or not value:
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        try:
            value_size = len(value.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ValidationError(
                self.error_messages["invalid"], code="invalid"
            ) from error
        if value_size > MAX_MENTION_JSON_BYTES:
            raise ValidationError(self.error_messages["invalid"], code="invalid")

    def to_python(self, value):
        if value is MENTIONS_OMITTED:
            return MENTIONS_OMITTED
        self._validate_raw_value(value)
        try:
            return super().to_python(value)
        except (RecursionError, ValueError, ValidationError) as error:
            raise ValidationError(
                self.error_messages["invalid"], code="invalid"
            ) from error

    def prepare_value(self, value):
        if isinstance(value, InvalidJSONInput):
            return value
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def has_changed(self, initial, data):
        if data is MENTIONS_OMITTED:
            return False
        return super().has_changed(initial, data)


class MentionedMessageFormMixin:
    def __init__(self, *args, page=None, parent_page=None, **kwargs):
        self.page = page
        self.parent_page = parent_page
        self.mention_changes = MentionChanges()
        super().__init__(*args, **kwargs)
        self.initial["mentions"] = self._initial_mentions()

    def _initial_mentions(self):
        return list(
            sanitize_stored_mentions(
                self.instance.mentions,
                text=self.instance.text,
                message_id=self.instance.pk,
            )
        )

    def clean_mentions(self):
        initial = self._initial_mentions()
        submitted = self.cleaned_data["mentions"]
        if submitted is MENTIONS_OMITTED:
            submitted = initial
        try:
            current = list(
                validate_mention_occurrences(
                    submitted,
                    text=self.cleaned_data.get("text", self.instance.text),
                )
            )
            validate_retained_mentions(initial, current)
        except ValidationError as error:
            raise ValidationError(_("Enter a valid mention list.")) from error
        self.mention_changes = compare_mentions(initial, current)
        return current
```

Use a translated user-facing validation message in production rather than exposing parse details.

- [ ] **Step 4: Apply the mixin and serialization contract**

Make both forms consume the mixin:

```python
class CommentReplyForm(MentionedMessageFormMixin, WagtailAdminModelForm):
    mentions = CommentMentionsField(required=False)

    class Meta:
        fields = ("text", "mentions")


class CommentForm(MentionedMessageFormMixin, WagtailAdminModelForm):
    resolved = forms.BooleanField(required=False)
    mentions = CommentMentionsField(required=False)

    class Meta:
        formsets = {
            "replies": {
                "form": CommentReplyForm,
                "inherit_kwargs": ["for_user", "page", "parent_page"],
            }
        }
```

Declare the field on both concrete forms so Django's model-form metaclass collects it; keep parsing/cleaning behavior in the mixin. Its constructor canonicalizes stored JSON into `form.initial`, while `has_changed` treats only the explicit omission sentinel as unchanged, so malformed legacy entries and older clients cannot manufacture another-author edits. Set `self.parent_page = parent_page` before `WagtailAdminPageForm` calls `super().__init__`, add `parent_page` to the comment formset's `inherit_kwargs`, and add `page`/`parent_page` to the nested reply formset's inherited kwargs. Serialize each message's complete occurrence list directly, serialize only comment/reply authors, and restore author entries to:

```python
{"name": user_display_name(user), "avatar_url": avatar_url(user)}
```

In `CommentFormSet.__init__`, copy `for_user` and `parent_page` from its incoming `form_kwargs` before calling `super()`. Its existing `get_form_kwargs()` continues to add `page=self.instance` to every concrete comment form. This gives formset validation the editor and create parent without relying on attributes that `BaseChildFormSet` does not define.

Add one formset-level synchronization method and call it only after the normal modelcluster save has assigned message primary keys:

```python
def sync_mention_lookups(self):
    for form in self.forms:
        if form in self.deleted_forms:
            # The database cascade has already removed its replies; do not
            # recreate lookup rows from in-memory nested forms.
            continue
        if form.instance.pk:
            sync_message_mention_lookups(
                message=form.instance,
                occurrences=form.cleaned_data["mentions"],
            )
        replies = form.formsets["replies"]
        for reply_form in replies.forms:
            if reply_form not in replies.deleted_forms and reply_form.instance.pk:
                sync_message_mention_lookups(
                    message=reply_form.instance,
                    occurrences=reply_form.cleaned_data["mentions"],
                )
```

Implement `sync_message_mention_lookups` in `wagtail/admin/comment_mentions.py`. Select the model/foreign-key name from `Comment` versus `CommentReply`, fetch all still-existing target users in one query using the occurrence IDs, delete rows not in that resolved user set, and bulk-create missing `(message, user)` rows with `ignore_conflicts=True`. Compare resolved user objects/prepared identities rather than `str(user.pk)` so configured prepared/display aliases collapse to one row. Never recreate a deleted target from retained JSON and never infer notification novelty from row insertion.

Remove the prototype `save_mentions`, relation-derived author expansion, author email, and user-edit URLs. After serializing every comment and reply, collect all sanitized occurrence user IDs and bulk-load current users once. Emit:

```python
comments_data["mentioned_users"] = {
    occurrence_user_id: {"email": current_mention_email(user)}
    for occurrence_user_id, user in resolved_occurrence_users.items()
}
```

Resolve each exact occurrence ID through the configured PK field's prepared identity before building this map, so supported aliases may point to the same user without rewriting JSON. Keep the current editor plus actual comment/reply authors in `authors`, but never add a mention-only target there. Stringify all user IDs in the wire payload. Create serialization must not reverse an edit URL while `page.pk` is `None`; Task 5 supplies the correct two URL variants.

The recorded Task 3 base already makes the prototype edit lifecycle unusable because that lifecycle treats the new JSON list as a related manager. Task 4 removes those relation helpers but intentionally does not create a temporary compatibility shim: Task 5 replaces the prototype endpoint, Task 6 replaces the change collector, removes the remaining `save_mentions()` / `notified_at` paths, and restores ordinary subscriber/thread notifications, Task 7 builds recipient-specific mention planning, and Task 8 installs lookup synchronization and the new planner transactionally across edit/create actions. Tasks 4 and 5 are coherent review slices rather than standalone runnable edit-lifecycle checkpoints; Task 6 restores the non-mention action baseline before direct mention delivery is integrated.

- [ ] **Step 5: Verify form, privacy, UUID, and create-GET regressions**

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.test_comment_mentions \
  wagtail.admin.tests.test_edit_handlers.TestCommentPanel \
  wagtail.admin.tests.pages.test_create_page.TestCommenting.test_comments_enabled_by_default

USE_EMAIL_USER_MODEL=yes python runtests.py -- \
  wagtail.admin.tests.test_comment_mentions \
  wagtail.admin.tests.test_edit_handlers.TestCommentPanel
```

Expected: all PASS; serialized UUID IDs are strings; repeated occurrences produce one lookup row; the current email map changes without rewriting stored text/JSON; deleted users are omitted; create GET returns 200.

- [ ] **Step 6: Commit the shared form contract**

```bash
git add wagtail/admin/comment_mentions.py wagtail/admin/forms/comment_mentions.py wagtail/admin/forms/comments.py wagtail/admin/forms/pages.py wagtail/admin/panels/comment_panel.py wagtail/admin/tests/test_comment_mentions.py wagtail/admin/tests/test_edit_handlers.py
git commit -m "Validate comment and reply mention payloads"
```

---

### Task 5: Permission-Filtered Candidate Services and Both Suggestion Endpoints

**Files:**
- Modify: `wagtail/admin/comment_mentions.py`
- Create: `wagtail/admin/views/pages/comment_mentions.py`
- Modify: `wagtail/admin/forms/comment_mentions.py`
- Modify: `wagtail/admin/forms/comments.py`
- Modify: `wagtail/admin/viewsets/pages.py`
- Modify: `wagtail/admin/urls/pages.py`
- Modify: `wagtail/admin/views/pages/edit.py`
- Modify: `wagtail/admin/tests/test_comment_mentions.py`
- Modify: `wagtail/admin/tests/test_edit_handlers.py`
- Modify: `wagtail/admin/tests/pages/test_create_page.py`
- Modify: `wagtail/admin/tests/pages/test_edit_page.py`

**Interfaces:**
- Consumes: normalized labels and form deltas.
- Produces: database-filtered saved/future candidate querysets, new-target resolution, exact suggestion JSON, and saved/create URLs.

- [ ] **Step 1: Add failing candidate and endpoint tests**

Create these test classes in `test_comment_mentions.py`: `TestPageMentionCandidates`, `TestFuturePageMentionCandidates`, `TestPageMentionSuggestionView`, and `TestCreateMentionSuggestionView`.

The response assertion is exact:

```python
self.assertJSONEqual(
    response.content,
    {
        "results": [
            {
                "id": str(self.editor.pk),
                "label": "@jane@example.com",
                "email": "jane@example.com",
                "username": self.editor.get_username(),
            }
        ]
    },
)
```

Cover direct/inherited change permission, add-only future owner, add-only non-owner exclusion, superuser, direct/group `access_admin`, inactive target exclusion before slicing, comments disabled, missing `CommentPanel`, unauthorized requester, stale saved and create content types, invalid parent/type/model, child-model viewset routing, empty/65-unit/33-emoji query bounds, current configured email, blank-email display-name/username fallback, overlong label truncation, deterministic username/PK order, ten-result cap, bounded query count, UUID IDs, and no edit URL/notification/permission keys. Add browser-shaped form tests for one bulk comment/reply resolution call, exact field error attribution, prepared primary keys, duplicate occurrence keys across different messages, sibling form errors, deleted messages, and invalid-target bound redisplay.

- [ ] **Step 2: Verify the endpoints fail before implementation**

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.test_comment_mentions.TestPageMentionCandidates \
  wagtail.admin.tests.test_comment_mentions.TestFuturePageMentionCandidates \
  wagtail.admin.tests.test_comment_mentions.TestPageMentionSuggestionView \
  wagtail.admin.tests.test_comment_mentions.TestCreateMentionSuggestionView
```

Expected: FAIL because the shared views/services and create URL do not exist.

- [ ] **Step 3: Implement complete database-backed candidate querysets**

Add these public functions to `comment_mentions.py`:

```python
def users_with_admin_access(queryset):
    access_admin = Permission.objects.get(
        content_type__app_label="wagtailadmin",
        codename="access_admin",
    )
    return (
        queryset.filter(is_active=True)
        .filter(
            Q(is_superuser=True)
            | Q(user_permissions=access_admin)
            | Q(groups__permissions=access_admin)
        )
        .distinct()
    )


def page_mention_candidates(page):
    return users_with_admin_access(
        page_permission_policy.users_with_permission_for_instance("change", page)
    )


def future_page_mention_candidates(*, parent_page, owner):
    ancestors = parent_page.get_ancestors(inclusive=True)
    change_groups = GroupPagePermission.objects.filter(
        page__in=ancestors,
        permission__codename=get_permission_codename("change", Page._meta),
    ).values("group_id")
    add_groups = GroupPagePermission.objects.filter(
        page__in=ancestors,
        permission__codename=get_permission_codename("add", Page._meta),
    ).values("group_id")
    users = get_user_model()._default_manager.filter(is_active=True).filter(
        Q(is_superuser=True)
        | Q(groups__in=change_groups)
        | (Q(pk=owner.pk) & Q(groups__in=add_groups))
    )
    return users_with_admin_access(users)
```

Use available model fields among `first_name`, `last_name`, `EMAIL_FIELD`, and `USERNAME_FIELD` for the `icontains` OR query; deduplicate field names before building `Q` objects, order by configured username field and PK, slice to ten after active/admin/page eligibility filters, then generate `id`, `label`, `email`, and optional distinct `username`. `email` comes from `current_mention_email(user)` and may be empty when `normalize_mention_label` used a fallback.

Add four exact public interfaces. `comments_available_for_page_model(page_model: type[Page]) -> bool` returns false when `WAGTAILADMIN_COMMENTS_ENABLED` is false and otherwise tests for the `comments` formset on the model's edit-handler form class. `search_mention_candidates(candidates, query: str) -> list[dict[str, str]]` enforces the query contract, applies the available-model-field OR query, orders, slices, and maps the exact wire result. `resolve_new_mention_users(occurrences, candidates) -> tuple[object, ...]` fetches all prepared canonical IDs in one candidates query, returns users aligned with the input occurrence order, and rejects a missing user or label that differs from `normalize_mention_label(user)`. Define a translated `InvalidMentionTargets(ValidationError)` carrying only invalid input indices. Occurrence keys are unique only within one message, so neither resolver output nor failure attribution may use keys across the flattened comment/reply batch. `resolve_creatable_page_model(request, parent_page, app_label, model_name) -> type[Page]` applies the same content-type, Page-subclass, parent-permission, `creatable_subpage_models`, and `can_create_at` gates as `CreateView.dispatch`.

Call `resolve_new_mention_users` once from a reusable `CommentFormSet.validate_new_mentions(candidates)` across non-deleted top-level and nested reply forms. Use `page_mention_candidates(self.instance)` when the page has a PK; otherwise use `future_page_mention_candidates(parent_page=self.parent_page, owner=self.for_user)`. Skip each form that already has errors without suppressing valid siblings, map invalid indices back to exact forms, retain the submitted occurrence list for bound redisplay, add the generic failure to each exact `mentions` field, and re-raise so the same helper can trigger Task 8's provisional-create rollback. `CommentFormSet.clean()` catches that exception after field errors have been attached.

- [ ] **Step 4: Implement saved/create views and main routing**

Create `wagtail/admin/views/pages/comment_mentions.py` with:

```python
class PageCommentMentionSuggestionsView(View):
    def dispatch(self, request, page_id, **kwargs):
        page = get_object_or_404(Page, pk=page_id)
        if page.specific_class is None:
            raise PageClassNotFoundError
        self.page = page.specific
        if not self.page.permissions_for_user(request.user).can_edit():
            raise PermissionDenied
        if not comments_available_for_page_model(type(self.page)):
            raise Http404
        self.candidates = page_mention_candidates(self.page)
        return super().dispatch(request, page_id, **kwargs)

    def get(self, request, page_id, **kwargs):
        return JsonResponse({
            "results": search_mention_candidates(
                self.candidates,
                request.GET.get("q", ""),
            )
        })


class CreatePageCommentMentionSuggestionsView(View):
    def dispatch(
        self,
        request,
        content_type_app_name,
        content_type_model_name,
        parent_page_id,
        **kwargs,
    ):
        self.parent_page = get_object_or_404(Page, pk=parent_page_id).specific
        self.page_model = resolve_creatable_page_model(
            request=request,
            parent_page=self.parent_page,
            app_label=content_type_app_name,
            model_name=content_type_model_name,
        )
        if not comments_available_for_page_model(self.page_model):
            raise Http404
        self.candidates = future_page_mention_candidates(
            parent_page=self.parent_page,
            owner=request.user,
        )
        return super().dispatch(request, **kwargs)

    def get(self, request, **kwargs):
        return JsonResponse({
            "results": search_mention_candidates(
                self.candidates,
                request.GET.get("q", ""),
            )
        })
```

Saved dispatch must resolve the specific page, require requester `can_edit`, comments enabled, and a comment formset. Create dispatch must mirror `CreateView`: resolve content type/model/parent, require a `Page` subclass, `creatable_subpage_models`, `can_create_at`, and requester parent permission.

Remove the superseded relation-era endpoint/helper from `views/pages/edit.py` and `forms/comments.py`. On main, register viewset names `comment_mention_suggestions` and `create_comment_mention_suggestions`, classes, cached properties, and these URL names. The create route must dispatch through the requested child app/model viewset rather than choosing from the parent page ID:

```python
"wagtailadmin_pages:comment_mention_suggestions"
"wagtailadmin_pages:create_comment_mention_suggestions"
```

Make `CommentFormSet.serialize()` choose the saved-page URL when `instance.pk` exists and the parent/content-type URL otherwise.

- [ ] **Step 5: Run permission, URL, query, and UUID tests**

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.test_comment_mentions \
  wagtail.admin.tests.test_edit_handlers.TestCommentPanel \
  wagtail.admin.tests.pages.test_create_page.TestCommenting.test_comments_enabled_by_default \
  wagtail.admin.tests.pages.test_edit_page.TestCommenting.test_comment_mention_suggestions \
  wagtail.admin.tests.pages.test_edit_page.TestCommenting.test_comment_mention_suggestions_require_page_edit_permission \
  wagtail.admin.tests.pages.test_page_viewset.TestPageViewSetRegistry.test_as_view

USE_EMAIL_USER_MODEL=yes python runtests.py -- \
  wagtail.admin.tests.test_comment_mentions \
  wagtail.admin.tests.test_edit_handlers.TestCommentPanel
```

Expected: all PASS; create GET includes a resolvable create suggestion URL; query-count assertions stay fixed as candidate count grows.

- [ ] **Step 6: Commit candidate services and routes**

```bash
git add wagtail/admin/comment_mentions.py wagtail/admin/views/pages/comment_mentions.py wagtail/admin/forms/comment_mentions.py wagtail/admin/forms/comments.py wagtail/admin/viewsets/pages.py wagtail/admin/urls/pages.py wagtail/admin/views/pages/edit.py wagtail/admin/tests/test_comment_mentions.py wagtail/admin/tests/test_edit_handlers.py wagtail/admin/tests/pages/test_create_page.py wagtail/admin/tests/pages/test_edit_page.py
git commit -m "Add permission-aware mention suggestions"
```

---

### Task 6: Change Collection and Mention-Aware Audit Data

**Files:**
- Create: `wagtail/admin/commenting.py`
- Modify: `wagtail/models/pages.py`
- Modify: `wagtail/admin/views/pages/edit.py`
- Create: `wagtail/admin/tests/test_comment_notifications.py`
- Modify: `wagtail/admin/tests/pages/test_edit_page.py`

**Interfaces:**
- Consumes: comment/reply form `mention_changes`.
- Produces: one `CommentingChanges` object and exact audit deltas for both message types.

- [ ] **Step 1: Write failing collection and audit tests**

Create the module and tests around these data types:

```python
@dataclass(frozen=True)
class MentionedMessage:
    comment: Comment
    reply: CommentReply | None
    changes: MentionChanges


@dataclass
class CommentingChanges:
    new_comments: list[Comment]
    deleted_comments: list[Comment]
    resolved_comments: list[Comment]
    edited_comments: list[Comment]
    new_replies: list[tuple[Comment, list[CommentReply]]]
    deleted_replies: list[tuple[Comment, list[CommentReply]]]
    edited_replies: list[tuple[Comment, list[CommentReply]]]
    mentions: list[MentionedMessage]
```

Assert mention-only edits appear in `edited_comments`/`edited_replies`, added/removed entries are paired to the exact message by object identity, deleted parent/reply forms contribute no mention reason, formset order is retained, collection performs no queries, and the same occurrence UUID may be reused by different messages without collision. Audit JSON is:

```json
"mentions": {
  "added": [{"key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb", "user_id": "42"}],
  "removed": [{"key": "f4cf21fd-7dad-40e0-83da-d90310d2425f", "user_id": "17"}]
}
```

- [ ] **Step 2: Run and verify audit deltas are absent**

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.test_comment_notifications.TestCommentingChanges \
  wagtail.admin.tests.test_comment_notifications.TestMentionAuditData
```

Expected: FAIL because `wagtail.admin.commenting` and mention audit data do not exist.

- [ ] **Step 3: Implement one change collector and audit dispatcher**

Create:

```python
def collect_commenting_changes(comments_formset) -> CommentingChanges:
    new_comments = list(comments_formset.new_objects)
    deleted_comments = list(comments_formset.deleted_objects)
    changed_comments = list(comments_formset.changed_objects)
    mention_changes = []
    deleted_comment_forms = set(comments_formset.deleted_forms)
    for comment_form in comments_formset.forms:
        if comment_form in deleted_comment_forms:
            continue
        if comment_form.mention_changes.added or comment_form.mention_changes.removed:
            mention_changes.append(
                MentionedMessage(
                    comment=comment_form.instance,
                    reply=None,
                    changes=comment_form.mention_changes,
                )
            )
        replies_formset = comment_form.formsets["replies"]
        deleted_reply_forms = set(replies_formset.deleted_forms)
        for reply_form in replies_formset.forms:
            if reply_form in deleted_reply_forms:
                continue
            if reply_form.mention_changes.added or reply_form.mention_changes.removed:
                mention_changes.append(
                    MentionedMessage(
                        comment=comment_form.instance,
                        reply=reply_form.instance,
                        changes=reply_form.mention_changes,
                    )
                )

    return CommentingChanges(
        new_comments=new_comments,
        deleted_comments=deleted_comments,
        resolved_comments=get_resolved_comments(changed_comments),
        edited_comments=get_edited_comments(changed_comments),
        new_replies=get_new_replies(comments_formset.forms),
        deleted_replies=get_deleted_replies(comments_formset.forms),
        edited_replies=get_edited_replies(comments_formset.forms),
        mentions=mention_changes,
    )


def log_commenting_changes(*, changes, revision, actor) -> None:
    for comment in changes.new_comments:
        comment.log_create(
            page_revision=revision,
            user=actor,
            mention_changes=_changes_for(comment, changes),
        )

    for comment in changes.edited_comments:
        comment.log_edit(
            page_revision=revision,
            user=actor,
            mention_changes=_changes_for(comment, changes),
        )

    for comment in changes.resolved_comments:
        comment.log_resolve(page_revision=revision, user=actor)

    for comment in changes.deleted_comments:
        comment.log_delete(page_revision=revision, user=actor)

    for comment, replies in changes.new_replies:
        for reply in replies:
            reply.log_create(
                page_revision=revision,
                user=actor,
                mention_changes=_changes_for(reply, changes),
            )

    for comment, replies in changes.edited_replies:
        for reply in replies:
            reply.log_edit(
                page_revision=revision,
                user=actor,
                mention_changes=_changes_for(reply, changes),
            )

    for comment, replies in changes.deleted_replies:
        for reply in replies:
            reply.log_delete(page_revision=revision, user=actor)
```

The collector must snapshot `new_objects`, `deleted_objects`, and `changed_objects` once, then attach each form's `mention_changes`; no model queries may rediscover the delta after save. `_changes_for()` must match the exact `Comment` or `CommentReply` object by identity rather than by occurrence key, user ID, equality, or primary key alone.

Define the collection helpers with these exact semantics:

```python
def get_resolved_comments(changed_objects):
    return [obj for obj, fields in changed_objects if obj.resolved_at and "resolved" in fields]


def get_edited_comments(changed_objects):
    return [obj for obj, fields in changed_objects if {"text", "mentions"} & set(fields)]


def _group_reply_formset_objects(comment_forms, attribute):
    grouped = []
    for comment_form in comment_forms:
        objects = list(getattr(comment_form.formsets["replies"], attribute, []))
        if objects:
            grouped.append((comment_form.instance, objects))
    return grouped


def get_new_replies(comment_forms):
    return _group_reply_formset_objects(comment_forms, "new_objects")


def get_deleted_replies(comment_forms):
    return _group_reply_formset_objects(comment_forms, "deleted_objects")


def get_edited_replies(comment_forms):
    grouped = []
    for comment_form in comment_forms:
        replies = [
            reply
            for reply, fields in getattr(
                comment_form.formsets["replies"], "changed_objects", []
            )
            if {"text", "mentions"} & set(fields)
        ]
        if replies:
            grouped.append((comment_form.instance, replies))
    return grouped
```

Extend `Comment._log` and `CommentReply._log` with optional `mention_changes`, including only stable `key`/`user_id` values. Do not log labels, message search text, or email.

- [ ] **Step 4: Replace view-local change/audit code and bridge ordinary notifications**

Make `EditView.get_commenting_changes()` and `EditView.log_commenting_changes()` thin delegates. Remove the dead `comments_formset.save_mentions()`, `CommentMention.notified_at`, `new_mentions`, and `mark_comment_mentions_notified()` prototype paths. Until Task 8 installs Task 7's recipient planner, keep only the ordinary upstream subscriber/thread notification behavior reading `CommentingChanges` attributes. It must return early for mention-only or edit-only changes and must not synthesize direct mention mail, query lookup rows, or duplicate Task 7's planner.

Rewrite the three stale prototype action tests that submit a list of user IDs or treat `comment.mentions` as a relation. Use the five-field occurrence payload and generic validation error where an action-level assertion remains useful; replace relation/delivery-state expectations with durable collection/audit integration coverage. Preserve all existing non-mention notification tests.

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.test_comment_notifications \
  wagtail.admin.tests.pages.test_edit_page.TestCommenting
```

Expected: all collection/audit and existing comment tests PASS.

- [ ] **Step 5: Commit collection and audit behavior**

```bash
git add wagtail/admin/commenting.py wagtail/models/pages.py wagtail/admin/views/pages/edit.py wagtail/admin/tests/test_comment_notifications.py wagtail/admin/tests/pages/test_edit_page.py
git commit -m "Audit comment and reply mention changes"
```

---

### Task 7: Recipient-Specific Notifications and Exact Template Copy

**Files:**
- Create: `wagtail/admin/comment_notifications.py`
- Modify: `wagtail/admin/templates/wagtailadmin/notifications/updated_comments.txt`
- Modify: `wagtail/admin/templates/wagtailadmin/notifications/updated_comments.html`
- Modify: `wagtail/admin/templates/wagtailadmin/notifications/updated_comments_subject.txt`
- Modify: `wagtail/admin/tests/test_comment_notifications.py`

**Interfaces:**
- Consumes: `CommentingChanges` from Task 6.
- Produces: recipient-complete contexts, identical-context grouping, and `schedule_comment_notifications(page, editor, changes)`.

- [ ] **Step 1: Write failing recipient and template tests**

Create exact tests for:

```python
payloads = build_recipient_payloads(
    page=self.page,
    editor=self.actor,
    changes=self.changes,
)
self.assertEqual(payloads[self.mentioned_subscriber.pk].mentioned_comments, [comment_b])
self.assertIn(comment_a, payloads[self.mentioned_subscriber.pk].new_comments)
```

Cover actor exclusion by canonical PK; profile preference opt-out; inactive/deleted/no-email targets; a direct mention when the target's page subscription has `comment_notifications=False`; subscriber/thread/direct overlap; mention B plus subscription change A; repeated occurrences in one message; the same occurrence UUID reused by different messages; prepared/display and UUID user IDs; multiple messages; comment/reply context; exact-message pruning; independent per-recipient containers; failed send; empty-payload callback avoidance; and no delivery before transaction commit. Preserve the upstream thread scope exactly: thread-only participants receive only resolved comments and new replies for threads they participate in, never deleted comments or unrelated global changes. Global subscribers still receive all ordinary new/resolved/deleted-comment and new-reply sections. Prove lookup-state independence in both directions: an added occurrence notifies even when its exact message/user lookup row already exists, while a lookup row without an added occurrence creates no mention reason.

Exercise grouping identity collisions explicitly: a `Comment` and `CommentReply` with the same numeric PK, same-text distinct saved messages, and distinct deleted/unsaved objects with `pk=None` must produce distinct signatures unless every ordered section identity actually matches.

Use `captureOnCommitCallbacks(execute=True)` for `TestCase`: assert no mail inside the context and assert callbacks/mail only after context exit. Add an inner `transaction.atomic()` rollback case proving its callback and mail are discarded. Keep mail patches active through callback execution and patch `wagtail.admin.mail.send_mail` for failure behavior rather than making `send_notification` raise. A failed address must be logged, must not escape the callback, must not prevent attempts to later recipients in the group, and must create no retry or delivery state.

Assert exact translated source output:

- Subject with any mention: `{{ editor }} mentioned you in comments on "{{ title }}"`.
- Intro with any mention: same sentence plus period.
- Section order: `Mentions`, `New comments`, `Resolved comments`, `Deleted comments`, `New replies`.
- Mentioned comment example: `Comment: "Please review this section"`.
- Mentioned reply example: `Reply to "Please review this section": "I have updated it"`.
- A message rendered in `Mentions` is absent from later sections for that recipient.

- [ ] **Step 2: Run and verify old global deduplication fails**

Run:

```bash
python runtests.py -- wagtail.admin.tests.test_comment_notifications
```

Expected: FAIL because the Task 7 planner does not exist and the current templates have no recipient-specific mention sections.

- [ ] **Step 3: Implement the planner and on-commit delivery**

Create:

```python
@dataclass
class RecipientPayload:
    user: object
    new_comments: list[Comment] = field(default_factory=list)
    resolved_comments: list[Comment] = field(default_factory=list)
    deleted_comments: list[Comment] = field(default_factory=list)
    replied_comments: list[dict] = field(default_factory=list)
    mentioned_comments: list[Comment] = field(default_factory=list)
    mentioned_replies: list[dict] = field(default_factory=list)

    @property
    def has_mentions(self):
        return bool(self.mentioned_comments or self.mentioned_replies)


def schedule_comment_notifications(*, page, editor, changes) -> None:
    payloads = build_recipient_payloads(page=page, editor=editor, changes=changes)
    if not payloads:
        return
    groups = group_identical_payloads(payloads)

    def send():
        for users, section_context in groups:
            send_notification(
                users,
                "updated_comments",
                {"page": page, "editor": editor, **section_context},
            )

    transaction.on_commit(send)
```

Implement `build_recipient_payloads(*, page, editor, changes) -> dict[object, RecipientPayload]` in four fixed passes:

1. Seed global subscribers with independent copies of the existing notification-worthy new/resolved/deleted-comment and new-reply sections.
2. Add only resolved comments and new replies for each thread participant's affected threads. Do not exclude global subscribers early; merge reasons and deduplicate exact message identities instead. Edits and deleted replies never create ordinary mail, and thread-only participants never receive deleted comments or unrelated changes.
3. Read `user_id` from every `MentionedMessage.changes.added` occurrence, prepare it through the configured user primary-key field, resolve all direct targets in one active-user query, map prepared/display aliases to the same user, and add one exact comment/reply reason per target and message. Do not query occurrence keys or inverse lookup rows. Existing lookup rows do not suppress a new occurrence, and new lookup rows do not create notification novelty.
4. For each recipient independently, remove an exactly mentioned comment only from comment sections and remove an exactly mentioned reply only from that thread's reply list, preserving other replies and dropping an empty thread entry.

Every pass excludes `editor.pk`, preserves change order, drops empty payloads, and keys the map by canonical user PK. Each `RecipientPayload` must own its list objects and each `replied_comments` entry must own its nested reply list so pruning one recipient cannot mutate another. Define `mentioned_replies` entries exactly as `{"comment": parent_comment, "reply": reply}`; ordinary `replied_comments` remains `{"comment": parent_comment, "replies": [...]}`.

Implement `group_identical_payloads(payloads)` with a signature containing every ordered section identity and reply nesting. Use `(model label, pk)` for saved objects and Python object identity for `pk=None`, so equal numeric comment/reply PKs, same-text messages, and distinct deleted objects never collide. It returns `(users, section_context)` without a shared `user`; `schedule_comment_notifications` adds `page` and `editor`, while existing `send_notification` supplies each recipient's `user`, language, active/email/profile filtering, and failure logging. A no-email or opted-out active target may exist in the planner payload but sends no mail; inactive/deleted direct targets are absent from the one active-user lookup. Ignore `send_notification`'s false return, create no delivery state/retry, and register no `on_commit` callback when payloads are empty.

- [ ] **Step 4: Update all three templates and run exact-copy tests**

Use `{% if mentioned_comments or mentioned_replies %}` in subject/body templates. Subject and `.txt` are plain MIME text, not markup: retain literal readable page/editor/comment/reply values and the existing `safe` handling needed to prevent Django from converting ordinary apostrophes and ampersands into HTML entities. Preserve their non-mention wording, section order, whitespace, and page-edit link byte-for-byte, and render hostile-looking input literally as text. The `.html` alternative must use normal Django autoescaping with no `safe` on page/editor/comment/reply content. There is no separate mention-label interpolation; the saved label is already ordinary message text. Add exact plain-text and HTML golden tests, including literal hostile text in `.txt`, escaped hostile content in HTML, and the HTML alternate with `WAGTAILADMIN_NOTIFICATION_USE_HTML=True`.

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.test_comment_notifications \
  wagtail.admin.tests.pages.test_edit_page.TestCommenting
```

Expected: all notification, order, preference, failure, escaping, upstream-copy, and on-commit tests PASS.

- [ ] **Step 5: Commit notification planning**

```bash
git add wagtail/admin/comment_notifications.py wagtail/admin/templates/wagtailadmin/notifications/updated_comments.txt wagtail/admin/templates/wagtailadmin/notifications/updated_comments.html wagtail/admin/templates/wagtailadmin/notifications/updated_comments_subject.txt wagtail/admin/tests/test_comment_notifications.py
git commit -m "Notify users about exact comment mentions"
```

---

### Task 8: Atomic Edit and Create Lifecycles

**Files:**
- Modify: `wagtail/admin/views/pages/edit.py`
- Modify: `wagtail/admin/views/pages/create.py`
- Modify: `wagtail/admin/forms/comments.py`
- Modify: `wagtail/admin/tests/pages/test_edit_page.py`
- Modify: `wagtail/admin/tests/pages/test_create_page.py`
- Modify: `wagtail/admin/tests/test_workflows.py`

**Interfaces:**
- Consumes: form deltas, change collector, audit dispatcher, notification scheduler, actual-page candidate queryset.
- Produces: no-partial-save integration across the nine real action cores: edit `save_action` (HTML and Accept-JSON autosave/overwrite), `publish_action`, `submit_action`, `restart_workflow_action`, `perform_workflow_action`, and `cancel_workflow_action`; create `save_action` (HTML and Accept-JSON), `publish_action`, and `submit_action`. Publish and submit do not have separate JSON lifecycle handlers.

- [ ] **Step 1: Add failing full-lifecycle regressions**

Use compact shared payload/occurrence helpers and real text/ranges in every payload; never duplicate giant POST dictionaries or submit a phantom ID with unrelated text. Add tests for:

- top-level and reply mention create/edit/remove;
- mention-only edit dirty/audit behavior;
- ordinary save with another author's unchanged hydrated mentions;
- retained target rename, deactivation, or permission loss preserves the stored occurrence JSON and exact lookup row without a comment audit entry, mention delta, or notification; target deletion preserves stored JSON but cascades the lookup row and yields no live hydrated metadata, comment audit entry, mention delta, or notification;
- edit HTML save, JSON save and revision overwrite, publish, submit, restart-from-needs-changes, real task workflow action, and cancel;
- create HTML save, JSON save, publish, and submit with comment and reply mentions;
- target permission loss between future validation and provisional save;
- malformed/new-ineligible occurrence leaves no page/revision/comment/reply/audit/mail;
- valid create/edit/remove synchronizes exact top-level/reply lookup rows, repeated occurrences collapse, and rollback leaves no partial lookup rows;
- mail callback runs only after the `captureOnCommitCallbacks(execute=True)` context exits;
- an ineligible top-level mention and an ineligible reply mention each leave an active workflow untouched during cancellation, while an unrelated invalid page field preserves Wagtail's existing cancel-anyway behavior.

Across the action matrix, assert stored occurrence JSON, exact `CommentMention` / `CommentReplyMention` target sets, revision and audit identity, and direct mail after commit. Preserve ordinary subscriber behavior on edit actions. Create actions must instead assert direct-mention delivery, actor exclusion, and the newly saved actor subscription because no non-actor page subscription can predate the page. Reuse the real workflow setup patterns from `test_workflows.py` rather than mocking method selection.

Add rollback-placement tests for all nine action cores by wrapping the real scheduler so it registers its `on_commit` callback and then raises. Because scheduling is the last database-lifecycle operation, these tests exercise real publish/workflow actions before the exception. In addition to unchanged row counts and no surviving callback/mail, edit cases must assert the original page title/content/live flags/latest-revision pointer, comment/reply text and occurrence JSON, exact lookup targets, subscription values, and workflow state values. Across the three create cases, configure the default privacy setting as login-only, password, and groups respectively so each rollback proves that real privacy rows and group links disappear; also assert unchanged parent `numchild`. This promise covers transactional database state and mention email scheduling, not arbitrary external effects produced by third-party hooks or signals.

Representative create assertion:

```python
with self.captureOnCommitCallbacks(execute=True):
    response = self.client.post(
        self.add_url,
        post_data,
        headers={"Accept": "application/json"},
    )
self.assertEqual(response.status_code, 200)
self.assertEqual(SimplePage.objects.filter(slug="mentioned-page").count(), 1)
self.assertEqual(
    SimplePage.objects.get(slug="mentioned-page")
    .wagtail_admin_comments.get()
    .mentions,
    [occurrence],
)
```

- [ ] **Step 2: Run focused lifecycle tests and verify failures**

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.pages.test_edit_page.TestCommenting \
  wagtail.admin.tests.pages.test_create_page.TestCommenting \
  wagtail.admin.tests.test_workflows.TestCommentMentionWorkflows
```

Expected: FAIL because lookup synchronization and the Task 7 scheduler are not integrated, create does not collect/audit/notify mentions, provisional permission loss is not reconstructed safely, and the nine action cores do not yet share one atomic comment lifecycle.

- [ ] **Step 3: Integrate edit actions with atomic lookup synchronization**

Add one small per-view integration helper and replace the Task 6 ordinary notification bridge/imports with these lifecycle operations:

```python
comments_formset.sync_mention_lookups()
changes = collect_commenting_changes(self.form.formsets["comments"])
log_commenting_changes(
    changes=changes,
    revision=revision,
    actor=self.request.user,
)
schedule_comment_notifications(
    page=self.page,
    editor=self.request.user,
    changes=changes,
)
```

In every successful edit/create action, begin with lookup synchronization and change collection only after `save_revision()`, the reliable point at which staged comment and reply primary keys exist. Extend edit `save_action`'s existing block and add one outer `transaction.atomic()` around each of the other five edit and three create cores. Keep page/comment/reply/revision persistence, lookup sync, audit rows, subscription/privacy rows, and publish/workflow database actions inside that action block. For submit, restart, and perform-workflow actions, preserve the existing audit-before-workflow order. For cancel, preserve the existing cancel-first order and perform comment audit afterward. Run `schedule_comment_notifications()` as the final operation inside every block, after the successful publish/workflow action. Its callback then survives only a successful outer commit, and a scheduler failure rolls back the entire action. Remove `send_commenting_notifications()` completely to prevent duplicate or immediate ordinary mail.

Keep after-hooks, response rendering, and messages outside the action block where existing behavior permits. `before_publish_page` must remain at its existing semantic point inside the publish transaction: after revision persistence and lookup synchronization, but before publishing. Collect the changes before the hook, then log and schedule them only after publishing. A hook response therefore still commits the draft revision and synchronized lookup rows while suppressing publish, comment audit, and comment notifications, matching the current edit behavior. Do not claim that the database transaction can undo arbitrary external side effects from hooks or signals.

`EditView.form_invalid()` currently cancels a workflow even when the form is invalid. Preserve that existing behavior for unrelated invalid page fields, wrapped in `transaction.atomic()`, but detect exact comment/reply `mentions` field errors and leave the workflow untouched for those errors.

- [ ] **Step 4: Recheck create targets on the provisional real page inside one transaction**

Add to `CommentFormSet`:

```python
def revalidate_new_mentions_for_page(self, page):
    self.validate_new_mentions(page_mention_candidates(page))
```

For each create core, use this fixed in-transaction order: `form.save(commit=False)`; for ordinary save and submit set `page.live = False`; provisionally call `parent_page.add_child(instance=page)`; immediately run actual-page `revalidate_new_mentions_for_page(page)`; then persist privacy, revision, subscription, lookup synchronization, and change collection. For ordinary save, log then schedule. For submit, log, start the workflow, then schedule. For publish, retain the submitted live state, run `before_publish_page`, publish only when it permits, then log and schedule. Scheduling is always last. No provisional write may occur outside the rollbackable outer transaction.

`validate_new_mentions()` maps invalid indices to exact fields and re-raises. After rollback, capture `{form.prefix: invalid_target_mentions}` plus the one generic error from the failed form, refresh `parent_page` so treebeard's in-memory `numchild` is restored, and build a brand-new page with the original owner/locale, a brand-new `PageSubscription`, and a brand-new bound form. Reapply the normal required-field deferral, validate it, and call `restore_required_fields()` before rendering. Map fresh comment/reply forms by prefix through `iter_mention_forms`, then restore each submitted occurrence list and exact generic `mentions` error before `form_invalid()` renders. Assert the rebuilt page has `pk is None`, `_state.adding is True`, `path == ""`, and `depth == 0`; each rebuilt comment/reply has `pk is None` and `_state.adding is True`.

The permission-loss HTML regressions must cover top-level comment and reply attribution and assert the exact field error, rebuilt bound `mentions` widget name/value, serialized `comments-data` occurrence, restored parent `numchild`, fresh unsaved instances, and absence of every provisional database row/callback. A Django response does not execute CommentApp, so it cannot contain the React-owned hidden inputs; the combined Task 10/12 frontend integration must assert that these hydrated occurrences render as the exact per-comment/reply hidden JSON values. Current JSON `form_invalid()` returns only `success/error_code/error_message`; Task 8 tests successful JSON save/overwrite separately and leaves per-message JSON error serialization to Task 10.

- [ ] **Step 5: Verify all edit/create paths and UUID users**

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.pages.test_edit_page.TestCommenting \
  wagtail.admin.tests.pages.test_create_page.TestCommenting \
  wagtail.admin.tests.test_workflows.TestCommentMentionWorkflows \
  wagtail.admin.tests.test_comment_notifications

USE_EMAIL_USER_MODEL=yes python runtests.py -- \
  wagtail.admin.tests.pages.test_edit_page.TestCommenting \
  wagtail.admin.tests.pages.test_create_page.TestCommenting \
  wagtail.admin.tests.test_workflows.TestCommentMentionWorkflows
```

Expected: all PASS; every action uses its declared post-revision ordering; exact-message lookup rows match occurrence target sets; no partial page/revision/comment/reply/lookup/log/subscription/privacy/workflow rows or mail callbacks remain in invalid/raised cases; UUID payloads serialize cleanly.

- [ ] **Step 6: Commit lifecycle integration**

```bash
git add wagtail/admin/views/pages/edit.py wagtail/admin/views/pages/create.py wagtail/admin/forms/comments.py wagtail/admin/tests/pages/test_edit_page.py wagtail/admin/tests/pages/test_create_page.py wagtail/admin/tests/test_workflows.py
git commit -m "Persist mentions across page comment lifecycles"
```

---

### Task 9: Pure Frontend Mention Wire, Query, and Display Helpers

**Files:**
- Create: `client/src/components/CommentApp/utils/mentions.ts`
- Create: `client/src/components/CommentApp/utils/mentions.test.ts`

**Interfaces:**
- Consumes: the backend five-field occurrence wire schema from Tasks 2-8.
- Produces: canonical occurrence conversion, query recognition, and all-or-nothing display segmentation for Tasks 11-13.

- [ ] **Step 1: Write the failing helper suite and freeze the public types**

Define tests against these exact exports:

```typescript
export interface SerializedMentionOccurrence {
  key: string;
  user_id: string;
  start: number;
  end: number;
  label: string;
}

export interface MentionOccurrence {
  key: string;
  userId: string;
  start: number;
  end: number;
  label: string;
}

export interface MentionSuggestion {
  id: string;
  label: string;
  email: string;
  username?: string;
}

export interface MentionedUser {
  email: string;
}

export interface MentionQuery {
  start: number;
  end: number;
  query: string;
}

export interface MentionTextPart {
  text: string;
  mention?: MentionOccurrence;
}

export function deserializeMentionOccurrences(
  values: readonly SerializedMentionOccurrence[],
): MentionOccurrence[];

export function serializeMentionOccurrences(
  values: readonly MentionOccurrence[],
): SerializedMentionOccurrence[];

export function findMentionQuery(
  value: string,
  selectionStart: number,
  selectionEnd: number,
): MentionQuery | null;

export function splitTextByMentions(
  value: string,
  mentions: readonly MentionOccurrence[],
): MentionTextPart[];
```

Cover snake/camel round trips, deterministic `(start, end, key)` sorting, duplicate labels/users, repeated occurrences, emoji and multiline offsets, and `MentionedUser.email` remaining separate from saved identity/label data.

For `splitTextByMentions`, cover integer and in-bounds checks, monotonic sorted non-overlap, negative/clamped ranges, ranges that split a UTF-16 surrogate pair, exact label slices, overlap/order failures, and valid-then-invalid input. One invalid occurrence must return exactly `[{ text: value }]`; it must not render the valid prefix as a mention.

For `findMentionQuery`, cover a collapsed caret at the beginning and in the middle of text, every accepted punctuation character (`_`, `.`, `+`, `-`, `'`, and a second `@`), Unicode letters/numbers, an ordinary `person@example.com` non-trigger, whitespace/newline/unsupported punctuation termination, a bare `@`, and exact 1/64/65 UTF-16-unit boundaries including astral characters.

- [ ] **Step 2: Run the helper suite and verify RED**

Run:

```bash
npm run test:unit -- --runInBand client/src/components/CommentApp/utils/mentions.test.ts
```

Expected: FAIL because `client/src/components/CommentApp/utils/mentions.ts` does not exist.

- [ ] **Step 3: Implement the pure helpers**

Use JavaScript string offsets directly as UTF-16 units. Query recognition uses the maximal accepted token run ending at the collapsed caret, requires the trigger `@` to be at the start or preceded by a non-token character, and accepts 1-64 UTF-16 units after the trigger. Sorting may normalize only already-valid occurrences; it must not repair malformed input. Display segmentation validates the complete list before producing any mention part. Never infer identity from label or email text.

- [ ] **Step 4: Run focused tests, lint, formatting, and type checking**

Run:

```bash
npm run test:unit -- --runInBand client/src/components/CommentApp/utils/mentions.test.ts
./node_modules/.bin/eslint --report-unused-disable-directives client/src/components/CommentApp/utils/mentions.ts client/src/components/CommentApp/utils/mentions.test.ts
./node_modules/.bin/prettier --check client/src/components/CommentApp/utils/mentions.ts client/src/components/CommentApp/utils/mentions.test.ts
npm run lint:ts
```

Expected: all commands PASS.

- [ ] **Step 5: Commit the helper contract**

```bash
git add client/src/components/CommentApp/utils/mentions.ts client/src/components/CommentApp/utils/mentions.test.ts
git commit -m "Add client-side mention wire helpers"
```

Expected: the commit contains only the two Task 9 files.

---

### Task 10: Server Rejection Serialization for Comments and Replies

**Files:**
- Modify: `wagtail/admin/forms/comments.py`
- Modify: `wagtail/admin/views/pages/create.py`
- Modify: `wagtail/admin/views/pages/edit.py`
- Modify: `wagtail/admin/tests/test_edit_handlers.py`
- Modify: `wagtail/admin/tests/pages/test_create_page.py`
- Modify: `wagtail/admin/tests/pages/test_edit_page.py`

**Interfaces:**
- Consumes: Task 8's atomic comment/reply form validation and existing comment serializer.
- Produces: optional bound `comments` data on invalid create/edit JSON responses for Task 12's rejection-only hydration path.
- Does not change frontend state or consume Task 9 types.

The invalid JSON response contract is:

```text
{
  success: false,
  error_code: string,
  error_message: string,
  comments?: CommentAppData
}
```

`comments` carries exact generic `mention_error` values on the affected comment/reply and `pk: null` for rejected unsaved messages. It is present only when bound comments were serialized safely.

- [ ] **Step 1: Write failing form/create/edit response tests**

Add comment and reply parity for:

- a structurally valid occurrence rejected only because its target disappeared or lost permission: retain the submitted text and occurrence list as bound working data and attach only the generic `mentions` error;
- malformed JSON, blank/oversized input, parser/digit-limit/recursion failure, or an invalid occurrence shape: serialize sanitized initial values and never echo the raw payload;
- an existing bound message: retain its real numeric PK;
- a rejected unsaved comment/reply: serialize `pk: null`;
- sibling messages: serialize independent errors and values with no target identifier or permission detail leakage;
- create and edit Accept-JSON validation failures: include top-level `comments` without changing the existing error fields; and
- failures with no safely serialized bound comments: omit `comments`.

- [ ] **Step 2: Run the server modules and verify RED**

Run:

```bash
python runtests.py -- wagtail.admin.tests.test_edit_handlers wagtail.admin.tests.pages.test_create_page wagtail.admin.tests.pages.test_edit_page
```

Expected: FAIL because invalid create/edit JSON responses do not yet carry the bound comment data required by the new assertions.

- [ ] **Step 3: Implement safe bound serialization in the form path**

Reuse the existing per-entry sanitizer and generic mention error. Preserve only structurally valid submitted occurrences rejected at target/permission validation. Structural/parser failures use sanitized model/form initial data. Keep comment and reply values/errors isolated, preserve `None` PKs, and never interpolate malformed payload content into the response.

- [ ] **Step 4: Add `comments` to invalid production JSON responses**

Update both production create and edit views. Do not change successful response semantics. Do not add `comments` to unrelated network/hydration errors, and do not expose target IDs beyond the already sanitized occurrence wire data.

- [ ] **Step 5: Verify server behavior and canonical server lint**

Run:

```bash
python runtests.py -- wagtail.admin.tests.test_edit_handlers wagtail.admin.tests.pages.test_create_page wagtail.admin.tests.pages.test_edit_page
make lint-server
```

Expected: all commands PASS; valid target/permission rejections redisplay safe working values, structural failures never echo raw input, and successful JSON responses are unchanged.

- [ ] **Step 6: Commit only the server transport slice**

```bash
git add wagtail/admin/forms/comments.py wagtail/admin/views/pages/create.py wagtail/admin/views/pages/edit.py wagtail/admin/tests/test_edit_handlers.py wagtail/admin/tests/pages/test_create_page.py wagtail/admin/tests/pages/test_edit_page.py
git commit -m "Serialize rejected comment mention state"
```

Expected: the commit contains only the six Task 10 files and no frontend migration.

---

### Task 11: Debounced and Race-Safe Suggestion Hook

**Files:**
- Create: `client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.ts`
- Create: `client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.test.tsx`

**Interfaces:**
- Consumes: Task 9 `MentionQuery` and `MentionSuggestion` plus the exact server `{results}` response.
- Produces: one request state machine for Task 12.

```typescript
export type MentionSuggestionStatus =
  | 'closed'
  | 'loading'
  | 'ready'
  | 'empty'
  | 'error';

export interface UseMentionSuggestionsOptions {
  url?: string;
  query: MentionQuery | null;
  composing: boolean;
  debounceMs?: number;
}

export interface UseMentionSuggestionsResult {
  status: MentionSuggestionStatus;
  suggestions: MentionSuggestion[];
  close(): void;
}
```

Query identity is the complete `(start, end, query)` tuple.

- [ ] **Step 1: Write failing fake-timer and deferred-request tests**

Create the shared editor directory before adding the hook files:

```bash
mkdir -p client/src/components/CommentApp/components/MentionEditor
```

Cover:

- missing URL/query and composition suppression;
- exactly 199/200 ms with a 200 ms default;
- immediate result clearing and request-generation invalidation on every effective tuple change;
- timer cancellation and abort/invalidation on changed query, close, composition, URL/query disappearance, unmount, and any suppression transition;
- request A settling during request B's debounce and after B is ready, for both stale success and stale non-`AbortError` rejection;
- every terminal state update guarded by the current request generation;
- `AbortError` remaining silent and non-OK/network failures becoming `error` only when current;
- explicit close latching across equal rerenders and releasing when any query tuple field changes;
- valid empty results becoming `empty`;
- response-wide validation: top-level object, `results` array, object items, required string `id`/`label`/`email`, empty-string email allowed, optional string `username`, and one malformed/mixed item making the whole response `error`; and
- relative URL resolution, replacement of all existing `q` values, and preservation/order of repeated non-`q` parameters.

- [ ] **Step 2: Run the hook suite and verify RED**

```bash
npm run test:unit -- --runInBand client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.test.tsx
```

Expected: FAIL because the hook does not exist.

- [ ] **Step 3: Implement the request state machine**

Use one timer and `AbortController` per effective query, plus a monotonically increasing generation invalidated before any asynchronous work can settle. Resolve the supplied URL against `window.location.origin`; use `searchParams.set('q', query.query)` so every old `q` is replaced while unrelated repeated parameters survive. Validate the entire response before publishing suggestions. `close()` aborts/invalidates and latches until the tuple changes.

- [ ] **Step 4: Verify the hook, formatting, lint, and types**

```bash
npm run test:unit -- --runInBand client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.test.tsx
./node_modules/.bin/eslint --report-unused-disable-directives client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.ts client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.test.tsx
./node_modules/.bin/prettier --check client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.ts client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.test.tsx
npm run lint:ts
```

Expected: all commands PASS, including both stale-success and stale-error races.

- [ ] **Step 5: Commit the isolated hook**

```bash
git add client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.ts client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.test.tsx
git commit -m "Make mention suggestions race safe"
```

Expected: the commit contains only the hook and its test.

---

### Task 12: Atomic Comment State and Mini Draftail Frontend Migration

**Files:**
- Modify: `client/src/components/CommentApp/state/comments.ts`
- Modify: `client/src/components/CommentApp/state/comments.test.ts`
- Modify: `client/src/components/CommentApp/state/settings.ts`
- Modify: `client/src/components/CommentApp/selectors/index.ts`
- Modify: `client/src/components/CommentApp/selectors/selectors.test.ts`
- Modify: `client/src/components/CommentApp/__fixtures__/state.tsx`
- Modify: `client/src/components/CommentApp/components/Form/index.tsx`
- Modify: `client/src/components/CommentApp/components/Form/index.test.tsx`
- Modify: `client/src/components/CommentApp/main.tsx`
- Create: `client/src/components/CommentApp/main.test.tsx`
- Modify: `client/src/components/CommentApp/main.scss`
- Create: `client/src/components/CommentApp/components/MentionEditor/draftail.ts`
- Create: `client/src/components/CommentApp/components/MentionEditor/draftail.test.ts`
- Create: `client/src/components/CommentApp/components/MentionEditor/index.tsx`
- Create: `client/src/components/CommentApp/components/MentionEditor/index.test.tsx`
- Create: `client/src/components/CommentApp/components/MentionText/index.tsx`
- Create: `client/src/components/CommentApp/components/MentionText/index.test.tsx`
- Delete: `client/src/components/CommentApp/components/MentionTextArea/index.tsx`
- Delete: `client/src/components/CommentApp/components/MentionTextArea/index.test.tsx`
- Delete: `client/src/components/CommentApp/components/Comment/CommentText.tsx`
- Delete: `client/src/components/CommentApp/components/Comment/CommentText.test.tsx`
- Modify: `client/src/components/CommentApp/components/Comment/index.tsx`
- Create: `client/src/components/CommentApp/components/Comment/index.test.tsx`
- Modify: `client/src/components/CommentApp/components/Comment/style.scss`
- Modify: `client/src/components/CommentApp/components/CommentReply/index.tsx`
- Create: `client/src/components/CommentApp/components/CommentReply/index.test.tsx`
- Modify: `client/src/entrypoints/admin/comments.js`
- Modify: `client/src/entrypoints/admin/comments.test.js`

**Interfaces:**
- Consumes: Task 9 occurrence/query/display helpers, Task 10 optional rejected `comments` transport, Task 11 hook, and existing `draftail`, `draft-js`, and `uuid` dependencies.
- Produces: occurrence-aware comment/reply Redux state, success and rejection hydration paths, complete hidden forms, toolbar-free Mini Draftail editing, and non-link saved mention rendering.
- Atomic boundary: all listed state, editor, renderer, comment/reply consumer, entrypoint, and tests migrate in this one task and one commit. Do not run a full TypeScript gate against a partial legacy `Mention`/new `MentionOccurrence` mixture.

State uses independently owned `MentionOccurrence[]` values:

```typescript
// Comment
mentions;
originalMentions;
newMentions;
newReplyMentions;
mentionError?: string;

// CommentReply
mentions;
originalMentions;
newMentions;
mentionError?: string;
```

The server wire types are explicit and remain snake_case at the boundary:

```typescript
interface InitialComment {
  pk: number | null;
  mentions: SerializedMentionOccurrence[];
  mention_error?: string;
}

interface InitialCommentReply {
  pk: number | null;
  mentions: SerializedMentionOccurrence[];
  mention_error?: string;
}

interface CommentAppData {
  mentioned_users: Record<string, MentionedUser>;
}
```

Deserialize occurrences only through Task 9 and copy `mentioned_users` into global `settings.mentionedUsers` without adding email to authors or entity data. Rejected hydration binds numeric-PK messages by PK. Within each parent formset, it binds `pk: null` messages by canonical submitted formset position; it never matches by text, label, or user. Missing, locally deleted, or resolved entries are skipped and never recreated.

Keep successful rebasing and rejected hydration separate:

```typescript
CommentApp.updateData(data: CommentAppData): void;
CommentApp.hydrateRejectedData(data: CommentAppData): void;
```

`updateData` remains success-only and may reset/rebase originals. `hydrateRejectedData` never rebases originals, resurrects removed entries, or marks an equal error-only response dirty.

Freeze the Draft conversion contract:

```typescript
export interface MentionEditorValue {
  value: string;
  mentions: MentionOccurrence[];
}

export function createMentionEditorState(
  value: string,
  mentions: readonly MentionOccurrence[],
): EditorState;

export function serializeMentionEditorState(
  editorState: EditorState,
): MentionEditorValue;

export function getMentionQueryFromEditorState(
  editorState: EditorState,
): MentionQuery | null;

export function insertMentionSuggestion(
  editorState: EditorState,
  query: MentionQuery,
  suggestion: MentionSuggestion,
  createKey?: () => string,
): EditorState;
```

Freeze the component contract:

```typescript
export interface MentionEditorProps {
  id: string;
  label: string;
  value: string;
  mentions: readonly MentionOccurrence[];
  mentionedUsers: Readonly<Record<string, MentionedUser>>;
  mentionSuggestionsUrl?: string;
  error?: string;
  describedBy?: string;
  className?: string;
  placeholder?: string;
  focusOnMount?: boolean;
  focusTarget?: boolean;
  onChange(value: string, mentions: MentionOccurrence[]): void;
}
```

**Binding entity correction:** use Draft.js `MUTABLE` `MENTION` entities plus immediate mismatch normalization. This supersedes the earlier plan/design `IMMUTABLE` mechanism wording. It is required to preserve the approved behavior where a partial edit removes identity but leaves the resulting characters as plain text.

- [ ] **Step 1: Write failing state, selector, form, hydration, and entrypoint tests**

Cover independently copied arrays **and occurrence objects** for comments, existing replies, and new replies; dirty comparison across key/user/range/label additions, removals, moves, and exact reverts; error-only state not dirty; equal reducer updates preserving `mentionError`; and only a semantically different local text/canonical-occurrence change clearing that message's error.

Assert every participating comment and reply renders a hidden `mentions` input containing the canonical JSON array, where each occurrence has exactly `key`, `user_id`, `start`, `end`, and `label`, including unchanged forms. Test `number | null` PKs, two rejected null-PK comments and two null-PK replies to prove positional isolation, rejected unsaved messages remaining in hidden forms, cancel deleting a bound `pk: null` message, cancel restoring saved existing values, current-email metadata changes not dirtying content, deleted metadata omission, and sibling error isolation.

Keep the public paths distinct:

- success `w-autosave:success` calls `updateData(detail.data.comments)`, rebases values, clears processed removals/errors, and preserves success focus behavior;
- `w-autosave:error` calls `hydrateRejectedData(detail.response.comments)` only when `detail.response.comments` exists;
- errors without `comments` do not mutate CommentApp state;
- rejected existing/unsaved messages return to editing/creating mode with valid working values while originals/removals stay unchanged.

- [ ] **Step 2: Write failing Draft conversion, editor, renderer, and integration tests**

In `draftail.test.ts`, cover plain/multiline hydration, emoji offsets, multiple blocks, repeated users, duplicate labels, deterministic extraction, edits before/after/through entities, cut, selected replacement, plain-text paste, query extraction, suggestion insertion with injected UUID, and text/entity undo/redo.

Hydration is all-or-nothing: validate canonical order, unique keys, non-overlap, bounds and UTF-16 boundaries, one-block containment, and exact label slices **before applying any entity**. One invalid/cross-block/mismatched occurrence produces plain text with no entities.

Prove `MUTABLE` partial edits keep edited characters, then remove the complete mismatched entity association using `EditorState.set` so normalization adds no undo entry. Suggestion insertion must replace query text, apply one entity, add one unlinked trailing space, and create one non-coalescing `EditorState.push(..., 'apply-entity')` undo boundary.

In `MentionEditor/index.test.tsx`, cover one Draftail contenteditable, no textarea/toolbars/format controls, local selection-only `EditorState` changes with no parent callback, parent callback only when serialized text/occurrences change, equal Redux echoes preserving selection/history, genuine external changes rehydrating, and metadata-only changes rerendering decoration without rehydration.

Unit tests assert handler and `EditorState` behavior: ready Enter prevents default and stops propagation before Draft inserts a newline; ordinary Enter is not intercepted and Draftail is configured multiline; Tab closes without interception; Ctrl/Cmd+B/I/U are prevented; pointer selection prevents blur and inserts at the saved Draft selection; and synthetic composition defers query recomputation until the next Draft `onChange`. Exercise cut/paste transformations through Draft handlers and editor state. Cover Arrow wrap, Escape, loading/ready/empty/error status, and one-step undo/redo. Task 13 owns native browser newline, paste, focus, and pointer behavior; Task 14 owns native IME/caret evidence.

Assert the actual contenteditable keeps Draftail's `role="textbox"` and `aria-multiline="true"` intact and receives the stable `id`, `data-focus-target`, `aria-autocomplete="list"`, and `aria-haspopup="listbox"`. Set `aria-controls` only while the real listbox exists and `aria-activedescendant` only while a valid option is active; remove popup ownership and active-option attributes when closed or stale. Do not set `aria-expanded` on the multiline textbox. Continue passing Draftail `ariaLabel` and merged/de-duplicated `ariaDescribedBy` through Draftail. Assert exact labels `Add a comment`, `Edit comment`, `Add a reply`, and `Edit reply`.

Renderer/integration tests cover escaped plain text, repeated/multiple/malformed ranges, `.comment__mention`, saved visible label, `data-mention-user-id`, separately hydrated `data-mention-email`, no admin link, comment/reply add/edit/save/cancel, and error isolation.

- [ ] **Step 3: Run the combined RED suite**

Run:

```bash
npm run test:unit -- --runInBand client/src/components/CommentApp client/src/entrypoints/admin/comments.test.js
```

Expected: FAIL because occurrence-aware state, rejection hydration, Mini Draftail helpers/components, and migrated consumers do not yet exist. Do not attempt to make an intermediate partial migration pass `npm run lint:ts`.

- [ ] **Step 4: Implement occurrence state, hidden forms, and separate hydration paths**

Create the new component directories before adding files:

```bash
mkdir -p client/src/components/CommentApp/components/MentionEditor client/src/components/CommentApp/components/MentionText
```

Deserialize all server occurrences through Task 9 and deep-copy arrays/elements at every initial/current/original boundary. Canonical serialized arrays drive dirty checks. Keep `mention_error` presentation-only. Restore ordinary `Author` to ID/name/avatar only and place current email exclusively under `settings.mentionedUsers`.

`updateData` performs success rebasing. `hydrateRejectedData` merges bound working values/errors without replacing originals or removed entries, restores exact edit/create modes, and keeps genuinely changed values dirty. Preserve bound unsaved messages until cancel. Keep all errors message-local.

Update the entrypoint listeners exactly as follows in behavior:

```javascript
document.addEventListener('w-autosave:success', ({ detail }) => {
  if (detail?.data?.comments) {
    commentApp.updateData(detail.data.comments);
  }
});

document.addEventListener('w-autosave:error', ({ detail }) => {
  if (detail?.response?.comments) {
    commentApp.hydrateRejectedData(detail.response.comments);
  }
});
```

- [ ] **Step 5: Implement deterministic Draft hydration, extraction, and insertion**

Use `ContentState.createFromText(value)` and map absolute UTF-16 offsets into ordinary Draft blocks. Validate the full list first. Create `MUTABLE` entities containing only `{ key, userId, label }`. Extraction joins blocks with `\n`, walks contiguous `MENTION` ranges, verifies entity text equals the snapshot label, converts to absolute offsets, and returns canonical occurrences.

On every Draft change, remove all associations for entities whose current text differs from their stored label by replacing current content with `EditorState.set`, then serialize. Insertion uses one final content state and one `apply-entity` push, followed by forced selection after the trailing space.

- [ ] **Step 6: Implement the accessible toolbar-free editor**

Configure controlled Draftail with one `MENTION` entity type whose required `source` is an inert component returning `null` and whose `decorator` is the mention decorator. The source is unreachable because the decorator never calls `onEdit`. Pass `topToolbar={null}`, `bottomToolbar={null}`, `commandToolbar={null}`, `commands={false}`, empty block/inline/control arrays, and disabled undo/redo controls. Keep every `EditorState` change locally, notifying the parent only for a serialized value/occurrence change. Pass `ariaLabel={label}` and `ariaDescribedBy` directly to Draftail; bridge ID, focus target, popup state, ownership, and active option to the actual Draft.js contenteditable. Merge caller and error descriptions rather than overwriting either. Assert no `.Draftail-Toolbar`, inert source, textarea, or formatting control is rendered.

Use the Task 11 hook, `onKeyDownCapture`, saved Draft selection for pointer insertion, and subsequent-`onChange` composition query recomputation. The decorator reads `mentionedUsers` from context, renders snapshot text plus separate metadata attributes, never calls Draftail `onEdit`, and never becomes a link.

- [ ] **Step 7: Migrate every comment and reply mode atomically**

Use stable IDs:

```text
comment-mention-editor-${localId}
comment-new-reply-mention-editor-${comment.localId}
comment-reply-mention-editor-${comment.localId}-${reply.localId}
```

Save/cancel text and occurrences together. New-reply cancel clears both; existing cancel restores both. Pass the message's own generic error and merged description IDs. Replace saved `CommentText` with `MentionText` for comments and replies, then delete both legacy/prototype components and tests listed above.

- [ ] **Step 8: Add CSS once and finish visual/accessibility states**

Import `draft-js/dist/Draft.css` exactly once from CommentApp `main.scss`. Style inline mentions, errors, selected options, popup scrolling, and forced-colors states in `Comment/style.scss`. There must be no Draftail toolbar DOM to hide. Remove prototype contenteditable/caret-walker styling.

- [ ] **Step 9: Run the complete frontend verification gate**

```bash
npm run test:unit -- --runInBand client/src/components/CommentApp client/src/entrypoints/admin/comments.test.js
./node_modules/.bin/eslint --report-unused-disable-directives client/src/components/CommentApp client/src/entrypoints/admin/comments.js client/src/entrypoints/admin/comments.test.js
./node_modules/.bin/prettier --check client/src/components/CommentApp client/src/entrypoints/admin/comments.js client/src/entrypoints/admin/comments.test.js
./node_modules/.bin/stylelint "client/src/components/CommentApp/**/*.scss"
npm run lint:ts
npm run build
```

Expected: all commands PASS; no toolbar/textarea remains; partial edits preserve plain characters but remove identity; rejection hydration remains dirty and message-local; and there are no spurious parent callbacks.

- [ ] **Step 10: Commit the complete atomic frontend migration**

```bash
git add -A -- client/src/components/CommentApp/state/comments.ts client/src/components/CommentApp/state/comments.test.ts client/src/components/CommentApp/state/settings.ts client/src/components/CommentApp/selectors/index.ts client/src/components/CommentApp/selectors/selectors.test.ts client/src/components/CommentApp/__fixtures__/state.tsx client/src/components/CommentApp/components/Form/index.tsx client/src/components/CommentApp/components/Form/index.test.tsx client/src/components/CommentApp/main.tsx client/src/components/CommentApp/main.test.tsx client/src/components/CommentApp/main.scss client/src/components/CommentApp/components/MentionEditor/draftail.ts client/src/components/CommentApp/components/MentionEditor/draftail.test.ts client/src/components/CommentApp/components/MentionEditor/index.tsx client/src/components/CommentApp/components/MentionEditor/index.test.tsx client/src/components/CommentApp/components/MentionText/index.tsx client/src/components/CommentApp/components/MentionText/index.test.tsx client/src/components/CommentApp/components/MentionTextArea/index.tsx client/src/components/CommentApp/components/MentionTextArea/index.test.tsx client/src/components/CommentApp/components/Comment/CommentText.tsx client/src/components/CommentApp/components/Comment/CommentText.test.tsx client/src/components/CommentApp/components/Comment/index.tsx client/src/components/CommentApp/components/Comment/index.test.tsx client/src/components/CommentApp/components/Comment/style.scss client/src/components/CommentApp/components/CommentReply/index.tsx client/src/components/CommentApp/components/CommentReply/index.test.tsx client/src/entrypoints/admin/comments.js client/src/entrypoints/admin/comments.test.js
git commit -m "Add Mini Draftail comment mention editing"
```

Expected: one reviewable commit contains the entire frontend state/editor/consumer migration and no server files.

---

### Task 13: Fresh-Database Chromium and Axe Browser Regression

**Files:**
- Create: `client/tests/integration/comment-mentions.test.js`
- Modify: `wagtail/test/settings_ui.py`
- Modify only for a verified browser defect: Task 12-owned CommentApp files and their focused tests

**Interfaces:**
- Consumes: Tasks 8-12, the production bundle, settings-UI server, create-page parent ID 2, and Task 12's stable editor IDs.
- Produces: automated primary Chromium/Axe evidence reusable on 7.4 in Task 15 and beta-or-later in Task 16.
- Browser scope: the default settings-UI user proves opaque string IDs; UUID/custom-PK behavior remains a backend/frontend-unit claim unless a separate UUID browser environment is actually provisioned.

Freeze these exact scenario values:

```javascript
const baselinePrefix = 'Mention baseline 😀\nReview with ';
const queryText = `${baselinePrefix}@adm`;
const selectedText = `${baselinePrefix}@admin@example.com`;
const insertedText = `${selectedText} `;
const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const occurrenceForUser = (userId) => ({
  key: expect.stringMatching(uuidPattern),
  user_id: userId,
  start: 32,
  end: 50,
  label: '@admin@example.com',
});
```

- [ ] **Step 1: Make the settings-UI database name configurable**

In `wagtail/test/settings_ui.py`, import `os` and set:

```python
DATABASES["default"]["NAME"] = os.environ.get(  # noqa: F405
    "WAGTAIL_UI_TEST_DB", "ui_tests.db"
)
```

Keep the existing default for ordinary integration use; Task 13 always supplies a fresh temporary path.

- [ ] **Step 2: Write the complete Playwright scenario**

Use `/admin/pages/add/demosite/standardpage/2/` and a 120-second test timeout. The scenario must:

1. Disable create autosave by setting `data-w-autosave-active-value="false"` before changing the title or comments.
2. Fill a unique required title, await its slug, open the first comment editor, type the first line, press Enter through `page.keyboard`, and type the second line up to but not including `@adm` through the browser.
3. Assert there is one contenteditable and no textarea, Draftail toolbar, formatting control, or rich-text widget.
4. Before typing `@adm`, register a one-shot route whose handler captures the request, awaits `route.fetch()`, parses the real response, then waits on a resolver before calling `route.fulfill({ response })`. Type `@adm`, await the handler reaching that hold point, assert loading and run loading Axe, then release the resolver. Assert the create suggestion endpoint URL. Locate the returned `admin` result, assert its `id` is a nonempty string, assign it to `capturedUserId`, and use that exact opaque value for every subsequent browser assertion; do not assume an AutoField value or coerce it to a number.
5. Select `admin` by keyboard and assert `insertedText`, inline `.comment__mention`, `data-mention-user-id` equal to the captured suggestion ID, `data-mention-email="admin@example.com"`, and the exact five-field object from `occurrenceForUser(capturedUserId)`. Capture its generated key. Prove one undo returns `queryText` with `[]` and one redo restores `insertedText`, the same key, and the complete occurrence containing `capturedUserId`. Press Backspace once to remove only the unlinked trailing space, then use `selectedText` as the persisted baseline.
6. Run Axe in four distinct states: loading, ready/open with options, empty/open against a guaranteed no-match query, and closed.
7. Install the create-response, `w-autosave:hydrate`, and `w-autosave:success` waiters first. On `#page-edit-form`, set `data-w-autosave-active-value="true"` and dispatch `new CustomEvent('w-unsaved:add', { bubbles: true, detail: { type: 'edits' } })` only after the exact hidden occurrence exists.
8. Capture the create POST JSON and assert it contains the exact five-field occurrence with the generated key and `capturedUserId`; await hydration and success, then assert the post-hydration DOM and hidden JSON retain that same complete occurrence. Resolve `response.url` against `TEST_ORIGIN`, then assert `form.action` and `page.url()` equal that absolute edit URL and that the resolved `hydrate_url` was requested. Assert the create and post-hydration edit suggestion endpoint URLs.
9. Reload/follow the edit URL and assert exact text, entity attributes, key, `capturedUserId`, offsets, label, and complete hidden JSON survive.
10. Restore `selectedText` and the captured occurrence before each destructive case. Inserting one ASCII character before the mention retains the key and changes offsets to 33/51; inserting after it retains the key and offsets 32/50. Partial replacement leaves the exact resulting plain text with `[]`; one undo restores the original text/entity/key and one redo removes it again. Whole replacement leaves its exact replacement text with `[]`. Assert complete hidden JSON after every operation.
11. Perform rich paste through a granted browser clipboard and `ControlOrMeta+V`, not a synthetic `ClipboardEvent`; assert exact plain text, no formatting DOM, and complete hidden JSON. Prove Ctrl/Cmd+B/I/U do not introduce formatting.
12. Restore `selectedText` and its captured exact occurrence between every destructive case.
13. Add/edit/cancel/save/reload a reply mention, selecting one reply suggestion by pointer; finally remove the reply occurrence while retaining its reply text.
14. Open results, press Tab, and prove focus moves normally while the listbox closes, popup-ownership and active-option attributes disappear, and no `aria-expanded` is set on the multiline textbox.
15. Assert the actual contenteditable keeps Draftail's `role="textbox"` and `aria-multiline="true"`, carries `aria-autocomplete="list"` and `aria-haspopup="listbox"`, and receives the accessible name, descriptions, focus target, and only live listbox relationships rather than wrapper-only attributes.
16. When evidence output is enabled, create its directory, restore `queryText`, open the ready popup, and capture `autocomplete-open.png`; then select the suggestion, remove its unlinked trailing space, reassert `selectedText` and the exact occurrence, and capture `after-redesign.png`. Await `document.fonts.ready` and stable animation frames and assert a 1024x768 viewport. Task 14 records HEAD/OID, Wagtail and Chromium versions, OS, URLs/states, dimensions, and checksums; Task 13 screenshots alone are not final metadata.

Task 13 does not exercise native IME or composition-caret behavior. Attribute those claims only to a separately recorded Task 14 run using a real installed IME; otherwise state that IME is untested. Do not claim that this browser scenario mutates live email or uses a UUID user model.

- [ ] **Step 3: Install/build and prepare one fresh server environment**

Run from the primary worktree:

```bash
npm ci
npm run build
npm --prefix client/tests/integration ci
export PLAYWRIGHT_BROWSERS_PATH=/tmp/wagtail-comment-mentions-playwright
npm --prefix client/tests/integration exec -- playwright install chromium
export WAGTAIL_UI_TEST_DB="$(mktemp --suffix=.sqlite3 /tmp/wagtail-comment-mentions-task13.XXXXXX)"
export TEST_PORT="$(uv run --extra testing python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
export TEST_ORIGIN="http://127.0.0.1:${TEST_PORT}"
export DJANGO_SETTINGS_MODULE=wagtail.test.settings_ui
printf 'export WAGTAIL_UI_TEST_DB=%s\nexport TEST_PORT=%s\nexport TEST_ORIGIN=%s\nexport PLAYWRIGHT_BROWSERS_PATH=%s\nexport DJANGO_SETTINGS_MODULE=%s\n' "$WAGTAIL_UI_TEST_DB" "$TEST_PORT" "$TEST_ORIGIN" "$PLAYWRIGHT_BROWSERS_PATH" "$DJANGO_SETTINGS_MODULE" > /tmp/comment-mentions-task13.env
uv run --extra testing python ./wagtail/test/manage.py migrate --noinput
uv run --extra testing python ./wagtail/test/manage.py createcachetable
DJANGO_SUPERUSER_EMAIL=admin@example.com DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_PASSWORD=changeme uv run --extra testing python ./wagtail/test/manage.py createsuperuser --noinput
uv run --extra testing python ./wagtail/test/manage.py runserver "127.0.0.1:${TEST_PORT}" --noreload
```

Expected: the server remains running in this terminal on the free recorded port and uses only the fresh temporary database.

- [ ] **Step 4: Run the Chromium/Axe scenario in a second terminal**

```bash
source /tmp/comment-mentions-task13.env
until curl -fsS "$TEST_ORIGIN/admin/login/" >/dev/null; do sleep 0.25; done
TEST_ORIGIN="$TEST_ORIGIN" PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" npm run test:integration -- --runInBand --runTestsByPath client/tests/integration/comment-mentions.test.js
```

Expected: PASS is valid on the first run because Tasks 8-12 are prerequisites. Do not manufacture a RED failure. Stop the server after the run and remove the temporary database when evidence collection is complete.

In the foreground server terminal, press Ctrl-C, then clean up exactly:

```bash
rm -f "$WAGTAIL_UI_TEST_DB" \
  "${WAGTAIL_UI_TEST_DB}-journal" \
  "${WAGTAIL_UI_TEST_DB}-wal" \
  "${WAGTAIL_UI_TEST_DB}-shm" \
  /tmp/comment-mentions-task13.env
```

- [ ] **Step 5: Fix only genuine browser discrepancies and rerun all affected gates**

Do not weaken expectations or add sleeps. Wait on visible state, a held/fulfilled response, form update, autosave event, navigation, fonts, or hydration. If production code changes, return to Task 12: add the focused unit regression, rerun Task 12's full unit/lint/type/build gate, and create a separate focused Task 12 defect commit before resuming Task 13. Task 13's commit remains limited to its two known files.

- [ ] **Step 6: Verify the integration files and commit the regression**

```bash
./node_modules/.bin/eslint --report-unused-disable-directives client/tests/integration/comment-mentions.test.js
./node_modules/.bin/prettier --check client/tests/integration/comment-mentions.test.js
uv run --extra testing python -m ruff format --check wagtail/test/settings_ui.py
uv run --extra testing python -m ruff check wagtail/test/settings_ui.py
```

Expected: all commands PASS; generated databases, browser binaries, and screenshots remain outside git.

```bash
git add client/tests/integration/comment-mentions.test.js wagtail/test/settings_ui.py
git commit -m "Test comment mentions in the browser"
```

Expected: this commit contains exactly `client/tests/integration/comment-mentions.test.js` and `wagtail/test/settings_ui.py`; any verified production fix was already committed separately in Step 5. No generated artifact or unrelated source is committed.

---

### Task 14: Current-Primary Verification and Provisional Reviewer Artifact

**Files:**
- Modify only for a verified defect: files owned by Tasks 2-13 and their focused tests
- Create outside git: `/tmp/wagtail-comment-mentions-pr/autocomplete-open.png`
- Create outside git: `/tmp/wagtail-comment-mentions-pr/after-redesign.png`
- Create outside git: `/tmp/wagtail-comment-mentions-pr/verification.json`
- Create outside git: `/tmp/wagtail-comment-mentions-pr/pr-body-provisional.md`
- Do not modify: `CHANGELOG.txt`, `docs/releases/8.0.md`, `CONTRIBUTORS.md`

**Interfaces:**
- Consumes: complete Tasks 2-13 and the exact current primary OID/version.
- Produces: a complete current-primary matrix plus a provisional, unsubmitted reviewer artifact.
- Current-alpha rule: an 8.0 alpha PASS is development evidence only. It does not satisfy Task 16 or authorize publication.

- [ ] **Step 1: Activate and record the direct/tox environments**

```bash
source .venv/bin/activate
export UV_CACHE_DIR=/tmp/wagtail-comment-mentions-uv-cache
mkdir -p "$UV_CACHE_DIR" /tmp/wagtail-comment-mentions-pr
python --version
python -c 'import wagtail; print(wagtail.__version__)'
uvx --python 3.13 --from 'tox>=4,<5' tox --version
```

Expected: record the activated direct Python deliberately, including 3.14 if that is the repository environment; tox is explicitly provisioned with Python 3.13 rather than selecting a host interpreter implicitly.

- [ ] **Step 2: Run the complete focused primary backend matrix**

```bash
BACKEND_TESTS=(
  wagtail.tests.test_comments
  wagtail.admin.tests.test_comment_mentions
  wagtail.admin.tests.test_comment_notifications
  wagtail.admin.tests.test_edit_handlers
  wagtail.admin.tests.pages.test_create_page
  wagtail.admin.tests.pages.test_edit_page
  wagtail.admin.tests.test_audit_log
  wagtail.tests.permission_policies.test_page_permission_policies
  wagtail.admin.tests.test_workflows.TestCommentMentionWorkflows
)

python runtests.py -- "${BACKEND_TESTS[@]}"
USE_EMAIL_USER_MODEL=yes python runtests.py -- "${BACKEND_TESTS[@]}"
uvx --python 3.13 --from 'tox>=4,<5' tox -e py313-dj52-sqlite-noelasticsearch-customuser-tz -- "${BACKEND_TESTS[@]}"
uvx --python 3.13 --from 'tox>=4,<5' tox -e py313-dj60-sqlite-noelasticsearch-emailuser-tz -- "${BACKEND_TESTS[@]}"
```

Expected: all four commands PASS. Record Wagtail, Django, Python, user model, and environment for each; UUID/custom-PK conclusions come from the email-user runs, not the default browser.

- [ ] **Step 3: Run complete frontend, formatting, build, migration, and diff gates**

```bash
npm run test:unit:coverage -- --runInBand client/src/components/CommentApp client/src/entrypoints/admin/comments.test.js
npm run lint:ts
npm run lint:js
npm run lint:css
npm run lint:format
npm run lint:project
npm run build
DJANGO_SETTINGS_MODULE=wagtail.test.settings python -m django makemigrations --check --dry-run
make lint-server
source /tmp/comment-mentions-bases.env
git diff --check "$OFFICIAL_MAIN"..HEAD
```

Expected: all commands PASS. Use the canonical whole-repository server lint; do not substitute selected Ruff paths as final server evidence.

- [ ] **Step 4: Rerun Task 13 with primary evidence output**

Use Task 13's fresh database, free port, explicit interpreter, `--noreload`, readiness, and cleanup contract with:

```bash
export COMMENT_MENTIONS_EVIDENCE_DIR=/tmp/wagtail-comment-mentions-pr
```

Expected: Chromium/Axe PASS with exact plain comment/reply values and hidden JSON before submit and after reload, rich-paste stripping, blocked formatting shortcuts, actual contenteditable ARIA/focus/listbox state, and stale-attribute cleanup. Validate screenshot dimensions and checksums.

- [ ] **Step 5: Run and record real native-input browser evidence**

On the exact primary head, manually run the same representative path in current Chromium and Firefox using a real installed IME. Record OS, browser versions, input method, entered text, caret result, pointer selection, multiline input, paste, emoji, reload, inline entity highlighting, and popup keyboard/accessibility results.

Expected: both native-IME/caret/pointer passes are recorded. If native IME is unavailable, Task 14 remains incomplete and its provisional text narrows the claim; Task 16 cannot make the final IME-safe claim. State explicitly that Axe is not an assistive-technology test, no AT test was run unless one actually was, and WebKit/Safari was not tested.

- [ ] **Step 6: Write and validate exact provisional metadata**

Write `/tmp/wagtail-comment-mentions-pr/verification.json` with full `OFFICIAL_MAIN`, primary HEAD, exact Wagtail version, Python/Django/tox/Ruff versions, 1024x768 viewport, OS, Chromium/Firefox versions, image checksums, commands/results, and which evidence is backend-only.

Expected: notification delivery/recipient merging is attributed to backend tests unless a second browser recipient was actually seeded. UUID is backend/frontend-unit only. No unrun browser/AT claim appears.

- [ ] **Step 7: Review primary history and draft, but do not publish, the PR body**

```bash
source /tmp/comment-mentions-bases.env
git diff --name-status "$OFFICIAL_MAIN"..HEAD
git diff --stat "$OFFICIAL_MAIN"..HEAD
git log --oneline "$OFFICIAL_MAIN"..HEAD
git status --short --branch
```

Expected: only mention-related source/tests/planning evidence; no generated output, caches, release files, unrelated commits, or uncommitted changes.

Write `/tmp/wagtail-comment-mentions-pr/pr-body-provisional.md` from `.github/PULL_REQUEST_TEMPLATE.md`. Include literal current results and these exact markers:

```text
PENDING TASK 15 7.4 EVIDENCE
PENDING TASK 16 8.0 BETA-OR-LATER EVIDENCE
PENDING SCREENSHOT UPLOAD
```

Include `Fixes #`, `### Description`, `### AI usage`, rationale/review areas, exact current OID/version, negative browser/AT disclosures, suggested core-committer release/contributor copy, and:

```text
> This pull request includes code written with the assistance of AI.
> The code has **not yet been reviewed** by a human.
```

Expected: if VERSION is alpha, every result is clearly provisional. Do not edit the live PR, upload/push anything, or imply Task 15/16 has passed.

- [ ] **Step 8: Commit only verified defects, if any**

If verification changed production/test code, run the affected focused gate plus Steps 2-5 again, stage only the named defect files/tests, and commit a focused fix. If no defect was found, create no Task 14 commit. Temporary evidence remains untracked.

---

### Task 15: Retained Wagtail 7.4 Backport and Provisional Compatibility Report

**Files:**
- Create as a sibling worktree: `/home/jt/dev/made-with-future/wagtail-compat-comment-mentions-7.4`
- Create as a local-only branch: `compat/comment-mentions-7.4`
- Modify on compatibility only: `wagtail/admin/urls/pages.py`
- Modify on compatibility only when the refreshed graph requires it: the dynamically discovered comment-mentions migration filename/dependency
- Create on primary: `docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md`
- Do not create/push a remote compatibility branch

**Interfaces:**
- Consumes: the exact Task 14 primary runtime head, refreshed official `main` and `stable/7.4.x`, and Tasks 9-13 runtime/tests.
- Produces: one retained initial compatibility commit, a frozen primary runtime patch/SHA, adaptation-aware equivalence evidence, a complete 7.4 matrix, and a provisional primary report for Task 16.

Preserve these meanings:

```text
PRIMARY_RUNTIME_HEAD = exact primary source head tested/checksummed by Tasks 14-15
PRIMARY_REPORT_HEAD  = later primary commit that changes only the compatibility report
OFFICIAL_STABLE      = exact refreshed stable/7.4.x base
COMPAT_RUNTIME_HEAD  = exact tested compatibility head
PATCH                = frozen PRIMARY_BASE..PRIMARY_RUNTIME_HEAD runtime/test patch
PATCH_SHA256         = identity of PATCH only, not proof of cross-branch equivalence
```

Task 15 browser scope is default opaque-string IDs. UUID/custom-PK compatibility is proved by backend/email-user and frontend wire tests; do not claim a UUID browser run. Firefox evidence remains primary-only.

- [ ] **Step 1: Refresh both official refs, freeze primary provenance, and enter the retained worktree safely**

Detect and validate frozen state **before** fetching, deriving a head, or exporting anything:

```bash
TASK15_BASES_ENV=/tmp/comment-mentions-bases.env
TASK15_COMPAT_ENV=/tmp/comment-mentions-compat.env
TASK15_RESUME=fresh
if test -s "$TASK15_COMPAT_ENV"; then
  test -s "$TASK15_BASES_ENV"
  source "$TASK15_BASES_ENV"
  source "$TASK15_COMPAT_ENV"
  test -n "$PRIMARY_WORKTREE"
  test -n "$COMPAT"
  test -n "$OFFICIAL_MAIN"
  test -n "$OFFICIAL_STABLE"
  test -n "$PRIMARY_BASE"
  test -n "$REDESIGN_BASE"
  test -n "$PRIMARY_VERSION"
  test -n "$PRIMARY_RUNTIME_HEAD"
  test -n "$COMPAT_RUNTIME_HEAD"
  test -n "$PATCH"
  test -n "$PATCH_SHA256"
  test "$PRIMARY_HEAD" = "$PRIMARY_RUNTIME_HEAD"
  test "$COMPAT_HEAD" = "$COMPAT_RUNTIME_HEAD"
  test "$(git -C "$PRIMARY_WORKTREE" rev-parse --show-toplevel)" = "$PRIMARY_WORKTREE"
  test "$(git -C "$COMPAT" rev-parse --show-toplevel)" = "$COMPAT"
  test "$(git -C "$COMPAT" branch --show-current)" = compat/comment-mentions-7.4
  test "$(git -C "$PRIMARY_WORKTREE" rev-parse "$REDESIGN_BASE^{commit}")" = "$REDESIGN_BASE"
  test "$(git -C "$PRIMARY_WORKTREE" merge-base "$PRIMARY_BASE" "$PRIMARY_RUNTIME_HEAD")" = "$PRIMARY_BASE"
  test -z "$(git -C "$COMPAT" status --short)"
  test -z "$(git -C "$PRIMARY_WORKTREE" status --short)"
  test -s "$PATCH"
  test "$(sha256sum "$PATCH" | cut -d' ' -f1)" = "$PATCH_SHA256"
  CURRENT_PRIMARY_HEAD="$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)"
  CURRENT_COMPAT_HEAD="$(git -C "$COMPAT" rev-parse HEAD)"

  if test "$COMPAT_RUNTIME_HEAD" = "$OFFICIAL_STABLE"; then
    test -z "${PRIMARY_REPORT_HEAD:-}"
    if test "$CURRENT_COMPAT_HEAD" = "$OFFICIAL_STABLE"; then
      COMPAT_RESUME=apply
      TASK15_RESUME=apply
    else
      test "$(git -C "$COMPAT" rev-list --count "$OFFICIAL_STABLE".."$CURRENT_COMPAT_HEAD")" = 1
      test "$(git -C "$COMPAT" rev-parse "$CURRENT_COMPAT_HEAD^")" = "$OFFICIAL_STABLE"
      COMPAT_RUNTIME_HEAD="$CURRENT_COMPAT_HEAD"
      COMPAT_HEAD="$CURRENT_COMPAT_HEAD"
      COMPAT_RESUME=verify
      TASK15_RESUME=verify
    fi
  else
    test "$CURRENT_COMPAT_HEAD" = "$COMPAT_RUNTIME_HEAD"
    test "$(git -C "$COMPAT" rev-list --count "$OFFICIAL_STABLE"..HEAD)" = 1
    test "$(git -C "$COMPAT" rev-parse HEAD^)" = "$OFFICIAL_STABLE"
    COMPAT_RESUME=verify
    TASK15_RESUME=verify
  fi

  if test -n "${PRIMARY_REPORT_HEAD:-}"; then
    test -n "$PRIMARY_HANDOFF_HEAD"
    test "$PRIMARY_HANDOFF_HEAD" = "$PRIMARY_REPORT_HEAD"
    test "$CURRENT_PRIMARY_HEAD" = "$PRIMARY_REPORT_HEAD"
    test "$(git -C "$PRIMARY_WORKTREE" rev-parse "$PRIMARY_REPORT_HEAD^")" = "$PRIMARY_RUNTIME_HEAD"
    test "$(git -C "$PRIMARY_WORKTREE" diff --name-only "$PRIMARY_RUNTIME_HEAD" "$PRIMARY_REPORT_HEAD")" = docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md
    TASK15_RESUME=completed
  elif test "$CURRENT_PRIMARY_HEAD" = "$PRIMARY_RUNTIME_HEAD"; then
    :
  else
    test "$COMPAT_RUNTIME_HEAD" != "$OFFICIAL_STABLE"
    test "$(git -C "$PRIMARY_WORKTREE" rev-parse "$CURRENT_PRIMARY_HEAD^")" = "$PRIMARY_RUNTIME_HEAD"
    test "$(git -C "$PRIMARY_WORKTREE" diff --name-only "$PRIMARY_RUNTIME_HEAD" "$CURRENT_PRIMARY_HEAD")" = docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md
    PRIMARY_REPORT_HEAD="$CURRENT_PRIMARY_HEAD"
    PRIMARY_HANDOFF_HEAD="$CURRENT_PRIMARY_HEAD"
    TASK15_RESUME=report-handoff
  fi
  TASK15_FROZEN=1
else
  TASK15_FROZEN=0
fi
```

Expected for frozen resume: use the recorded canonical runtime/report heads and immutable patch; never classify the current report HEAD as runtime and never regenerate the patch.

For `TASK15_FROZEN=0`, run the fresh-entry path with network/filesystem approval:

```bash
source "$TASK15_BASES_ENV"
REMOTE=https://github.com/wagtail/wagtail.git
COMPAT=/home/jt/dev/made-with-future/wagtail-compat-comment-mentions-7.4
git -C "$PRIMARY_WORKTREE" fetch --no-tags "$REMOTE" +refs/heads/main:refs/remotes/upstream/main +refs/heads/stable/7.4.x:refs/remotes/upstream/stable/7.4.x
OFFICIAL_MAIN="$(git -C "$PRIMARY_WORKTREE" rev-parse refs/remotes/upstream/main)"
OFFICIAL_STABLE="$(git -C "$PRIMARY_WORKTREE" rev-parse refs/remotes/upstream/stable/7.4.x)"
PRIMARY_BASE="$(git -C "$PRIMARY_WORKTREE" merge-base "$OFFICIAL_MAIN" HEAD)"
PRIMARY_RUNTIME_HEAD="$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)"
PRIMARY_VERSION="$(PYTHONPATH="$PRIMARY_WORKTREE" "$PRIMARY_WORKTREE/.venv/bin/python" -c 'import wagtail; print(wagtail.__version__)')"
test "$PRIMARY_BASE" = "$OFFICIAL_MAIN"
test -z "$(git -C "$PRIMARY_WORKTREE" status --short)"
if test -e "$COMPAT"; then
  test "$(git -C "$COMPAT" branch --show-current)" = compat/comment-mentions-7.4
  test -z "$(git -C "$COMPAT" status --short)"
  COMPAT_EXISTING_HEAD="$(git -C "$COMPAT" rev-parse HEAD)"
  test "$COMPAT_EXISTING_HEAD" = "$OFFICIAL_STABLE"
else
  test -z "$(git -C "$PRIMARY_WORKTREE" branch --list compat/comment-mentions-7.4)"
  git -C "$PRIMARY_WORKTREE" worktree add "$COMPAT" -b compat/comment-mentions-7.4 "$OFFICIAL_STABLE"
fi
COMPAT_EXISTING_HEAD="$(git -C "$COMPAT" rev-parse HEAD)"
COMPAT_RUNTIME_HEAD="$COMPAT_EXISTING_HEAD"
COMPAT_RESUME=apply
```

Expected for fresh entry: primary remains exactly based on freshly fetched main and compatibility is exact stable. An existing retained commit without frozen env state hard-stops. Never reset, recreate, or reapply to recover it.

- [ ] **Step 2: Export and checksum the primary runtime patch exactly once**

For fresh entry only:

```bash
test "$TASK15_FROZEN" = 0
PATCH="/tmp/comment-mentions-${PRIMARY_RUNTIME_HEAD}.patch"
git -C "$PRIMARY_WORKTREE" diff --binary --full-index --no-renames --output="$PATCH" "$PRIMARY_BASE" "$PRIMARY_RUNTIME_HEAD" -- . ':(exclude)docs/superpowers/**' ':(exclude)CHANGELOG.txt' ':(exclude)CONTRIBUTORS.md' ':(exclude)docs/releases/**'
test -s "$PATCH"
PATCH_SHA256="$(sha256sum "$PATCH" | cut -d' ' -f1)"
test -n "$PATCH_SHA256"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$PRIMARY_RUNTIME_HEAD"
```

Write `/tmp/comment-mentions-bases.env` and `/tmp/comment-mentions-compat.env` atomically with complete literal state. Validate every value and both worktrees immediately before replacement:

```bash
test -n "$PRIMARY_WORKTREE"
test -n "$OFFICIAL_MAIN"
test -n "$OFFICIAL_STABLE"
test -n "$PRIMARY_BASE"
test -n "$REDESIGN_BASE"
test -n "$PRIMARY_VERSION"
test -n "$PRIMARY_RUNTIME_HEAD"
test -n "$COMPAT"
test -n "$COMPAT_EXISTING_HEAD"
test -n "$COMPAT_RUNTIME_HEAD"
test -n "$PATCH"
test -n "$PATCH_SHA256"
test "$PRIMARY_BASE" = "$OFFICIAL_MAIN"
test "$COMPAT_EXISTING_HEAD" = "$OFFICIAL_STABLE"
test "$COMPAT_RUNTIME_HEAD" = "$COMPAT_EXISTING_HEAD"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse --show-toplevel)" = "$PRIMARY_WORKTREE"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$PRIMARY_RUNTIME_HEAD"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse "$REDESIGN_BASE^{commit}")" = "$REDESIGN_BASE"
test "$(git -C "$PRIMARY_WORKTREE" merge-base "$PRIMARY_BASE" "$PRIMARY_RUNTIME_HEAD")" = "$PRIMARY_BASE"
test -z "$(git -C "$PRIMARY_WORKTREE" status --short)"
test "$(git -C "$COMPAT" rev-parse --show-toplevel)" = "$COMPAT"
test "$(git -C "$COMPAT" branch --show-current)" = compat/comment-mentions-7.4
test "$(git -C "$COMPAT" rev-parse HEAD)" = "$COMPAT_RUNTIME_HEAD"
test -z "$(git -C "$COMPAT" status --short)"
test -s "$PATCH"
test "$(sha256sum "$PATCH" | cut -d' ' -f1)" = "$PATCH_SHA256"

BASES_NEXT="$(mktemp /tmp/comment-mentions-bases.XXXXXX)"
printf 'export PRIMARY_WORKTREE=%q\nexport OFFICIAL_MAIN=%q\nexport OFFICIAL_STABLE=%q\nexport PRIMARY_BASE=%q\nexport REDESIGN_BASE=%q\nexport PRIMARY_VERSION=%q\n' \
  "$PRIMARY_WORKTREE" "$OFFICIAL_MAIN" "$OFFICIAL_STABLE" "$PRIMARY_BASE" "$REDESIGN_BASE" "$PRIMARY_VERSION" > "$BASES_NEXT"
test -s "$BASES_NEXT"
mv "$BASES_NEXT" "$TASK15_BASES_ENV"

COMPAT_NEXT="$(mktemp /tmp/comment-mentions-compat.XXXXXX)"
printf 'export COMPAT=%q\nexport PRIMARY_HEAD=%q\nexport PRIMARY_RUNTIME_HEAD=%q\nexport COMPAT_HEAD=%q\nexport COMPAT_RUNTIME_HEAD=%q\nexport PATCH=%q\nexport PATCH_SHA256=%q\n' \
  "$COMPAT" "$PRIMARY_RUNTIME_HEAD" "$PRIMARY_RUNTIME_HEAD" "$COMPAT_RUNTIME_HEAD" "$COMPAT_RUNTIME_HEAD" "$PATCH" "$PATCH_SHA256" > "$COMPAT_NEXT"
test -s "$COMPAT_NEXT"
mv "$COMPAT_NEXT" "$TASK15_COMPAT_ENV"
```

For `TASK15_FROZEN=1`, skip export and revalidate the sourced patch/SHA. Never regenerate the patch after apply/backport work begins.

- [ ] **Step 3: Provision tox-owned tools and inspect the stable migration leaf**

```bash
TOX_ENV=py313-dj52-sqlite-noelasticsearch-customuser-tz
uvx --python 3.13 --from 'tox>=4,<5' tox -c "$COMPAT/tox.ini" -e "$TOX_ENV" --notest
TOX_PY="$COMPAT/.tox/$TOX_ENV/bin/python"
TOX_RUFF="$COMPAT/.tox/$TOX_ENV/bin/ruff"
test -x "$TOX_PY"
test -x "$TOX_RUFF"
"$TOX_PY" --version
"$TOX_RUFF" --version
DJANGO_SETTINGS_MODULE=wagtail.test.settings "$TOX_PY" -c 'import django; django.setup(); from django.db import connections; from django.db.migrations.loader import MigrationLoader; print(MigrationLoader(connections["default"], ignore_no_migrations=True).graph.leaf_nodes("wagtailcore"))'
```

Expected: record the exact one stable `wagtailcore` leaf plus Python, Ruff, Wagtail, and Django versions. Stable has no authoritative `uv.lock`; host bare Python/Ruff is invalid evidence.

Discover the one primary changed migration dynamically:

```bash
PRIMARY_MIGRATION="$(git -C "$PRIMARY_WORKTREE" diff --name-only "$PRIMARY_BASE" "$PRIMARY_RUNTIME_HEAD" -- 'wagtail/migrations/*_comment_mentions.py')"
test -n "$PRIMARY_MIGRATION"
test "$(printf '%s\n' "$PRIMARY_MIGRATION" | wc -l)" = 1
```

Decide from the recorded graph whether its filename/dependency applies unchanged. If not, record the one adapted compatibility path and exclude the primary migration during apply.

- [ ] **Step 4: Apply with identical fail-fast exclusions or validate the retained commit**

For `COMPAT_RESUME=apply`, use one unchanged exclusion array for check and real indexed 3-way apply:

```bash
APPLY_EXCLUDES=(
  --exclude=wagtail/admin/viewsets/pages.py
  --exclude=wagtail/admin/urls/pages.py
)
# Append exactly this only when the recorded stable leaf requires adaptation:
# APPLY_EXCLUDES+=(--exclude="$PRIMARY_MIGRATION")

git -C "$COMPAT" apply --check --3way --index "${APPLY_EXCLUDES[@]}" "$PATCH"
git -C "$COMPAT" apply --3way --index "${APPLY_EXCLUDES[@]}" "$PATCH"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$PRIMARY_RUNTIME_HEAD"
test "$(sha256sum "$PATCH" | cut -d' ' -f1)" = "$PATCH_SHA256"
```

There is no `|| true`, rejected-hunk resolution, reset, or full-patch reapplication. Register the same shared suggestion views directly in 7.4's `wagtail/admin/urls/pages.py`. If migration adaptation is required, use `apply_patch` to create only the new filename/dependency; operation content remains identical.

For `COMPAT_RESUME=verify`, skip every apply/edit/commit action and validate the retained commit, patch SHA, route seam, migration seam, and ancestry before proceeding.

- [ ] **Step 5: Commit one initial retained compatibility commit**

For a new apply only:

```bash
git -C "$COMPAT" diff --check
git -C "$COMPAT" status --short
git -C "$COMPAT" add -A -- wagtail client
git -C "$COMPAT" commit -m "Backport comment mentions to Wagtail 7.4"
COMPAT_RUNTIME_HEAD="$(git -C "$COMPAT" rev-parse HEAD)"
test "$(git -C "$COMPAT" rev-parse HEAD^)" = "$OFFICIAL_STABLE"
```

Expected: one focused local commit. Frontend source/tests are unchanged from primary; intentional backend differences are limited to route registration and a recorded migration filename/dependency or test-location seam.

Unless `TASK15_RESUME` is `completed` or `report-handoff`, atomically replace `/tmp/comment-mentions-compat.env` with complete committed-compatibility state. Those two states already carry the persisted report/handoff identities and must not be downgraded. On a verified compatibility-only resume, use the existing exact commit as `COMPAT_RUNTIME_HEAD` and do not create another:

```bash
if test "$TASK15_RESUME" != completed && test "$TASK15_RESUME" != report-handoff; then
  test -n "$COMPAT"
  test -n "$PRIMARY_RUNTIME_HEAD"
  test -n "$COMPAT_RUNTIME_HEAD"
  test -n "$OFFICIAL_STABLE"
  test -n "$PATCH"
  test -n "$PATCH_SHA256"
  test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$PRIMARY_RUNTIME_HEAD"
  test -z "$(git -C "$PRIMARY_WORKTREE" status --short)"
  test "$(git -C "$COMPAT" rev-parse --show-toplevel)" = "$COMPAT"
  test "$(git -C "$COMPAT" branch --show-current)" = compat/comment-mentions-7.4
  test "$(git -C "$COMPAT" rev-parse HEAD)" = "$COMPAT_RUNTIME_HEAD"
  test "$(git -C "$COMPAT" rev-list --count "$OFFICIAL_STABLE"..HEAD)" = 1
  test "$(git -C "$COMPAT" rev-parse HEAD^)" = "$OFFICIAL_STABLE"
  test -z "$(git -C "$COMPAT" status --short)"
  test -s "$PATCH"
  test "$(sha256sum "$PATCH" | cut -d' ' -f1)" = "$PATCH_SHA256"

  COMPAT_NEXT="$(mktemp /tmp/comment-mentions-compat.XXXXXX)"
  printf 'export COMPAT=%q\nexport PRIMARY_HEAD=%q\nexport PRIMARY_RUNTIME_HEAD=%q\nexport COMPAT_HEAD=%q\nexport COMPAT_RUNTIME_HEAD=%q\nexport PATCH=%q\nexport PATCH_SHA256=%q\n' \
    "$COMPAT" "$PRIMARY_RUNTIME_HEAD" "$PRIMARY_RUNTIME_HEAD" "$COMPAT_RUNTIME_HEAD" "$COMPAT_RUNTIME_HEAD" "$PATCH" "$PATCH_SHA256" > "$COMPAT_NEXT"
  test -s "$COMPAT_NEXT"
  mv "$COMPAT_NEXT" "$TASK15_COMPAT_ENV"
fi
```

- [ ] **Step 6: Run the complete 7.4 backend/default/UUID matrix**

```bash
BACKEND_TESTS=(
  wagtail.tests.test_comments
  wagtail.admin.tests.test_comment_mentions
  wagtail.admin.tests.test_comment_notifications
  wagtail.admin.tests.test_edit_handlers
  wagtail.admin.tests.pages.test_create_page
  wagtail.admin.tests.pages.test_edit_page
  wagtail.admin.tests.test_audit_log
  wagtail.tests.permission_policies.test_page_permission_policies
  wagtail.admin.tests.test_workflows.TestCommentMentionWorkflows
)

uvx --python 3.13 --from 'tox>=4,<5' tox -c "$COMPAT/tox.ini" -e py313-dj52-sqlite-noelasticsearch-customuser-tz -- "${BACKEND_TESTS[@]}"
uvx --python 3.13 --from 'tox>=4,<5' tox -c "$COMPAT/tox.ini" -e py313-dj60-sqlite-noelasticsearch-customuser-tz -- "${BACKEND_TESTS[@]}"
uvx --python 3.13 --from 'tox>=4,<5' tox -c "$COMPAT/tox.ini" -e py313-dj60-sqlite-noelasticsearch-emailuser-tz -- "${BACKEND_TESTS[@]}"
```

Expected: all environments PASS. Record exact Wagtail/Django/Python/user-model versions per environment; the email-user run is the UUID/custom-PK evidence.

- [ ] **Step 7: Run complete compatibility frontend, build, migration, and lint gates**

```bash
cd "$COMPAT"
npm ci
npm run test:unit:coverage -- --runInBand client/src/components/CommentApp client/src/entrypoints/admin/comments.test.js
npm run lint:ts
npm run lint:js
npm run lint:css
npm run lint:format
npm run lint:project
npm run build
DJANGO_SETTINGS_MODULE=wagtail.test.settings "$TOX_PY" -m django makemigrations --check --dry-run
"$TOX_RUFF" format --check wagtail/admin wagtail/models/pages.py wagtail/migrations
"$TOX_RUFF" check wagtail/admin wagtail/models/pages.py wagtail/migrations
git diff --check "$OFFICIAL_STABLE"..HEAD
```

Expected: all commands PASS using tox-owned Python/Ruff and the dynamically adapted migration path; no host bare tool result is reported.

- [ ] **Step 8: Rerun Task 13 on one fresh 7.4 server**

In the compatibility worktree:

```bash
export PLAYWRIGHT_BROWSERS_PATH=/tmp/wagtail-comment-mentions-playwright-7.4
npm --prefix client/tests/integration ci
npm --prefix client/tests/integration exec -- playwright install chromium
export WAGTAIL_UI_TEST_DB="$(mktemp --suffix=.sqlite3 /tmp/wagtail-comment-mentions-task15.XXXXXX)"
export TEST_PORT="$("$TOX_PY" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
export TEST_ORIGIN="http://127.0.0.1:${TEST_PORT}"
export COMMENT_MENTIONS_EVIDENCE_DIR=/tmp/wagtail-comment-mentions-compat/7.4
printf 'export COMPAT=%s\nexport WAGTAIL_UI_TEST_DB=%s\nexport TEST_PORT=%s\nexport TEST_ORIGIN=%s\nexport PLAYWRIGHT_BROWSERS_PATH=%s\nexport COMMENT_MENTIONS_EVIDENCE_DIR=%s\n' "$COMPAT" "$WAGTAIL_UI_TEST_DB" "$TEST_PORT" "$TEST_ORIGIN" "$PLAYWRIGHT_BROWSERS_PATH" "$COMMENT_MENTIONS_EVIDENCE_DIR" > /tmp/comment-mentions-task15-browser.env
DJANGO_SETTINGS_MODULE=wagtail.test.settings_ui "$TOX_PY" ./wagtail/test/manage.py migrate --noinput
DJANGO_SETTINGS_MODULE=wagtail.test.settings_ui "$TOX_PY" ./wagtail/test/manage.py createcachetable
DJANGO_SETTINGS_MODULE=wagtail.test.settings_ui DJANGO_SUPERUSER_EMAIL=admin@example.com DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_PASSWORD=changeme "$TOX_PY" ./wagtail/test/manage.py createsuperuser --noinput
DJANGO_SETTINGS_MODULE=wagtail.test.settings_ui "$TOX_PY" ./wagtail/test/manage.py runserver "127.0.0.1:${TEST_PORT}" --noreload
```

In another terminal:

```bash
source /tmp/comment-mentions-task15-browser.env
cd "$COMPAT"
until curl -fsS "$TEST_ORIGIN/admin/login/" >/dev/null; do sleep 0.25; done
COMMENT_MENTIONS_EVIDENCE_DIR="$COMMENT_MENTIONS_EVIDENCE_DIR" TEST_ORIGIN="$TEST_ORIGIN" PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" npm run test:integration -- --runInBand --runTestsByPath client/tests/integration/comment-mentions.test.js
```

Expected: Chromium/Axe PASS through both 7.4 create/edit routing seams. The browser proves default `user_id` is an opaque string; UUID remains backend-only. Stop the server and remove the temporary DB afterward. Do not claim a 7.4 Firefox run.

- [ ] **Step 9: Prove adaptation-aware source, migration, route, and history equivalence**

Run:

```bash
source /tmp/comment-mentions-bases.env
source /tmp/comment-mentions-compat.env
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$PRIMARY_RUNTIME_HEAD"
test "$(sha256sum "$PATCH" | cut -d' ' -f1)" = "$PATCH_SHA256"
git diff --no-index --exit-code "$PRIMARY_WORKTREE/client/src/components/CommentApp" "$COMPAT/client/src/components/CommentApp"
git diff --no-index --exit-code "$PRIMARY_WORKTREE/client/tests/integration/comment-mentions.test.js" "$COMPAT/client/tests/integration/comment-mentions.test.js"
git -C "$PRIMARY_WORKTREE" range-diff --no-color "$PRIMARY_BASE..$PRIMARY_RUNTIME_HEAD" "$OFFICIAL_STABLE..$COMPAT_RUNTIME_HEAD"
git -C "$PRIMARY_WORKTREE" diff --name-status "$PRIMARY_BASE" "$PRIMARY_RUNTIME_HEAD"
git -C "$COMPAT" diff --name-status "$OFFICIAL_STABLE" "$COMPAT_RUNTIME_HEAD"
git -C "$PRIMARY_WORKTREE" diff --stat "$PRIMARY_BASE" "$PRIMARY_RUNTIME_HEAD"
git -C "$COMPAT" diff --stat "$OFFICIAL_STABLE" "$COMPAT_RUNTIME_HEAD"
git -C "$PRIMARY_WORKTREE" diff --check "$PRIMARY_BASE" "$PRIMARY_RUNTIME_HEAD"
git -C "$COMPAT" diff --check "$OFFICIAL_STABLE" "$COMPAT_RUNTIME_HEAD"
```

Generate and compare normalized shared patch IDs with only the declared primary-only/route/migration seams excluded:

```bash
EQUIV=/tmp/wagtail-comment-mentions-compat/equivalence
mkdir -p "$EQUIV"
COMPAT_MIGRATION="$(git -C "$COMPAT" diff --name-only "$OFFICIAL_STABLE" "$COMPAT_RUNTIME_HEAD" -- 'wagtail/migrations/*_comment_mentions.py')"
test -n "$COMPAT_MIGRATION"
PRIMARY_PATHS=(. ':(exclude)docs/superpowers/**' ':(exclude)CHANGELOG.txt' ':(exclude)CONTRIBUTORS.md' ':(exclude)docs/releases/**' ':(exclude)wagtail/admin/viewsets/pages.py' ':(exclude)wagtail/admin/urls/pages.py' ":(exclude)$PRIMARY_MIGRATION")
COMPAT_PATHS=(. ':(exclude)docs/superpowers/**' ':(exclude)CHANGELOG.txt' ':(exclude)CONTRIBUTORS.md' ':(exclude)docs/releases/**' ':(exclude)wagtail/admin/viewsets/pages.py' ':(exclude)wagtail/admin/urls/pages.py' ":(exclude)$COMPAT_MIGRATION")
git -C "$PRIMARY_WORKTREE" diff --binary --full-index --no-renames "$PRIMARY_BASE" "$PRIMARY_RUNTIME_HEAD" -- "${PRIMARY_PATHS[@]}" > "$EQUIV/primary-shared.patch"
git -C "$COMPAT" diff --binary --full-index --no-renames "$OFFICIAL_STABLE" "$COMPAT_RUNTIME_HEAD" -- "${COMPAT_PATHS[@]}" > "$EQUIV/compat-shared.patch"
PRIMARY_SHARED_PATCH_ID="$(git patch-id --stable < "$EQUIV/primary-shared.patch" | cut -d' ' -f1)"
COMPAT_SHARED_PATCH_ID="$(git patch-id --stable < "$EQUIV/compat-shared.patch" | cut -d' ' -f1)"
test -n "$PRIMARY_SHARED_PATCH_ID"
test "$PRIMARY_SHARED_PATCH_ID" = "$COMPAT_SHARED_PATCH_ID"
```

Expected: one nonempty identical stable patch ID; differences outside the declared seams are a primary compatibility defect.

Compare migration operations while deliberately omitting only module filename and `Migration.dependencies`:

```bash
cat > /tmp/comment-mentions-migration-ops.py <<'PY'
import importlib.util
import pprint
import sys

path = sys.argv[1]
spec = importlib.util.spec_from_file_location("comment_mentions_migration", path)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
pprint.pp([operation.deconstruct() for operation in module.Migration.operations], sort_dicts=True)
PY
PRIMARY_PY="$PRIMARY_WORKTREE/.venv/bin/python"
(cd "$PRIMARY_WORKTREE" && DJANGO_SETTINGS_MODULE=wagtail.test.settings "$PRIMARY_PY" /tmp/comment-mentions-migration-ops.py "$PRIMARY_WORKTREE/$PRIMARY_MIGRATION") > "$EQUIV/primary-migration-operations.txt"
(cd "$COMPAT" && DJANGO_SETTINGS_MODULE=wagtail.test.settings "$TOX_PY" /tmp/comment-mentions-migration-ops.py "$COMPAT/$COMPAT_MIGRATION") > "$EQUIV/compat-migration-operations.txt"
cmp "$EQUIV/primary-migration-operations.txt" "$EQUIV/compat-migration-operations.txt"
```

Expected: `cmp` exits 0; filename/dependency may differ, but every deconstructed schema/data operation is identical.

Compare literal route pattern/name/view triples:

```bash
cat > /tmp/comment-mentions-route-triples.py <<'PY'
import json
import os

import django
from django.urls import URLPattern, URLResolver, get_resolver

django.setup()

def walk(patterns, prefix=""):
    for entry in patterns:
        pattern = f"{prefix}{entry.pattern}"
        if isinstance(entry, URLResolver):
            yield from walk(entry.url_patterns, pattern)
        elif isinstance(entry, URLPattern) and entry.name and "mention" in entry.name:
            callback = entry.callback
            yield (pattern, entry.name, f"{callback.__module__}.{callback.__qualname__}")

for triple in sorted(walk(get_resolver().url_patterns)):
    print(json.dumps(triple, separators=(",", ":")))
PY
(cd "$PRIMARY_WORKTREE" && DJANGO_SETTINGS_MODULE=wagtail.test.settings_ui "$PRIMARY_PY" /tmp/comment-mentions-route-triples.py) > "$EQUIV/primary-routes.jsonl"
(cd "$COMPAT" && DJANGO_SETTINGS_MODULE=wagtail.test.settings_ui "$TOX_PY" /tmp/comment-mentions-route-triples.py) > "$EQUIV/compat-routes.jsonl"
test "$(wc -l < "$EQUIV/primary-routes.jsonl")" = 2
test "$(wc -l < "$EQUIV/compat-routes.jsonl")" = 2
cmp "$EQUIV/primary-routes.jsonl" "$EQUIV/compat-routes.jsonl"
```

Expected: exactly two byte-identical suggestion route triples.

Write the literal adaptation table from the validated paths/leaf decisions:

```bash
ADAPTATIONS="$EQUIV/adaptations.md"
printf '| Area | Primary | Wagtail 7.4 | Reason |\n|---|---|---|---|\n| Suggestion routes | wagtail/admin/viewsets/pages.py | wagtail/admin/urls/pages.py | Declared 8.0 viewset versus 7.4 direct-URL seam |\n| Migration | %s | %s | Filename/dependency only; operations compare byte-identical |\n' "$PRIMARY_MIGRATION" "$COMPAT_MIGRATION" > "$ADAPTATIONS"
test -s "$ADAPTATIONS"
test "$(rg -c '^\| (Suggestion routes|Migration) \|' "$ADAPTATIONS")" = 2
```

Expected: exactly the two literal declared adaptations. Any additional source/test difference fails the gate and must be corrected on primary or explicitly approved before the table/report changes. `range-diff` remains supplementary.

- [ ] **Step 10: Write and commit the provisional compatibility report on primary**

All fresh and resume paths use the same report identity:

```bash
REPORT=docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md
```

For `TASK15_RESUME=completed`, skip every write/commit below. Validate the existing report is the only path between `PRIMARY_RUNTIME_HEAD` and `PRIMARY_REPORT_HEAD`, contains the recorded frozen heads/SHA/results, and proceed to Step 11.

For `TASK15_RESUME=report-handoff`, skip report creation and commit, validate that the current exact `PRIMARY_REPORT_HEAD` has parent `PRIMARY_RUNTIME_HEAD` and changes only the report path, then continue at the atomic report/handoff writer below.

For fresh/partial/verification runs without `PRIMARY_REPORT_HEAD`, continue through report creation and commit:

Create the report directory if this is the first compatibility report:

```bash
mkdir -p "$PRIMARY_WORKTREE/docs/superpowers/compatibility"
```

Create `docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md` with literal values/results under:

```markdown
# Comment mentions: Wagtail 7.4 compatibility

## Recorded revisions
## Tested Wagtail versions
## Runtime patch SHA-256
## Commit and file comparison
## Intentional adaptations
## Backend matrix
## Frontend and production build
## Chromium and Axe
## Firefox manual verification
## Migration and diff checks
## Conclusion
```

Record `PRIMARY_RUNTIME_HEAD`, `COMPAT_RUNTIME_HEAD`, both bases, exact versions, patch SHA, tools, commands/results, source/migration/route comparisons, and local-retention proof. If primary VERSION is alpha, label primary rows/conclusion provisional and state Task 16 must replace them; do not fabricate beta values or leave placeholders. Firefox is primary-only evidence.

```bash
git -C "$PRIMARY_WORKTREE" add "$REPORT"
test "$(git -C "$PRIMARY_WORKTREE" diff --cached --name-only)" = "$REPORT"
git -C "$PRIMARY_WORKTREE" commit -m "Document Wagtail 7.4 mention compatibility"
PRIMARY_REPORT_HEAD="$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)"
test "$(git -C "$PRIMARY_WORKTREE" diff --name-only "$PRIMARY_RUNTIME_HEAD" "$PRIMARY_REPORT_HEAD")" = "$REPORT"
```

Freeze the report/handoff state by atomically replacing `/tmp/comment-mentions-compat.env` with every value later sourced. `PRIMARY_HEAD` remains the tested runtime head; the report and handoff aliases identify only the later report commit:

```bash
PRIMARY_HANDOFF_HEAD="$PRIMARY_REPORT_HEAD"
test -n "$COMPAT"
test -n "$PRIMARY_RUNTIME_HEAD"
test -n "$PRIMARY_REPORT_HEAD"
test -n "$PRIMARY_HANDOFF_HEAD"
test -n "$COMPAT_RUNTIME_HEAD"
test -n "$OFFICIAL_STABLE"
test -n "$PATCH"
test -n "$PATCH_SHA256"
test "$PRIMARY_HANDOFF_HEAD" = "$PRIMARY_REPORT_HEAD"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$PRIMARY_REPORT_HEAD"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse "$PRIMARY_REPORT_HEAD^")" = "$PRIMARY_RUNTIME_HEAD"
test "$(git -C "$PRIMARY_WORKTREE" diff --name-only "$PRIMARY_RUNTIME_HEAD" "$PRIMARY_REPORT_HEAD")" = "$REPORT"
test -z "$(git -C "$PRIMARY_WORKTREE" status --short)"
test "$(git -C "$COMPAT" rev-parse --show-toplevel)" = "$COMPAT"
test "$(git -C "$COMPAT" branch --show-current)" = compat/comment-mentions-7.4
test "$(git -C "$COMPAT" rev-parse HEAD)" = "$COMPAT_RUNTIME_HEAD"
test "$(git -C "$COMPAT" rev-list --count "$OFFICIAL_STABLE"..HEAD)" = 1
test "$(git -C "$COMPAT" rev-parse HEAD^)" = "$OFFICIAL_STABLE"
test -z "$(git -C "$COMPAT" status --short)"
test -s "$PATCH"
test "$(sha256sum "$PATCH" | cut -d' ' -f1)" = "$PATCH_SHA256"

COMPAT_NEXT="$(mktemp /tmp/comment-mentions-compat.XXXXXX)"
printf 'export COMPAT=%q\nexport PRIMARY_HEAD=%q\nexport PRIMARY_RUNTIME_HEAD=%q\nexport PRIMARY_REPORT_HEAD=%q\nexport PRIMARY_HANDOFF_HEAD=%q\nexport COMPAT_HEAD=%q\nexport COMPAT_RUNTIME_HEAD=%q\nexport PATCH=%q\nexport PATCH_SHA256=%q\n' \
  "$COMPAT" "$PRIMARY_RUNTIME_HEAD" "$PRIMARY_RUNTIME_HEAD" "$PRIMARY_REPORT_HEAD" "$PRIMARY_HANDOFF_HEAD" "$COMPAT_RUNTIME_HEAD" "$COMPAT_RUNTIME_HEAD" "$PATCH" "$PATCH_SHA256" > "$COMPAT_NEXT"
test -s "$COMPAT_NEXT"
mv "$COMPAT_NEXT" "$TASK15_COMPAT_ENV"
```

Expected: the runtime head/checksum remain distinct from the later report-only head; the report is complete but provisional while primary is alpha.

- [ ] **Step 11: Audit retained local-only handoff and stop publication**

```bash
test -s "$TASK15_BASES_ENV"
test -s "$TASK15_COMPAT_ENV"
source "$TASK15_BASES_ENV"
source "$TASK15_COMPAT_ENV"
test -n "$PRIMARY_RUNTIME_HEAD"
test -n "$PRIMARY_REPORT_HEAD"
test -n "$PRIMARY_HANDOFF_HEAD"
test -n "$COMPAT_RUNTIME_HEAD"
test "$PRIMARY_HEAD" = "$PRIMARY_RUNTIME_HEAD"
test "$PRIMARY_HANDOFF_HEAD" = "$PRIMARY_REPORT_HEAD"
test "$COMPAT_HEAD" = "$COMPAT_RUNTIME_HEAD"
test "$(git -C "$COMPAT" rev-parse HEAD^)" = "$OFFICIAL_STABLE"
test "$(git -C "$COMPAT" rev-parse HEAD)" = "$COMPAT_RUNTIME_HEAD"
test -z "$(git -C "$COMPAT" status --short)"
test -z "$(git -C "$COMPAT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)"
test -z "$(git -C "$PRIMARY_WORKTREE" for-each-ref --format='%(refname)' refs/remotes | rg '/compat/comment-mentions-7\.4$')"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$PRIMARY_REPORT_HEAD"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD^)" = "$PRIMARY_RUNTIME_HEAD"
test -z "$(git -C "$PRIMARY_WORKTREE" status --short)"
git -C "$PRIMARY_WORKTREE" status --short --branch
```

Expected: exact stable ancestry, one clean retained compatibility commit, no upstream/remote compatibility branch, clean primary report head, validated `/tmp` state, and no publication. Task 16 owns all beta-or-later and publication claims.

---

### Task 16: Wagtail 8.0 Release Checkpoint and Re-plan Gate

**Files:**
- Modify no tracked files while this checkpoint is pending or requests a re-plan.
- Create outside git only: `/tmp/comment-mentions-task16-pending.env`.
- Only a future, independently reviewed plan may authorize changes to the compatibility report or runtime sources.

**Interfaces:**
- Consumes: clean, completed Task 14/15 evidence; the exact recorded primary runtime/report/handoff and retained compatibility heads; freshly queried official `main`, `stable/7.4.x`, and immutable `refs/tags/v8.0*`.
- Produces: one validated `/tmp/comment-mentions-task16-pending.env` observation with exact OIDs, parsed versions, tag refs/OIDs, timestamp, and either `PENDING_OFFICIAL_8_RELEASE` or `REPLAN_REQUIRED`.
- Current status: externally blocked while official `main` remains Wagtail 8.0 alpha. This checkpoint makes no compatibility, support, integration, or publication claim.

- [ ] **Step 1: Validate the completed Task 15 handoff before network access**

Run before any network action:

```bash
TASK16_BASES_ENV=/tmp/comment-mentions-bases.env
TASK16_COMPAT_ENV=/tmp/comment-mentions-compat.env
TASK16_CHECKPOINT=/tmp/comment-mentions-task16-pending.env
test -s "$TASK16_BASES_ENV"
test -s "$TASK16_COMPAT_ENV"
source "$TASK16_BASES_ENV"
source "$TASK16_COMPAT_ENV"

for required in \
  PRIMARY_WORKTREE OFFICIAL_MAIN OFFICIAL_STABLE PRIMARY_BASE REDESIGN_BASE \
  PRIMARY_VERSION COMPAT PRIMARY_HEAD PRIMARY_RUNTIME_HEAD PRIMARY_REPORT_HEAD \
  PRIMARY_HANDOFF_HEAD COMPAT_HEAD COMPAT_RUNTIME_HEAD PATCH PATCH_SHA256
do
  test -n "${!required}"
done

test "$PRIMARY_HEAD" = "$PRIMARY_RUNTIME_HEAD"
test "$PRIMARY_HANDOFF_HEAD" = "$PRIMARY_REPORT_HEAD"
test "$COMPAT_HEAD" = "$COMPAT_RUNTIME_HEAD"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse --show-toplevel)" = "$PRIMARY_WORKTREE"
test "$(git -C "$PRIMARY_WORKTREE" branch --show-current)" = worktree/comment-mentions
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$PRIMARY_REPORT_HEAD"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse "$PRIMARY_REPORT_HEAD^")" = "$PRIMARY_RUNTIME_HEAD"
test "$(git -C "$PRIMARY_WORKTREE" merge-base "$PRIMARY_BASE" "$PRIMARY_RUNTIME_HEAD")" = "$PRIMARY_BASE"
test "$(git -C "$PRIMARY_WORKTREE" diff --name-only "$PRIMARY_RUNTIME_HEAD" "$PRIMARY_REPORT_HEAD")" = docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md
test -z "$(git -C "$PRIMARY_WORKTREE" status --short)"

test "$(git -C "$COMPAT" rev-parse --show-toplevel)" = "$COMPAT"
test "$(git -C "$COMPAT" branch --show-current)" = compat/comment-mentions-7.4
test "$(git -C "$COMPAT" rev-parse HEAD)" = "$COMPAT_RUNTIME_HEAD"
test "$(git -C "$COMPAT" rev-list --count "$OFFICIAL_STABLE"..HEAD)" = 1
test "$(git -C "$COMPAT" rev-parse HEAD^)" = "$OFFICIAL_STABLE"
test -z "$(git -C "$COMPAT" status --short)"
test -z "$(git -C "$COMPAT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)"
test -z "$(git -C "$PRIMARY_WORKTREE" for-each-ref --format='%(refname)' refs/remotes | rg '/compat/comment-mentions-7\.4$')"

test -s "$PATCH"
test "$(sha256sum "$PATCH" | cut -d' ' -f1)" = "$PATCH_SHA256"
PRIMARY_HEAD_BEFORE="$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)"
COMPAT_HEAD_BEFORE="$(git -C "$COMPAT" rev-parse HEAD)"
PRIMARY_BRANCH_BEFORE="$(git -C "$PRIMARY_WORKTREE" branch --show-current)"
COMPAT_BRANCH_BEFORE="$(git -C "$COMPAT" branch --show-current)"
```

Expected: both paths, branches, heads, exact report/runtime and compatibility parents, clean worktrees, frozen patch, aliases, and local-only compatibility state match Task 15. Any mismatch is a hard stop before network access.

- [ ] **Step 2: Query official refs, parse fetched VERSION tuples, and record the observation atomically**

Fetch only remote-tracking refs, query immutable tag refs, and parse `VERSION` from the fetched branch Git objects with the primary checked-in environment:

```bash
REMOTE=https://github.com/wagtail/wagtail.git
PRIMARY_PY="$PRIMARY_WORKTREE/.venv/bin/python"
test -x "$PRIMARY_PY"

if ! git -C "$PRIMARY_WORKTREE" fetch --no-tags "$REMOTE" \
  +refs/heads/main:refs/remotes/upstream/main \
  +refs/heads/stable/7.4.x:refs/remotes/upstream/stable/7.4.x
then
  printf '%s\n' 'HARD STOP: official branch query failed' >&2
  exit 1
fi

TAG_REFS_FILE="$(mktemp /tmp/comment-mentions-task16-tags.XXXXXX)"
if ! git ls-remote --tags --refs "$REMOTE" 'refs/tags/v8.0*' > "$TAG_REFS_FILE"; then
  printf '%s\n' 'HARD STOP: official tag query failed' >&2
  exit 1
fi

OBSERVED_OFFICIAL_MAIN="$(git -C "$PRIMARY_WORKTREE" rev-parse refs/remotes/upstream/main)"
OBSERVED_OFFICIAL_STABLE="$(git -C "$PRIMARY_WORKTREE" rev-parse refs/remotes/upstream/stable/7.4.x)"
MAIN_VERSION_SOURCE="$(mktemp /tmp/comment-mentions-task16-main-version.XXXXXX)"
STABLE_VERSION_SOURCE="$(mktemp /tmp/comment-mentions-task16-stable-version.XXXXXX)"
if ! git -C "$PRIMARY_WORKTREE" show "$OBSERVED_OFFICIAL_MAIN:wagtail/__init__.py" > "$MAIN_VERSION_SOURCE"; then
  printf '%s\n' 'HARD STOP: fetched main VERSION provenance failed' >&2
  exit 1
fi
if ! git -C "$PRIMARY_WORKTREE" show "$OBSERVED_OFFICIAL_STABLE:wagtail/__init__.py" > "$STABLE_VERSION_SOURCE"; then
  printf '%s\n' 'HARD STOP: fetched stable VERSION provenance failed' >&2
  exit 1
fi

VERSION_AST='import ast, pathlib, sys; tree = ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")); matches = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets)]; assert len(matches) == 1; value = ast.literal_eval(matches[0].value); assert isinstance(value, tuple) and len(value) == 5; assert value[:3] == tuple(map(int, value[:3])); assert value[3] in {"alpha", "beta", "rc", "final"}; assert isinstance(value[4], int) and value[4] >= 0; print(repr(value))'
if ! OBSERVED_OFFICIAL_MAIN_VERSION="$("$PRIMARY_PY" -c "$VERSION_AST" "$MAIN_VERSION_SOURCE")"; then
  printf '%s\n' 'HARD STOP: fetched main VERSION parser failed' >&2
  exit 1
fi
if ! OBSERVED_OFFICIAL_STABLE_VERSION="$("$PRIMARY_PY" -c "$VERSION_AST" "$STABLE_VERSION_SOURCE")"; then
  printf '%s\n' 'HARD STOP: fetched stable VERSION parser failed' >&2
  exit 1
fi
if ! OBSERVED_OFFICIAL_MAIN_VERSION="$OBSERVED_OFFICIAL_MAIN_VERSION" OBSERVED_OFFICIAL_STABLE_VERSION="$OBSERVED_OFFICIAL_STABLE_VERSION" "$PRIMARY_PY" -c 'import ast, os; ast.literal_eval(os.environ["OBSERVED_OFFICIAL_MAIN_VERSION"]); stable = ast.literal_eval(os.environ["OBSERVED_OFFICIAL_STABLE_VERSION"]); assert stable[:2] == (7, 4) and stable[3] == "final"'; then
  printf '%s\n' 'HARD STOP: official branch VERSION provenance is outside the checkpoint contract' >&2
  exit 1
fi

if ! ELIGIBLE_8_RELEASE_REFS_OIDS="$("$PRIMARY_PY" - "$TAG_REFS_FILE" <<'PY'
import pathlib
import re
import sys

oid_pattern = re.compile(r"^[0-9a-f]{40,64}$")
eligible_pattern = re.compile(r"^refs/tags/v8\.0(?:(?:b|rc)[1-9][0-9]*|)$")
seen = set()
eligible = []
for number, line in enumerate(
    pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines(), 1
):
    parts = line.split()
    if len(parts) != 2:
        raise SystemExit(f"invalid ls-remote line {number}")
    oid, ref = parts
    if not oid_pattern.fullmatch(oid) or not ref.startswith("refs/tags/v8.0"):
        raise SystemExit(f"invalid 8.0 tag provenance at line {number}")
    if ref in seen:
        raise SystemExit(f"duplicate 8.0 tag ref: {ref}")
    seen.add(ref)
    if eligible_pattern.fullmatch(ref):
        eligible.append(f"{oid}\t{ref}")
print("\n".join(sorted(eligible)))
PY
)"; then
  printf '%s\n' 'HARD STOP: official tag provenance parser failed' >&2
  exit 1
fi
ALL_8_TAG_REFS_OIDS="$(cat "$TAG_REFS_FILE")"
CHECKED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
test -n "$OBSERVED_OFFICIAL_MAIN"
test -n "$OBSERVED_OFFICIAL_STABLE"
test -n "$OBSERVED_OFFICIAL_MAIN_VERSION"
test -n "$OBSERVED_OFFICIAL_STABLE_VERSION"
test -n "$CHECKED_AT"
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$PRIMARY_HEAD_BEFORE"
test "$(git -C "$COMPAT" rev-parse HEAD)" = "$COMPAT_HEAD_BEFORE"
test "$(git -C "$PRIMARY_WORKTREE" branch --show-current)" = "$PRIMARY_BRANCH_BEFORE"
test "$(git -C "$COMPAT" branch --show-current)" = "$COMPAT_BRANCH_BEFORE"
test -z "$(git -C "$PRIMARY_WORKTREE" status --short)"
test -z "$(git -C "$COMPAT" status --short)"

STATUS=OBSERVED_OFFICIAL_8_STATE
REASON='official refs recorded; release decision not yet applied'
CHECKPOINT_NEXT="$(mktemp /tmp/comment-mentions-task16-pending.XXXXXX)"
printf 'export STATUS=%q\nexport REASON=%q\nexport PRIMARY_WORKTREE=%q\nexport PRIMARY_BRANCH=%q\nexport COMPAT=%q\nexport COMPAT_BRANCH=%q\nexport RECORDED_OFFICIAL_MAIN=%q\nexport RECORDED_OFFICIAL_STABLE=%q\nexport PRIMARY_BASE=%q\nexport REDESIGN_BASE=%q\nexport RECORDED_PRIMARY_VERSION=%q\nexport PRIMARY_RUNTIME_HEAD=%q\nexport PRIMARY_REPORT_HEAD=%q\nexport PRIMARY_HANDOFF_HEAD=%q\nexport COMPAT_RUNTIME_HEAD=%q\nexport PATCH=%q\nexport PATCH_SHA256=%q\nexport OBSERVED_OFFICIAL_MAIN=%q\nexport OBSERVED_OFFICIAL_MAIN_VERSION=%q\nexport OBSERVED_OFFICIAL_STABLE=%q\nexport OBSERVED_OFFICIAL_STABLE_VERSION=%q\nexport ALL_8_TAG_REFS_OIDS=%q\nexport ELIGIBLE_8_RELEASE_REFS_OIDS=%q\nexport CHECKED_AT=%q\n' \
  "$STATUS" "$REASON" "$PRIMARY_WORKTREE" "$PRIMARY_BRANCH_BEFORE" "$COMPAT" "$COMPAT_BRANCH_BEFORE" \
  "$OFFICIAL_MAIN" "$OFFICIAL_STABLE" "$PRIMARY_BASE" "$REDESIGN_BASE" "$PRIMARY_VERSION" \
  "$PRIMARY_RUNTIME_HEAD" "$PRIMARY_REPORT_HEAD" \
  "$PRIMARY_HANDOFF_HEAD" "$COMPAT_RUNTIME_HEAD" "$PATCH" "$PATCH_SHA256" \
  "$OBSERVED_OFFICIAL_MAIN" "$OBSERVED_OFFICIAL_MAIN_VERSION" "$OBSERVED_OFFICIAL_STABLE" \
  "$OBSERVED_OFFICIAL_STABLE_VERSION" "$ALL_8_TAG_REFS_OIDS" "$ELIGIBLE_8_RELEASE_REFS_OIDS" \
  "$CHECKED_AT" > "$CHECKPOINT_NEXT"
test -s "$CHECKPOINT_NEXT"
( source "$CHECKPOINT_NEXT" && test "$STATUS" = OBSERVED_OFFICIAL_8_STATE && test -n "$OBSERVED_OFFICIAL_MAIN" && test -n "$OBSERVED_OFFICIAL_STABLE" && test -n "$CHECKED_AT" )
mv "$CHECKPOINT_NEXT" "$TASK16_CHECKPOINT"
```

Expected: command, parser, malformed-ref, wrong-release-line, or Git-object provenance failures exit nonzero and do not masquerade as a pending release. A valid query with no eligible beta/RC/final ref is recorded successfully with an empty `ELIGIBLE_8_RELEASE_REFS_OIDS`.

- [ ] **Step 3: Classify the official release state without mutating tracked or Git history state**

Source and validate the complete observation, then atomically replace it with the checkpoint decision:

```bash
TASK16_CHECKPOINT=/tmp/comment-mentions-task16-pending.env
source "$TASK16_CHECKPOINT"
for required in \
  PRIMARY_WORKTREE PRIMARY_BRANCH COMPAT COMPAT_BRANCH RECORDED_OFFICIAL_MAIN \
  RECORDED_OFFICIAL_STABLE PRIMARY_BASE REDESIGN_BASE RECORDED_PRIMARY_VERSION \
  PRIMARY_RUNTIME_HEAD PRIMARY_REPORT_HEAD \
  PRIMARY_HANDOFF_HEAD COMPAT_RUNTIME_HEAD PATCH PATCH_SHA256 \
  OBSERVED_OFFICIAL_MAIN OBSERVED_OFFICIAL_MAIN_VERSION OBSERVED_OFFICIAL_STABLE \
  OBSERVED_OFFICIAL_STABLE_VERSION CHECKED_AT
do
  test -n "${!required}"
done
test "$STATUS" = OBSERVED_OFFICIAL_8_STATE
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$PRIMARY_REPORT_HEAD"
test "$(git -C "$COMPAT" rev-parse HEAD)" = "$COMPAT_RUNTIME_HEAD"
test -z "$(git -C "$PRIMARY_WORKTREE" status --short)"
test -z "$(git -C "$COMPAT" status --short)"

if ! MAIN_IS_8_ALPHA="$(
  OBSERVED_OFFICIAL_MAIN_VERSION="$OBSERVED_OFFICIAL_MAIN_VERSION" "$PRIMARY_WORKTREE/.venv/bin/python" -c 'import ast, os; value = ast.literal_eval(os.environ["OBSERVED_OFFICIAL_MAIN_VERSION"]); print("yes" if value[:4] == (8, 0, 0, "alpha") and isinstance(value[4], int) else "no")'
)"; then
  printf '%s\n' 'HARD STOP: checkpoint VERSION decision parser failed' >&2
  exit 1
fi
test "$MAIN_IS_8_ALPHA" = yes || test "$MAIN_IS_8_ALPHA" = no
if test "$MAIN_IS_8_ALPHA" = yes && test -z "$ELIGIBLE_8_RELEASE_REFS_OIDS"; then
  STATUS=PENDING_OFFICIAL_8_RELEASE
  REASON='official main remains 8.0 alpha and no immutable 8.0 beta, RC, or final tag exists'
else
  STATUS=REPLAN_REQUIRED
  REASON='official main or immutable 8.0 release refs changed; a newly reviewed integration plan is required'
fi

CHECKPOINT_NEXT="$(mktemp /tmp/comment-mentions-task16-pending.XXXXXX)"
printf 'export STATUS=%q\nexport REASON=%q\nexport PRIMARY_WORKTREE=%q\nexport PRIMARY_BRANCH=%q\nexport COMPAT=%q\nexport COMPAT_BRANCH=%q\nexport RECORDED_OFFICIAL_MAIN=%q\nexport RECORDED_OFFICIAL_STABLE=%q\nexport PRIMARY_BASE=%q\nexport REDESIGN_BASE=%q\nexport RECORDED_PRIMARY_VERSION=%q\nexport PRIMARY_RUNTIME_HEAD=%q\nexport PRIMARY_REPORT_HEAD=%q\nexport PRIMARY_HANDOFF_HEAD=%q\nexport COMPAT_RUNTIME_HEAD=%q\nexport PATCH=%q\nexport PATCH_SHA256=%q\nexport OBSERVED_OFFICIAL_MAIN=%q\nexport OBSERVED_OFFICIAL_MAIN_VERSION=%q\nexport OBSERVED_OFFICIAL_STABLE=%q\nexport OBSERVED_OFFICIAL_STABLE_VERSION=%q\nexport ALL_8_TAG_REFS_OIDS=%q\nexport ELIGIBLE_8_RELEASE_REFS_OIDS=%q\nexport CHECKED_AT=%q\n' \
  "$STATUS" "$REASON" "$PRIMARY_WORKTREE" "$PRIMARY_BRANCH" "$COMPAT" "$COMPAT_BRANCH" \
  "$RECORDED_OFFICIAL_MAIN" "$RECORDED_OFFICIAL_STABLE" "$PRIMARY_BASE" "$REDESIGN_BASE" \
  "$RECORDED_PRIMARY_VERSION" "$PRIMARY_RUNTIME_HEAD" \
  "$PRIMARY_REPORT_HEAD" "$PRIMARY_HANDOFF_HEAD" "$COMPAT_RUNTIME_HEAD" "$PATCH" "$PATCH_SHA256" \
  "$OBSERVED_OFFICIAL_MAIN" "$OBSERVED_OFFICIAL_MAIN_VERSION" "$OBSERVED_OFFICIAL_STABLE" \
  "$OBSERVED_OFFICIAL_STABLE_VERSION" "$ALL_8_TAG_REFS_OIDS" "$ELIGIBLE_8_RELEASE_REFS_OIDS" \
  "$CHECKED_AT" > "$CHECKPOINT_NEXT"
test -s "$CHECKPOINT_NEXT"
( source "$CHECKPOINT_NEXT" && test "$STATUS" = PENDING_OFFICIAL_8_RELEASE || test "$STATUS" = REPLAN_REQUIRED )
mv "$CHECKPOINT_NEXT" "$TASK16_CHECKPOINT"

if test "$STATUS" = PENDING_OFFICIAL_8_RELEASE; then
  printf '%s\n' 'BLOCKED: waiting on official Wagtail 8.0 beta, RC, or final release state'
else
  printf '%s\n' 'STOP: official release state changed; re-plan before any mutation'
fi
exit 0
```

Expected: exactly alpha plus an empty eligible-release set yields `PENDING_OFFICIAL_8_RELEASE`, reports an external-state block, changes no tracked file or Git history, and stops successfully. Any main state beyond that exact alpha tuple, or any immutable 8.0 beta/RC/final ref, yields `REPLAN_REQUIRED` with the observed refs preserved and stops before mutation.

- [ ] **Step 4: Require a new independently reviewed execution plan**

The user/controller must create and independently review a fresh plan before any primary/compatibility integration. That future plan must separately authorize and define integration, complete 8.0 and 7.4 reruns, compatibility-report refresh, and any later publication. Task 16 remains incomplete until that future plan executes; this checkpoint makes no support or publication claim.

**Verification:**

```bash
source /tmp/comment-mentions-task16-pending.env
test "$STATUS" = PENDING_OFFICIAL_8_RELEASE || test "$STATUS" = REPLAN_REQUIRED
test "$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)" = "$PRIMARY_REPORT_HEAD"
test "$(git -C "$COMPAT" rev-parse HEAD)" = "$COMPAT_RUNTIME_HEAD"
test "$(git -C "$COMPAT" rev-list --count "$RECORDED_OFFICIAL_STABLE"..HEAD)" = 1
test "$(git -C "$COMPAT" rev-parse HEAD^)" = "$RECORDED_OFFICIAL_STABLE"
test -z "$(git -C "$PRIMARY_WORKTREE" status --short)"
test -z "$(git -C "$COMPAT" status --short)"
test -z "$(git -C "$COMPAT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)"
test -z "$(git -C "$PRIMARY_WORKTREE" for-each-ref --format='%(refname)' refs/remotes | rg '/compat/comment-mentions-7\.4$')"
test -s /tmp/comment-mentions-task16-pending.env
```

Expected: primary and compatibility heads, branches, parents, and clean states are unchanged; compatibility remains exactly one local commit with no upstream or remote branch; the checkpoint is complete and only records official release state. Create no commit for either checkpoint status.
