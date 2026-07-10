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
- The editor is toolbar-free Mini Draftail with only `IMMUTABLE` `MENTION` entities. It persists neither raw Draft.js content nor rich-text formatting and never uses canvas, a textarea overlay, user-management links, or email in ordinary author records.
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
- Consumes: backend wire schema.
- Produces: `MentionOccurrence`, `SerializedMentionOccurrence`, `MentionSuggestion`, `MentionedUser`, `MentionQuery`, canonical conversion, query recognition, and display segmentation helpers.

- [ ] **Step 1: Write the failing pure helper suite**

Define and test these exact interfaces:

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
```

Test: beginning/punctuation boundaries; no trigger inside `person@example.com`; email query with a second `@`; Unicode letters; whitespace/newline/unsupported punctuation termination; 1/64/65 UTF-16 units; collapsed selection only; duplicate labels/users; repeated occurrences; emoji and multiline offsets; malformed display ranges falling back to plain text; deterministic sort; snake/camel round-trip; and `MentionedUser.email` remaining separate from occurrence identity and labels.

- [ ] **Step 2: Run and verify the helper module is absent**

Run:

```bash
npm run test:unit -- --runInBand \
  client/src/components/CommentApp/utils/mentions.test.ts
```

Expected: FAIL because `utils/mentions.ts` does not exist.

- [ ] **Step 3: Implement pure helpers**

Export:

```typescript
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

Use JavaScript string lengths directly for UTF-16 units. Conversion sorts already-valid occurrences by `(start, end, key)` without attaching live metadata. Display segmentation validates monotonic ranges and exact label slices defensively; malformed input renders the complete value as plain text. Never infer identity from label or email text.

- [ ] **Step 4: Verify pure helpers, lint, and typecheck**

Run:

```bash
npm run test:unit -- --runInBand \
  client/src/components/CommentApp/utils/mentions.test.ts
./node_modules/.bin/eslint --report-unused-disable-directives \
  client/src/components/CommentApp/utils/mentions.ts \
  client/src/components/CommentApp/utils/mentions.test.ts
npm run lint:ts
```

Expected: all PASS.

- [ ] **Step 5: Commit pure client behavior**

```bash
git add client/src/components/CommentApp/utils/mentions.ts client/src/components/CommentApp/utils/mentions.test.ts
git commit -m "Add client-side mention wire helpers"
```

---

### Task 10: Comment/Reply State, Hydration, Dirty Checks, and Hidden Forms

**Files:**
- Modify: `wagtail/admin/forms/comments.py`
- Modify: `wagtail/admin/tests/test_edit_handlers.py`
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

**Interfaces:**
- Consumes: Task 9 internal/wire types.
- Produces: full occurrence state for comments, existing replies, and new replies; a separate current-email map in global settings; complete hidden JSON; autosave-safe hydration.

- [ ] **Step 1: Write failing state/form/hydration tests**

Assert all three state copies for both message types:

```typescript
expect(reply).toMatchObject({
  mentions: [mention],
  originalMentions: [mention],
  newMentions: [],
});
```

Dirty-state cases: add/remove/move/label/key/user changes; exact revert to original; comment and reply independently; a creating unsaved comment remains excluded until committed.

Assert exact hidden values:

```typescript
expect(
  wrapper.find('input[name="comments-0-replies-0-mentions"]').prop('value'),
).toBe(JSON.stringify([{ key, user_id, start, end, label }]));
```

Hydration tests must load serialized comment/reply occurrences and `mentioned_users`, update both via autosave, preserve canonical occurrence values, replace current emails without changing text/labels or dirty state, clear working values, omit deleted-user metadata cleanly, and never require author email/URL data. A bound server rejection must serialize only the generic `mentions` error onto the exact comment or reply, retain the submitted occurrence list, and hydrate that error into the matching client state without exposing target details.

- [ ] **Step 2: Run focused tests and verify failures**

Run:

```bash
npm run test:unit -- --runInBand \
  client/src/components/CommentApp/state/comments.test.ts \
  client/src/components/CommentApp/selectors/selectors.test.ts \
  client/src/components/CommentApp/components/Form/index.test.tsx \
  client/src/components/CommentApp/main.test.tsx
```

Expected: FAIL because replies/new replies lack occurrence state and current hydration depends on author email metadata.

- [ ] **Step 3: Implement atomic state fields and dirty comparison**

Use `MentionOccurrence[]` for:

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

Initialize arrays without sharing mutable references and initialize `mentionError` independently on comments and replies. Hydration/update loads `mention_error`; the first local text or occurrence change clears only that message's error. Dirty comparison must compare canonical serialized occurrence arrays, including key, user ID, range, and label; sorting only normalizes already-valid `(start,end,key)` order. A server error is presentation state and does not itself make the page dirty.

Add to global settings without mixing it into occurrence identity:

```typescript
mentionedUsers: Record<string, MentionedUser>;
```

- [ ] **Step 4: Implement complete hidden forms and wire hydration**

Add serialized `mentions` plus an optional generic `mention_error` to `InitialComment` and `InitialCommentReply`, and add the exact server key to `CommentAppData`:

```typescript
mentioned_users: Record<string, MentionedUser>;
```

Convert occurrences using Task 9 helpers. Carry `mention_error` separately from occurrence identity and clear it when the user changes that message's text or occurrence list. Always output complete lists for every participating form:

```typescript
value={JSON.stringify(serializeMentionOccurrences(comment.mentions))}
value={JSON.stringify(serializeMentionOccurrences(reply.mentions))}
```

Restore `Author` to ID/name/avatar only. Remove `getMention` and all author email/URL state. Store current email only in `settings.mentionedUsers`; `loadData` and `updateData` must round-trip comments, replies, and that map independently. Updating only `mentioned_users` must leave `selectIsDirty` false.

- [ ] **Step 5: Verify state, forms, hydration, and full types**

Run:

```bash
npm run test:unit -- --runInBand \
  client/src/components/CommentApp/state/comments.test.ts \
  client/src/components/CommentApp/selectors/selectors.test.ts \
  client/src/components/CommentApp/components/Form/index.test.tsx \
  client/src/components/CommentApp/main.test.tsx
npm run lint:ts
```

Expected: all PASS.

- [ ] **Step 6: Commit the state and wire contract**

```bash
git add wagtail/admin/forms/comments.py wagtail/admin/tests/test_edit_handlers.py client/src/components/CommentApp/state client/src/components/CommentApp/selectors client/src/components/CommentApp/__fixtures__/state.tsx client/src/components/CommentApp/components/Form client/src/components/CommentApp/main.tsx client/src/components/CommentApp/main.test.tsx
git commit -m "Track mentions for comments and replies"
```

---

### Task 11: Debounced and Race-Safe Suggestion Hook

**Files:**
- Create: `client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.ts`
- Create: `client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.test.tsx`

**Interfaces:**
- Consumes: `MentionQuery` and exact `{results}` response.
- Produces: `useMentionSuggestions` with closed/loading/ready/empty/error states and explicit close.

- [ ] **Step 1: Write failing fake-timer/request-order tests**

Freeze the interface:

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

Tests use fake timers and deferred fetch promises for: no URL/query; exactly 199/200 ms; clearing old results immediately; abort on changed query/close/unmount; older response resolving last; non-OK; invalid top-level/results/item shapes including missing/non-string `email`; empty list; composition suppression; close remaining closed until the query changes.

- [ ] **Step 2: Run and verify missing hook**

```bash
npm run test:unit -- --runInBand \
  client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.test.tsx
```

Expected: FAIL because the hook does not exist.

- [ ] **Step 3: Implement the state machine**

Use a 200 ms default timer, one `AbortController` per request, and a monotonically increasing request ID checked before every state update. Resolve the supplied path against `window.location.origin`, set only its `q` search parameter from `query.query`, and preserve any existing parameters. Parse required `id`, `label`, and `email` strings plus optional `username` string. A new query sets loading and clears results before the timer; `AbortError` never sets error.

- [ ] **Step 4: Verify the hook and commit**

```bash
npm run test:unit -- --runInBand \
  client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.test.tsx
npm run lint:ts
git add client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.ts client/src/components/CommentApp/components/MentionEditor/useMentionSuggestions.test.tsx
git commit -m "Make mention suggestions race safe"
```

Expected: tests/typecheck PASS; commit contains only the hook and tests.

---

### Task 12: Mini Draftail Mention Entities and Comment/Reply UI

**Files:**
- Create: `client/src/components/CommentApp/components/MentionEditor/draftail.ts`
- Create: `client/src/components/CommentApp/components/MentionEditor/draftail.test.ts`
- Create: `client/src/components/CommentApp/components/MentionEditor/index.tsx`
- Create: `client/src/components/CommentApp/components/MentionEditor/index.test.tsx`
- Delete: `client/src/components/CommentApp/components/MentionTextArea/index.tsx`
- Delete: `client/src/components/CommentApp/components/MentionTextArea/index.test.tsx`
- Create: `client/src/components/CommentApp/components/MentionText/index.tsx`
- Create: `client/src/components/CommentApp/components/MentionText/index.test.tsx`
- Delete: `client/src/components/CommentApp/components/Comment/CommentText.tsx`
- Delete: `client/src/components/CommentApp/components/Comment/CommentText.test.tsx`
- Modify: `client/src/components/CommentApp/components/Comment/index.tsx`
- Create: `client/src/components/CommentApp/components/Comment/index.test.tsx`
- Modify: `client/src/components/CommentApp/components/CommentReply/index.tsx`
- Create: `client/src/components/CommentApp/components/CommentReply/index.test.tsx`
- Modify: `client/src/components/CommentApp/components/Comment/style.scss`

**Interfaces:**
- Consumes: Task 9 helpers, Task 10 state/live metadata, Task 11 hook, and the repository's existing `draftail`, `draft-js`, and `uuid` dependencies.
- Produces: toolbar-free `MENTION` entity hydration/extraction, keyboard/pointer/IME-safe editing, and styled non-link display for comments and replies.

- [ ] **Step 1: Write failing Draftail conversion and renderer tests**

Freeze the conversion contract in `MentionEditor/draftail.test.ts`:

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

Test: plain and multiline hydration; emoji before an entity; multiple blocks; repeated users; duplicate labels; invalid/cross-block/mismatched occurrence fallback; absolute UTF-16 extraction; deterministic `(start,end,key)` ordering; edit before/after an entity; partial edit stripping the `MENTION` entity while retaining characters; whole selection replacement; suggestion insertion plus trailing space and injected UUID; entity/text undo and redo; cut; and plain-text paste not recreating entities.

Use this component contract in `MentionEditor/index.test.tsx`:

```typescript
export interface MentionEditorProps {
  id: string;
  label: string;
  value: string;
  mentions: readonly MentionOccurrence[];
  mentionedUsers: Readonly<Record<string, MentionedUser>>;
  mentionSuggestionsUrl?: string;
  error?: string;
  onChange(value: string, mentions: MentionOccurrence[]): void;
}
```

Test one Draftail `[contenteditable="true"]`, no `<textarea>`, no `.Draftail-Toolbar`, no formatting controls, `stripPastedStyles`, typing Enter/multiline text, selected-range paste, emoji offsets, query recomputation from `EditorState` selection, composition start/end, ArrowUp/Down wrap, Enter selection, Escape close, Tab closing without prevention, pointer selection without blur, loading/empty/error/ready status text, accessible name, listbox ownership, expanded state, and active-option announcement on the actual focusable editor surface. A generic bound `mentions` error must be visibly adjacent to the exact comment/reply editor, use `role="alert"`, and be connected to the focusable surface with `aria-describedby`; no target identifier or permission detail is rendered. The mention decorator renders `.comment__mention`, the saved label, `data-mention-user-id`, and separately hydrated current-email metadata without rewriting visible text. Also prove that a parent echo of the just-emitted value preserves selection/undo history, a genuinely different external value rehydrates the editor, and a metadata-only change rerenders decoration without rehydrating or dirtying content.

Renderer tests cover plain/multiple/repeated ranges, duplicate labels, emoji/multiline, malformed range fallback, HTML-like escaping, and `<span class="comment__mention">` with no link.

- [ ] **Step 2: Run and verify Mini Draftail support is absent**

```bash
npm run test:unit -- --runInBand \
  client/src/components/CommentApp/components/MentionEditor/draftail.test.ts \
  client/src/components/CommentApp/components/MentionEditor/index.test.tsx \
  client/src/components/CommentApp/components/MentionText/index.test.tsx
```

Expected: FAIL because `MentionEditor` and its Draftail conversion module do not exist.

- [ ] **Step 3: Implement deterministic Draftail hydration and extraction**

Use `ContentState.createFromText(value)` so `\n` becomes ordinary Draft blocks. For every structurally valid occurrence, map absolute UTF-16 offsets into one block, require the exact label slice, create a `MENTION` entity with Draft.js `IMMUTABLE` mutability and `{key, userId, label}`, and apply it with `Modifier.applyEntity`. Invalid or cross-block occurrences remain plain text.

Extraction joins blocks with `\n`, walks contiguous `MENTION` entity ranges, converts block offsets back to absolute UTF-16 offsets, requires entity text to equal its snapshot label, and returns canonical sorted occurrences. Query extraction converts the collapsed Draft selection into absolute offsets before calling Task 9's `findMentionQuery`. Suggestion insertion uses `Modifier.replaceText` for the server label, applies a new `MENTION` entity using `uuidv4()` by default, inserts one trailing space without an entity, pushes one undoable change, and forces the selection after that space.

- [ ] **Step 4: Implement the accessible toolbar-free editor**

Define an inert source component because Draftail's `EntityTypeControl` contract requires one even though mentions are inserted only through the autocomplete. Define the entity type once and let `MentionEntity` read `mentionedUsers` from a provider wrapped around the editor, so live metadata changes rerender decoration without becoming entity data or editor content:

```tsx
const MentionEntitySource = () => null;

const mentionEntityType: EntityTypeControl = {
  type: 'MENTION',
  source: MentionEntitySource,
  decorator: MentionEntity,
};
```

The decorator never calls Draftail's `onEdit`, and mention creation always uses Draft.js `IMMUTABLE` mutability in the Task 12 conversion helper. Render controlled `DraftailEditor` with these fixed capabilities:

```tsx
<DraftailEditor
  editorState={editorState}
  onChange={handleEditorChange}
  multiline
  stripPastedStyles
  blockTypes={[]}
  inlineStyles={[]}
  entityTypes={[mentionEntityType]}
  controls={[]}
  topToolbar={null}
  bottomToolbar={null}
  commandToolbar={null}
  commands={false}
  enableHorizontalRule={false}
  enableLineBreak={false}
  showUndoControl={false}
  showRedoControl={false}
/>
```

On each editor-state change, normalize any entity whose current text differs from its stored label by removing that entity association, then serialize and call `onChange(value, mentions)` once. Keep focus and selection in Draftail. When parent props change, compare canonical serialized props with the current editor state: ignore an equal Redux echo so selection and undo history survive, but close suggestions and rebuild the editor state for a genuinely different external text/occurrence value such as cancel or server hydration. A `mentionedUsers`-only change flows through the decorator context and never rebuilds editor state. A small ref-backed ARIA bridge sets `role="combobox"`, `aria-multiline="true"`, `aria-autocomplete="list"`, `aria-haspopup="listbox"`, `aria-controls`, `aria-expanded`, and `aria-activedescendant` on Draft.js's actual contenteditable element and removes stale attributes on close/unmount. When `error` is present, render an adjacent `role="alert"` element with a stable ID and add that ID to `aria-describedby` on the actual contenteditable; remove the attribute when the error clears or the component unmounts. The popup uses `role="listbox"`; items use stable IDs, `role="option"`, and `aria-selected`. Use localized `role="status" aria-live="polite"` text for loading, no matches, unavailable, result count, and active-option changes.

Handle suggestion navigation on bubbled editor key events without a DOM caret walker: ArrowUp/Down changes the active result, Enter inserts only when results are ready, Escape closes, and Tab closes without `preventDefault`. Pointer `mousedown` prevents editor blur and inserts against the saved Draft selection. Composition suppresses queries until `compositionend`; blur, cancel, deletion, and unmount abort outstanding work.

- [ ] **Step 5: Integrate all comment and reply modes**

Comments use IDs `comment-mention-editor-${localId}` with localized labels `Add a comment` / `Edit comment`. New replies use `comment-new-reply-mention-editor-${comment.localId}` and `comment.newReplyMentions`; existing reply edits use `comment-reply-mention-editor-${comment.localId}-${reply.localId}` and `reply.newMentions`.

Pass `settings.mentionedUsers` to every editor and saved renderer. Pass each message's generic server error only to its own editor and clear it on the next local text/mention change. Save commits text and mentions together; cancel restores both; new-reply cancel clears both; display uses `MentionText` for comments and replies. Style inline entities, errors, and selected options for normal and `@media (forced-colors: active)`, cap popup height with scrolling, suppress every Draftail toolbar container, and delete prototype contenteditable/caret-walker styles.

- [ ] **Step 6: Run complete CommentApp unit/style/type verification**

```bash
npm run test:unit -- --runInBand client/src/components/CommentApp
./node_modules/.bin/eslint --report-unused-disable-directives client/src/components/CommentApp
./node_modules/.bin/prettier --check client/src/components/CommentApp
./node_modules/.bin/stylelint "client/src/components/CommentApp/**/*.scss"
npm run lint:ts
```

Expected: all PASS and no snapshot/update warnings; tests prove plain model text, inline `MENTION` spans, current-email metadata separation, and no formatting UI.

- [ ] **Step 7: Commit Mini Draftail comment/reply UI**

```bash
git add client/src/components/CommentApp
git commit -m "Add Mini Draftail comment mention editing"
```

---

### Task 13: Chromium and Axe Browser Regression

**Files:**
- Create: `client/tests/integration/comment-mentions.test.js`

**Interfaces:**
- Consumes: settings UI server, setup-created `admin` superuser, create-page parent ID 2, stable editor IDs from Task 12.
- Produces: full create/edit/comment/reply browser evidence for both primary and compatibility worktrees.

- [ ] **Step 1: Write the failing Playwright scenario**

Use `/admin/pages/add/demosite/standardpage/2/`. The test must:

1. Fill the required page title with a per-run unique value, wait for its slug, and open a comment through the first `[data-comment-add]` control.
2. Type the same representative multiline text and emoji as the Task 1 baseline plus `@adm` into the toolbar-free Draftail contenteditable under the stable create-comment editor ID; assert no Draftail formatting toolbar or controls exist.
3. Assert loading then populated status and run Axe with popup closed/loading/populated.
4. Select `admin` by ArrowDown/Enter, verify an inline `.comment__mention` entity and a hidden five-field occurrence, and assert the entity exposes current email metadata without changing its visible snapshot label.
5. Save the comment, save/autosave the page, follow the returned/hydrated edit URL, and assert the same plain text/range/entity after reload.
6. Edit before/after/through the entity, asserting Draft.js shifts/retention/drop, selection replacement, plain-text paste, and text/entity undo/redo.
7. Add, edit, cancel, save, reload, and remove a reply mention.
8. Query a guaranteed no-match string, assert empty status, and run Axe.
9. Press Tab with results open and assert focus moves instead of inserting; verify the contenteditable listbox attributes close cleanly.

Use `expect(page).toPassAxeTests({include: '.comment'})` for each named state and inspect the hidden inputs rather than private React state. When `COMMENT_MENTIONS_EVIDENCE_DIR` is set, use Node's `fs.promises.mkdir` and `page.screenshot()` to write supplemental `autocomplete-open.png` and final `after-redesign.png` evidence there; otherwise write no artifact. Match the Task 1 viewport and representative content for `after-redesign.png`, and keep generated files out of git.

- [ ] **Step 2: Start the UI server and verify red state**

Prepare once:

```bash
npm --prefix client/tests/integration ci
npm --prefix client/tests/integration exec -- playwright install chromium
export DJANGO_SETTINGS_MODULE=wagtail.test.settings_ui
python ./wagtail/test/manage.py migrate
python ./wagtail/test/manage.py createcachetable
DJANGO_SUPERUSER_EMAIL=admin@example.com \
DJANGO_SUPERUSER_USERNAME=admin \
DJANGO_SUPERUSER_PASSWORD=changeme \
python ./wagtail/test/manage.py createsuperuser --noinput
python ./wagtail/test/manage.py runserver 0:8000
```

In another terminal:

```bash
TEST_ORIGIN=http://127.0.0.1:8000 npm run test:integration -- \
  --runInBand --runTestsByPath client/tests/integration/comment-mentions.test.js
```

Expected before completing the test-support selectors/behavior: FAIL at the first incomplete lifecycle assertion.

- [ ] **Step 3: Finish only test-required production fixes and rerun**

Fix production behavior, not expectations, for any genuine browser discrepancy. Do not add sleeps; wait for visible status, network response, form update, navigation, or hydration events.

Expected final run: all comment mention browser and Axe tests PASS in Chromium.

- [ ] **Step 4: Commit the browser regression**

```bash
git add client/tests/integration/comment-mentions.test.js client/src/components/CommentApp
git commit -m "Test comment mentions in the browser"
```

---

### Task 14: Primary Wagtail 8.0 Verification and Reviewer Artifact

**Files:**
- Modify only if verification finds defects: files owned by Tasks 2-13.
- Create during final evidence work: `docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md` in Task 15.
- Do not modify: `CHANGELOG.txt`, `docs/releases/8.0.md`, `CONTRIBUTORS.md`.

**Interfaces:**
- Consumes: complete primary implementation.
- Produces: green primary Wagtail 8.0 matrix and a PR body drafted from the final diff; results remain provisional if `VERSION` still reports alpha.

- [ ] **Step 1: Run the complete focused backend matrix**

```bash
python -c 'import wagtail; print(wagtail.__version__)'
BACKEND_TESTS=(
  wagtail.tests.test_comments
  wagtail.admin.tests.test_comment_mentions
  wagtail.admin.tests.test_comment_notifications
  wagtail.admin.tests.test_edit_handlers
  wagtail.admin.tests.pages.test_create_page
  wagtail.admin.tests.pages.test_edit_page
  wagtail.admin.tests.test_audit_log
  wagtail.tests.permission_policies.test_page_permission_policies
)

python runtests.py -- "${BACKEND_TESTS[@]}"
USE_EMAIL_USER_MODEL=yes python runtests.py -- "${BACKEND_TESTS[@]}"

uvx --from 'tox>=4,<5' tox \
  -e py313-dj52-sqlite-noelasticsearch-customuser-tz -- "${BACKEND_TESTS[@]}"
uvx --from 'tox>=4,<5' tox \
  -e py313-dj60-sqlite-noelasticsearch-emailuser-tz -- "${BACKEND_TESTS[@]}"
```

Expected: all commands PASS and the exact Wagtail 8.0 version is recorded. An alpha run is valid development evidence but does not discharge Task 16's beta-or-later gate.

- [ ] **Step 2: Run complete frontend/build/static verification**

```bash
npm run test:unit:coverage -- --runInBand client/src/components/CommentApp
npm run lint:ts
npm run lint:js
npm run lint:css
npm run lint:format
npm run lint:project
npm run build
```

Expected: all PASS.

- [ ] **Step 3: Run migration, formatting, diff, and browser gates**

```bash
source /tmp/comment-mentions-bases.env
DJANGO_SETTINGS_MODULE=wagtail.test.settings \
  python -m django makemigrations --check --dry-run
ruff format --check wagtail/admin wagtail/models/pages.py wagtail/migrations/0098_comment_mentions.py
ruff check wagtail/admin wagtail/models/pages.py wagtail/migrations/0098_comment_mentions.py
git diff --check "$OFFICIAL_MAIN"..HEAD
```

Rerun the Task 13 Chromium/Axe command with `COMMENT_MENTIONS_EVIDENCE_DIR=/tmp/wagtail-comment-mentions-pr` so it captures `autocomplete-open.png` and `after-redesign.png`. Compare `before-redesign.png` from `REDESIGN_BASE` with the final image at the same viewport/content; do not commit image artifacts. Run the same user path manually in current Firefox and record Firefox version, OS, keyboard, multiline, paste, emoji, reload, inline entity highlighting, and popup-accessibility outcomes for the PR/compatibility report.

- [ ] **Step 4: Review the final primary diff and history**

```bash
source /tmp/comment-mentions-bases.env
git diff --name-status "$OFFICIAL_MAIN"..HEAD
git diff --stat "$OFFICIAL_MAIN"..HEAD
git log --oneline "$OFFICIAL_MAIN"..HEAD
git status --short --branch
```

Expected: only mention-related code/tests/design/plan files; no generated build output, caches, unrelated edits, release files, or uncommitted changes.

- [ ] **Step 5: Draft the PR description from the final diff**

Use `.github/PULL_REQUEST_TEMPLATE.md` and keep the existing PR rather than opening a replacement. Give it a descriptive feature title, preserve the linked issue, and include a one-sentence solution summary, assumptions, before/after screenshots, and explicit Chromium/Axe/Firefox results as required by Wagtail's first-contribution guide. Explain why plain model text, Mini Draftail entities, occurrence JSON, exact-message inverse indexes, live-email metadata separation, and recipient merging are the right solution. Call out UTF-16 validation, lookup synchronization, create-page recheck, DB-backed candidate filtering, notification overlap, and both 7.4 and 8.0 beta-or-later evidence for careful review. Include the exact tested Wagtail version/OID for each release line; label any alpha result provisional. Include suggested `CHANGELOG.txt`, `docs/releases/8.0.md`, and contributor wording for a core committer, but do not edit those files.

End with:

> This pull request includes code written with the assistance of AI.
> The code has **not yet been reviewed** by a human.

Do not push or edit PR 1 until the user authorizes publication.

---

### Task 15: Retained Wagtail 7.4 Backport and Reproducible Compatibility Report

**Files:**
- Create in sibling worktree: local branch `compat/comment-mentions-7.4` at `/home/jt/dev/made-with-future/wagtail-compat-comment-mentions-7.4`.
- Create on primary: `docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md`.
- Modify on compatibility only: `wagtail/admin/urls/pages.py` for direct view registration and migration dependency/filename only if the freshly fetched graph differs.

**Interfaces:**
- Consumes: final runtime/test diff relative to `PRIMARY_BASE`, exact official stable OID, primary verification commands.
- Produces: retained committed compatibility head, patch SHA-256, adaptation table, range/file comparison, and two-branch test evidence.

- [ ] **Step 1: Refresh refs again and create the retained worktree safely**

Run with network/filesystem approval:

```bash
source /tmp/comment-mentions-bases.env
COMPAT=/home/jt/dev/made-with-future/wagtail-compat-comment-mentions-7.4

git -C "$PRIMARY_WORKTREE" fetch --no-tags https://github.com/wagtail/wagtail.git \
  +refs/heads/main:refs/remotes/upstream/main \
  +refs/heads/stable/7.4.x:refs/remotes/upstream/stable/7.4.x

OFFICIAL_MAIN=$(git -C "$PRIMARY_WORKTREE" rev-parse refs/remotes/upstream/main)
OFFICIAL_STABLE=$(git -C "$PRIMARY_WORKTREE" rev-parse refs/remotes/upstream/stable/7.4.x)
PRIMARY_BASE=$(git -C "$PRIMARY_WORKTREE" merge-base "$OFFICIAL_MAIN" HEAD)
PRIMARY_VERSION=$(python -c 'import wagtail; print(wagtail.__version__)')
test "$PRIMARY_BASE" = "$OFFICIAL_MAIN"

{
  printf 'PRIMARY_WORKTREE=%s\n' "$PRIMARY_WORKTREE"
  printf 'OFFICIAL_MAIN=%s\n' "$OFFICIAL_MAIN"
  printf 'OFFICIAL_STABLE=%s\n' "$OFFICIAL_STABLE"
  printf 'PRIMARY_BASE=%s\n' "$PRIMARY_BASE"
  printf 'REDESIGN_BASE=%s\n' "$REDESIGN_BASE"
  printf 'PRIMARY_VERSION=%s\n' "$PRIMARY_VERSION"
} > /tmp/comment-mentions-bases.env

if test -e "$COMPAT"; then
  test "$(git -C "$COMPAT" branch --show-current)" = "compat/comment-mentions-7.4"
  test -z "$(git -C "$COMPAT" status --short)"
else
  test -z "$(git -C "$PRIMARY_WORKTREE" branch --list compat/comment-mentions-7.4)"
  git -C "$PRIMARY_WORKTREE" worktree add "$COMPAT" \
    -b compat/comment-mentions-7.4 "$OFFICIAL_STABLE"
fi
```

Expected: clean compatibility branch at the recorded official 7.4 OID. On a resumed execution, reuse the existing retained worktree and assert it is clean; never reset/recreate it.

- [ ] **Step 2: Export the redesigned net runtime/test patch, excluding primary-only artifacts**

```bash
source /tmp/comment-mentions-bases.env
COMPAT=/home/jt/dev/made-with-future/wagtail-compat-comment-mentions-7.4
PRIMARY_HEAD=$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)
PATCH=/tmp/comment-mentions-${PRIMARY_HEAD}.patch

git -C "$PRIMARY_WORKTREE" diff --binary --full-index --no-renames \
  --output="$PATCH" "$PRIMARY_BASE" "$PRIMARY_HEAD" -- . \
  ':(exclude)docs/superpowers/**' \
  ':(exclude)CHANGELOG.txt' \
  ':(exclude)CONTRIBUTORS.md' \
  ':(exclude)docs/releases/**'

sha256sum "$PATCH"
git -C "$COMPAT" apply --check "$PATCH" || true
git -C "$COMPAT" apply --3way --index \
  --exclude=wagtail/admin/viewsets/pages.py \
  --exclude=wagtail/admin/urls/pages.py \
  "$PATCH"
```

Do not cherry-pick or format-patch `ea4a8c43f0`, `136e3acb83`, or `52ebbcc9ca`. Resolve no rejected hunks. Register the two shared suggestion views directly in 7.4's `wagtail/admin/urls/pages.py`; inspect the migration dependency and change it only if the refreshed stable graph requires it.

- [ ] **Step 3: Commit the compatibility branch and inspect adaptations**

```bash
source /tmp/comment-mentions-bases.env
COMPAT=/home/jt/dev/made-with-future/wagtail-compat-comment-mentions-7.4
git -C "$COMPAT" diff --check
git -C "$COMPAT" status --short
git -C "$COMPAT" add \
  wagtail client
git -C "$COMPAT" commit -m "Backport comment mentions to Wagtail 7.4"
PRIMARY_HEAD=$(git -C "$PRIMARY_WORKTREE" rev-parse HEAD)
COMPAT_HEAD=$(git -C "$COMPAT" rev-parse HEAD)

{
  printf 'COMPAT=%s\n' "$COMPAT"
  printf 'PRIMARY_HEAD=%s\n' "$PRIMARY_HEAD"
  printf 'COMPAT_HEAD=%s\n' "$COMPAT_HEAD"
} > /tmp/comment-mentions-compat.env
```

Expected: one retained local backport commit; frontend source is unchanged from the primary feature patch; intentional backend differences are limited to route registration and any recorded migration/test placement seam.

- [ ] **Step 4: Run the same backend/frontend/browser matrix on 7.4**

Run the same focused backend tests under the compatibility worktree without relying on Task 14's shell state:

```bash
source /tmp/comment-mentions-bases.env
source /tmp/comment-mentions-compat.env
BACKEND_TESTS=(
  wagtail.tests.test_comments
  wagtail.admin.tests.test_comment_mentions
  wagtail.admin.tests.test_comment_notifications
  wagtail.admin.tests.test_edit_handlers
  wagtail.admin.tests.pages.test_create_page
  wagtail.admin.tests.pages.test_edit_page
  wagtail.admin.tests.test_audit_log
  wagtail.tests.permission_policies.test_page_permission_policies
)

cd "$COMPAT"
uvx --from 'tox>=4,<5' tox \
  -e py313-dj52-sqlite-noelasticsearch-customuser-tz -- "${BACKEND_TESTS[@]}"
uvx --from 'tox>=4,<5' tox \
  -e py313-dj60-sqlite-noelasticsearch-customuser-tz -- "${BACKEND_TESTS[@]}"
uvx --from 'tox>=4,<5' tox \
  -e py313-dj60-sqlite-noelasticsearch-emailuser-tz -- "${BACKEND_TESTS[@]}"

npm ci
npm run test:unit:coverage -- --runInBand client/src/components/CommentApp
npm run lint:ts
npm run lint:js
npm run lint:css
npm run lint:format
npm run lint:project
npm run build

DJANGO_SETTINGS_MODULE=wagtail.test.settings \
  python -m django makemigrations --check --dry-run
ruff format --check wagtail/admin wagtail/models/pages.py wagtail/migrations/0098_comment_mentions.py
ruff check wagtail/admin wagtail/models/pages.py wagtail/migrations/0098_comment_mentions.py
git diff --check "$OFFICIAL_STABLE"..HEAD
```

In one compatibility-worktree terminal, prepare and run the 7.4 UI server:

```bash
source /tmp/comment-mentions-compat.env
cd "$COMPAT"
npm --prefix client/tests/integration ci
npm --prefix client/tests/integration exec -- playwright install chromium
export DJANGO_SETTINGS_MODULE=wagtail.test.settings_ui
python ./wagtail/test/manage.py migrate
python ./wagtail/test/manage.py createcachetable
DJANGO_SUPERUSER_EMAIL=admin@example.com \
DJANGO_SUPERUSER_USERNAME=admin \
DJANGO_SUPERUSER_PASSWORD=changeme \
python ./wagtail/test/manage.py createsuperuser --noinput
python ./wagtail/test/manage.py runserver 0:8000
```

In another compatibility-worktree terminal, run the exact Task 13 scenario against the 7.4 create/edit routes:

```bash
source /tmp/comment-mentions-compat.env
cd "$COMPAT"
COMMENT_MENTIONS_EVIDENCE_DIR=/tmp/wagtail-comment-mentions-compat/7.4 \
TEST_ORIGIN=http://127.0.0.1:8000 npm run test:integration -- \
  --runInBand --runTestsByPath client/tests/integration/comment-mentions.test.js
```

Expected: all PASS. Any frontend adaptation or non-declared backend adaptation is a primary design defect; correct the primary implementation, commit it, port the incremental diff, and rerun both matrices.

- [ ] **Step 5: Generate reproducible comparison evidence**

```bash
source /tmp/comment-mentions-bases.env
source /tmp/comment-mentions-compat.env
EVIDENCE=/tmp/wagtail-comment-mentions-compat
mkdir -p "$EVIDENCE"

git -C "$PRIMARY_WORKTREE" diff --binary --full-index --no-renames \
  --output="$EVIDENCE/primary-runtime.patch" \
  "$PRIMARY_BASE" "$PRIMARY_HEAD" -- . \
  ':(exclude)docs/superpowers/**' \
  ':(exclude)CHANGELOG.txt' \
  ':(exclude)CONTRIBUTORS.md' \
  ':(exclude)docs/releases/**'

sha256sum "$EVIDENCE/primary-runtime.patch"
git -C "$PRIMARY_WORKTREE" range-diff --no-color \
  "$PRIMARY_BASE..$PRIMARY_HEAD" \
  "$OFFICIAL_STABLE..$COMPAT_HEAD"
git -C "$PRIMARY_WORKTREE" diff --name-status "$PRIMARY_BASE" "$PRIMARY_HEAD"
git -C "$COMPAT" diff --name-status "$OFFICIAL_STABLE" "$COMPAT_HEAD"
git -C "$PRIMARY_WORKTREE" diff --stat "$PRIMARY_BASE" "$PRIMARY_HEAD"
git -C "$COMPAT" diff --stat "$OFFICIAL_STABLE" "$COMPAT_HEAD"
git -C "$PRIMARY_WORKTREE" diff --check "$PRIMARY_BASE" "$PRIMARY_HEAD"
git -C "$COMPAT" diff --check "$OFFICIAL_STABLE" "$COMPAT_HEAD"
```

`range-diff` is supplementary because the backport is one redesigned net commit. The authoritative report fields are base/head OIDs, patch checksum, full name/status and stat comparison, explicit adaptation table, and command results.

- [ ] **Step 6: Write and commit the compatibility report on primary**

The report contains these completed headings with literal values/output summaries, never placeholders:

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

Use `apply_patch` to create the report, then:

```bash
source /tmp/comment-mentions-bases.env
git -C "$PRIMARY_WORKTREE" add docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md
git -C "$PRIMARY_WORKTREE" commit -m "Document Wagtail 7.4 mention compatibility"
```

- [ ] **Step 7: Audit the completed 7.4 proof**

Source both `/tmp/comment-mentions-bases.env` and `/tmp/comment-mentions-compat.env`, then re-run `git status`, primary/compat OIDs, full required matrix evidence, and changed-file/history lists. Confirm the compatibility branch remains local and retained, and record whether `PRIMARY_VERSION` is provisional alpha or beta-or-later. Do not publish yet; Task 16 is the final two-release gate.

---

### Task 16: Wagtail 8.0 Beta-or-Later Release Gate

**Files:**
- Modify if OIDs or results changed: `docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md`.
- Modify only after user authorization: the existing PR 1 title/body on GitHub.

**Interfaces:**
- Consumes: the complete primary implementation, retained 7.4 proof, freshly fetched official `main`, and Wagtail's actual `VERSION` tuple.
- Produces: final evidence that the feature works on both Wagtail 7.4 and Wagtail 8.0 beta-or-later; alpha-only evidence cannot satisfy this task.

- [ ] **Step 1: Refresh official main and enforce the 8.0 release-stage gate**

Run with network approval:

```bash
source /tmp/comment-mentions-bases.env
git -C "$PRIMARY_WORKTREE" fetch --no-tags https://github.com/wagtail/wagtail.git \
  +refs/heads/main:refs/remotes/upstream/main

OFFICIAL_MAIN=$(git -C "$PRIMARY_WORKTREE" rev-parse refs/remotes/upstream/main)
PRIMARY_BASE=$(git -C "$PRIMARY_WORKTREE" merge-base "$OFFICIAL_MAIN" HEAD)
PRIMARY_VERSION=$(python -c 'import wagtail; print(wagtail.__version__)')
printf '%s\n' "$OFFICIAL_MAIN" "$PRIMARY_BASE" "$PRIMARY_VERSION"

test "$PRIMARY_BASE" = "$OFFICIAL_MAIN"
python -c 'from wagtail import VERSION; assert VERSION[:3] == (8, 0, 0); assert VERSION[3] in {"beta", "rc", "final"}'

{
  printf 'PRIMARY_WORKTREE=%s\n' "$PRIMARY_WORKTREE"
  printf 'OFFICIAL_MAIN=%s\n' "$OFFICIAL_MAIN"
  printf 'OFFICIAL_STABLE=%s\n' "$OFFICIAL_STABLE"
  printf 'PRIMARY_BASE=%s\n' "$PRIMARY_BASE"
  printf 'REDESIGN_BASE=%s\n' "$REDESIGN_BASE"
  printf 'PRIMARY_VERSION=%s\n' "$PRIMARY_VERSION"
} > /tmp/comment-mentions-bases.env
```

Expected: the primary branch is based on the freshly fetched official `main`, and its version is 8.0 beta, release candidate, or final. If official `main` or the feature branch still reports alpha, record the gate as pending and stop only completion/publication; implementation work and provisional tests may continue. If `main` advanced, obtain user approval before rebuilding/rebasing the existing PR branch, then continue with the refreshed branch rather than opening a replacement PR.

- [ ] **Step 2: Repeat both release-line proofs after the 8.0 refresh**

Rerun every Task 14 backend, frontend, migration, Chromium/Axe, Firefox, diff, and history command on the beta-or-later primary branch. Because a primary rebase changes source OIDs and the exported runtime patch, generate the fresh Task 15 patch/checksum and compare it with the retained 7.4 implementation. Do not apply the full patch over the existing backport. If feature behavior changed, hand-port only the incremental mention changes as a new compatibility commit; otherwise leave its code commit unchanged. Then rerun Task 15 Steps 4-7, refresh `PRIMARY_HEAD` / `COMPAT_HEAD`, update the report's versions, OIDs, checksum, comparisons, and results, and verify that the declared adaptation set remains unchanged.

Expected: the full matrix passes on exact recorded Wagtail 8.0 beta-or-later and Wagtail 7.4 OIDs, not merely on an earlier alpha snapshot.

- [ ] **Step 3: Final two-release completion and publication audit**

Check the seven design-spec acceptance criteria one by one, including exact version strings/OIDs, both browser runs, migration equivalence, compatibility diff evidence, focused history, PR template, screenshots, and AI disclosure. Confirm both worktrees are clean and the 7.4 branch remains local. Only after separate user authorization: push the primary branch, update the existing PR 1 title/body from the verified evidence, verify its remote head/body/checks, and leave it draft until human review occurs.
