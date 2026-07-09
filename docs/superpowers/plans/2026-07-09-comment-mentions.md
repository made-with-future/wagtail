# Comment Mentions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PR 1's unsafe email-token prototype with structured, accessible `@` mentions for page comments and replies, developed on the current Wagtail 8-era branch and proven on Wagtail 7.4.

**Architecture:** Store validated mention occurrences as JSON ranges on `Comment` and `CommentReply`, with shared Python utilities for UTF-16 offsets, canonical user IDs, labels, permission-filtered candidates, audit deltas, and recipient-specific notifications. Keep a native textarea on the client, with pure range/query helpers and a race-safe suggestion hook; routing is the only intended version adapter between main's `PageViewSet` and Wagtail 7.4's direct page URLs.

**Tech Stack:** Python 3.10+, Django 5.2/6.0, Wagtail modelcluster and page permission policy, React/Redux/TypeScript, Jest/Enzyme, Sass/Stylelint, Playwright/Axe, SQLite-focused tox verification, Git worktrees.

## Global Constraints

- Primary development stays on PR 1's current Wagtail 8-era branch; official `main` and `stable/7.4.x` refs must be freshly fetched and recorded before code work and final verification.
- Comments and replies share the exact occurrence contract: `{key, user_id, start, end, label}` with half-open UTF-16 offsets.
- Each message allows at most 20 occurrences, a 16 KiB UTF-8 JSON payload, and 255 UTF-16 units per server-generated label.
- Labels normalize whitespace, fall back to `user.get_username()`, and truncate on a code-point boundary with an ellipsis when needed.
- Suggestion queries allow 1-64 UTF-16 units, debounce for 200 ms, and return at most 10 results as `{id, label, username?}`.
- Candidate filtering uses Django's database-backed `wagtailadmin.access_admin` and Wagtail page-permission semantics before the ten-row slice.
- Omitted mention fields preserve stored metadata; an explicit `[]` clears it; unchanged other-author forms remain unchanged.
- Retained occurrence keys preserve user ID and label without re-authorizing the target; new keys require current target eligibility and the exact current label.
- The editor remains a native textarea. It does not use `contenteditable`, `role="combobox"`, `aria-expanded`, user-management links, or extra email fields.
- Native character edits keep browser paste, multiline, IME, selection, and text-undo behavior. Suggestion insertion is application-driven and is not promised as a native undo entry.
- Notification reasons are merged per recipient after all changed messages are collected; the actor is excluded and the existing updated-comments preference remains authoritative.
- Mention writes, audit data, and revision/page actions must not partially commit. Email is scheduled with `transaction.on_commit` and retains Wagtail's no-retry delivery contract.
- New user-facing strings use Django `gettext` or the frontend `gettext` helper.
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
- `client/src/components/CommentApp/utils/mentions.ts` — wire conversion, query recognition, range reconciliation, suggestion insertion, and display segmentation.
- `client/src/components/CommentApp/utils/mentions.test.ts` — pure frontend contract tests.
- `client/src/components/CommentApp/components/MentionTextArea/useMentionSuggestions.ts` and `.test.tsx` — debounced, abortable, stale-safe request state.
- `client/src/components/CommentApp/components/MentionText/index.tsx` and `index.test.tsx` — escaped, non-linked range rendering.
- `client/src/components/CommentApp/components/Comment/index.test.tsx` and `components/CommentReply/index.test.tsx` — comment/reply lifecycle integration.
- `client/src/components/CommentApp/main.test.tsx` — hydration/autosave round-trip.
- `client/tests/integration/comment-mentions.test.js` — Chromium/Axe create/edit/comment/reply browser regression.
- `docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md` — final reproducible backport report.

**Replace or delete:**

- Replace `wagtail/migrations/0098_commentmention.py` with `wagtail/migrations/0098_comment_mentions.py`.
- Delete the `CommentMention` model/export and all `notified_at` handling.
- Delete `client/src/components/CommentApp/components/Comment/CommentText.tsx` and its current email-link test after `MentionText` replaces them.
- Rewrite `client/src/components/CommentApp/components/MentionTextArea/index.tsx`; remove every contenteditable/caret-walker path.

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
- Produces: shell variables `OFFICIAL_MAIN`, `OFFICIAL_STABLE`, and `PRIMARY_BASE`, plus a verified baseline from which later compatibility patches are generated.

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
printf '%s\n' "$OFFICIAL_MAIN" "$OFFICIAL_STABLE" "$PRIMARY_BASE"
```

Expected: the fetched and `ls-remote` OIDs match for both branches.

- [ ] **Step 3: Enforce the main-base gate**

Run:

```bash
test "$PRIMARY_BASE" = "$OFFICIAL_MAIN"
```

Expected: exit 0. If it fails, stop implementation and obtain approval to rebuild/rebase the PR on official main; do not layer new code over an outdated base or blindly rebase the obsolete prototype series.

- [ ] **Step 4: Reconfirm the known prototype regression before replacing it**

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.pages.test_create_page.TestCommenting.test_comments_enabled_by_default
```

Expected before Task 5: FAIL with `NoReverseMatch` from reversing the edit suggestion URL with `page_id=None`. Preserve the output as the red regression evidence.

---

### Task 2: Structured Occurrence and UTF-16 Primitives

**Files:**
- Create: `wagtail/admin/comment_mentions.py`
- Create: `wagtail/admin/tests/test_comment_mentions.py`

**Interfaces:**
- Consumes: Django's configured user model and Wagtail `user_display_name`.
- Produces: `MentionOccurrence`, `MentionChanges`, constants, UTF-16 helpers, structural validation, stored-value sanitization, retained-key validation, label generation, and text segmentation used by every later backend task.

- [ ] **Step 1: Write failing primitive and validation tests**

Start `wagtail/admin/tests/test_comment_mentions.py` with these exact classes and representative assertions; use subtests to cover every row in the table after the code block.

```python
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
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


def normalize_mention_label(user) -> str:
    identity = re.sub(r"\s+", " ", user_display_name(user)).strip()
    if not identity:
        identity = re.sub(r"\s+", " ", str(user.get_username())).strip()
    return truncate_utf16(f"@{identity}", MAX_MENTION_LABEL_UTF16)
```

Complete `validate_mention_occurrences` with this fixed order: require a list; enforce count; require exactly five fields; canonicalize UUID text; reject boolean/collection user IDs; canonicalize through `get_user_model()._meta.pk.to_python`; require integer non-boolean offsets; require sorted non-overlapping ranges; require UTF-16 boundaries; require `utf16_slice(text, start, end) == label`; and return a tuple sorted by `(start, end, key)`. Implement `validate_retained_mentions` by key, `compare_mentions` by key, `sanitize_stored_mentions` as per-entry defensive validation with one warning per invalid entry, and `split_text_by_mentions` as escaped-data-ready `(text, is_mention)` segments without producing markup.

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

### Task 3: Replace the Relation with Comment and Reply JSON Fields

**Files:**
- Modify: `wagtail/models/pages.py`
- Modify: `wagtail/models/__init__.py`
- Modify: `wagtail/tests/test_comments.py`
- Delete: `wagtail/migrations/0098_commentmention.py`
- Create: `wagtail/migrations/0098_comment_mentions.py`

**Interfaces:**
- Consumes: validated occurrence lists from Task 2.
- Produces: `Comment.mentions` and `CommentReply.mentions`, both `models.JSONField(default=list)`; no relational mention manager or delivery state.

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

Also assert an ordinary `comment.save()` updates text without the prototype's reverse-relation filtering workaround.

- [ ] **Step 2: Run and verify the relation-based implementation fails**

Run:

```bash
python runtests.py -- wagtail.tests.test_comments.TestCommentMentionStorage
```

Expected: FAIL because `comment.mentions` is a related manager and replies have no `mentions` field.

- [ ] **Step 3: Implement the model and migration schema**

Add to both models:

```python
mentions = models.JSONField(default=list)
```

Delete `CommentMention`, its export from `wagtail/models/__init__.py`, the `get_all_child_relations` import introduced solely for that relation, and restore `Comment.save()` to the clean-main concrete-field filtering behavior.

Replace migration `0098_commentmention.py` with:

```python
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
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
git commit -m "Store structured mentions on comments and replies"
```

---

### Task 4: Shared Form Field, Omission Semantics, and Private Serialization

**Files:**
- Create: `wagtail/admin/forms/comment_mentions.py`
- Modify: `wagtail/admin/forms/comments.py`
- Modify: `wagtail/admin/forms/pages.py`
- Modify: `wagtail/admin/panels/comment_panel.py`
- Modify: `wagtail/admin/tests/test_comment_mentions.py`
- Modify: `wagtail/admin/tests/test_edit_handlers.py`

**Interfaces:**
- Consumes: Task 2 validators and Task 3 JSON fields.
- Produces: `CommentMentionsField`, `MentionedMessageFormMixin`, form-level `mention_changes`, comment/reply wire serialization, safe omission handling, and parent-page context for create forms.

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

Cover: unchanged browser payload for another author; resolve/reposition with omitted and hydrated fields; retained target rename/deactivation/deletion/permission loss; malformed/blank/oversize JSON; comment/reply parity; invalid stored entries sanitized without dirtying another-author forms; author JSON remains exactly name/avatar with no email or URL.

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

    def to_python(self, value):
        if value is MENTIONS_OMITTED:
            return MENTIONS_OMITTED
        if not isinstance(value, str) or not value:
            raise ValidationError(_("Enter a valid mention list."))
        if len(value.encode("utf-8")) > MAX_MENTION_JSON_BYTES:
            raise ValidationError(_("Enter a valid mention list."))
        return super().to_python(value)

    def prepare_value(self, value):
        return json.dumps(value, separators=(",", ":"))


class MentionedMessageFormMixin:
    mentions = CommentMentionsField(required=False)
    mention_changes = MentionChanges()

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
        current = list(
            validate_mention_occurrences(
                submitted,
                text=self.cleaned_data.get("text", self.instance.text),
            )
        )
        validate_retained_mentions(initial, current)
        self.mention_changes = compare_mentions(initial, current)
        return current
```

Use a translated user-facing validation message in production rather than exposing parse details.

- [ ] **Step 4: Apply the mixin and serialization contract**

Make both forms consume the mixin:

```python
class CommentReplyForm(MentionedMessageFormMixin, WagtailAdminModelForm):
    class Meta:
        fields = ("text", "mentions")


class CommentForm(MentionedMessageFormMixin, WagtailAdminModelForm):
    resolved = forms.BooleanField(required=False)

    class Meta:
        formsets = {
            "replies": {
                "form": CommentReplyForm,
                "inherit_kwargs": ["for_user", "page", "parent_page"],
            }
        }
```

Set `self.parent_page = parent_page` before `WagtailAdminPageForm` calls `super().__init__`, add `parent_page` to the comment formset's `inherit_kwargs`, and add `page`/`parent_page` to the nested reply formset's inherited kwargs. Serialize each message's complete occurrence list directly, serialize only comment/reply authors, and restore author entries to:

```python
{"name": user_display_name(user), "avatar_url": avatar_url(user)}
```

Remove `save_mentions`, all relation queries, and all mention-driven author expansion. Create serialization must not reverse an edit URL while `page.pk` is `None`; Task 5 supplies the correct two URL variants.

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

Expected: all PASS; serialized UUID IDs are strings; create GET returns 200.

- [ ] **Step 6: Commit the shared form contract**

```bash
git add wagtail/admin/forms/comment_mentions.py wagtail/admin/forms/comments.py wagtail/admin/forms/pages.py wagtail/admin/panels/comment_panel.py wagtail/admin/tests/test_comment_mentions.py wagtail/admin/tests/test_edit_handlers.py
git commit -m "Validate comment and reply mention payloads"
```

---

### Task 5: Permission-Filtered Candidate Services and Both Suggestion Endpoints

**Files:**
- Modify: `wagtail/admin/comment_mentions.py`
- Create: `wagtail/admin/views/pages/comment_mentions.py`
- Modify: `wagtail/admin/forms/comments.py`
- Modify: `wagtail/admin/viewsets/pages.py`
- Modify: `wagtail/admin/urls/pages.py`
- Modify: `wagtail/admin/tests/test_comment_mentions.py`
- Modify: `wagtail/admin/tests/pages/test_create_page.py`

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
                "label": "@Jane Smith",
                "username": self.editor.get_username(),
            }
        ]
    },
)
```

Cover direct/inherited change permission, add-only future owner, add-only non-owner exclusion, superuser, direct/group `access_admin`, inactive target, comments disabled, missing `CommentPanel`, unauthorized requester, invalid parent/type/model, empty/65-unit query, overlong label truncation, deterministic username/PK order, ten-result cap, bounded query count, UUID IDs, and no email/edit URL keys.

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
    return queryset.filter(
        Q(is_superuser=True)
        | Q(user_permissions=access_admin)
        | Q(groups__permissions=access_admin)
    ).distinct()


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

Use available model fields among `first_name`, `last_name`, `EMAIL_FIELD`, and `USERNAME_FIELD` for the `icontains` OR query; order by configured username field and PK, slice to ten after all database eligibility filters, then generate `id`, `label`, and optional distinct `username`.

Add four exact public interfaces. `comments_available_for_page_model(page_model: type[Page]) -> bool` returns false when `WAGTAILADMIN_COMMENTS_ENABLED` is false and otherwise tests for the `comments` formset on the model's edit-handler form class. `search_mention_candidates(candidates, query: str) -> list[dict[str, str]]` enforces the query contract, applies the available-model-field OR query, orders, slices, and maps the exact wire result. `resolve_new_mention_users(occurrences, candidates) -> dict[str, object]` fetches all canonical IDs in one candidates query and rejects a missing user or label that differs from `normalize_mention_label(user)`. `resolve_creatable_page_model(request, parent_page, app_label, model_name) -> type[Page]` applies the same content-type, Page-subclass, parent-permission, `creatable_subpage_models`, and `can_create_at` gates as `CreateView.dispatch`. Call `resolve_new_mention_users` once from `CommentFormSet.clean()` across top-level and nested reply forms.

- [ ] **Step 4: Implement saved/create views and main routing**

Create `wagtail/admin/views/pages/comment_mentions.py` with:

```python
class PageCommentMentionSuggestionsView(View):
    def dispatch(self, request, page_id, **kwargs):
        self.page = get_object_or_404(Page, pk=page_id).specific
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

On main, register viewset names `comment_mention_suggestions` and `create_comment_mention_suggestions`, classes, cached properties, and these URL names:

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
  wagtail.admin.tests.pages.test_create_page.TestCommenting.test_comments_enabled_by_default

USE_EMAIL_USER_MODEL=yes python runtests.py -- \
  wagtail.admin.tests.test_comment_mentions
```

Expected: all PASS; create GET includes a resolvable create suggestion URL; query-count assertions stay fixed as candidate count grows.

- [ ] **Step 6: Commit candidate services and routes**

```bash
git add wagtail/admin/comment_mentions.py wagtail/admin/views/pages/comment_mentions.py wagtail/admin/forms/comments.py wagtail/admin/viewsets/pages.py wagtail/admin/urls/pages.py wagtail/admin/tests/test_comment_mentions.py wagtail/admin/tests/pages/test_create_page.py
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

Assert mention-only edits appear in `edited_comments`/`edited_replies`, added/removed entries are paired to the exact message, and audit JSON is:

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
    mention_changes = []
    for comment_form in comments_formset.forms:
        if comment_form.mention_changes.added or comment_form.mention_changes.removed:
            mention_changes.append(
                MentionedMessage(
                    comment=comment_form.instance,
                    reply=None,
                    changes=comment_form.mention_changes,
                )
            )
        for reply_form in comment_form.formsets["replies"].forms:
            if reply_form.mention_changes.added or reply_form.mention_changes.removed:
                mention_changes.append(
                    MentionedMessage(
                        comment=comment_form.instance,
                        reply=reply_form.instance,
                        changes=reply_form.mention_changes,
                    )
                )

    return CommentingChanges(
        new_comments=list(comments_formset.new_objects),
        deleted_comments=list(comments_formset.deleted_objects),
        resolved_comments=get_resolved_comments(comments_formset.changed_objects),
        edited_comments=get_edited_comments(comments_formset.changed_objects),
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

The collector must inspect `new_objects`, `deleted_objects`, and `changed_objects` once, then attach each form's `mention_changes`; no model queries may rediscover the delta after save.

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

- [ ] **Step 4: Replace view-local change/audit code and verify**

Make `EditView.get_commenting_changes()` and `EditView.log_commenting_changes()` thin delegates initially, so action behavior remains stable before Task 8 changes transaction placement.

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

Cover actor exclusion, profile preference opt-out, inactive/deleted/no-email target, subscriber overlap, thread overlap, mention B plus subscription change A, repeated occurrences, multiple messages, comment/reply context, failed send, and no delivery before transaction commit.

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

Expected: FAIL on cross-message overlap and exact mention copy; the prototype either omits comment B or labels it as a new comment.

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

    def send():
        for users, context in group_identical_payloads(payloads):
            send_notification(users, "updated_comments", context)

    transaction.on_commit(send)
```

Implement `build_recipient_payloads(*, page, editor, changes) -> dict[object, RecipientPayload]` in four fixed passes: seed global subscribers; add thread-participant reasons without excluding users who already have another reason; resolve all users referenced by newly added occurrence keys in one active-user query and add the exact comment/reply reason; then remove messages from later sections when the same message is already in `Mentions`. Every pass excludes only `editor.pk`, preserves formset order, and keys the map by canonical user PK. Implement `group_identical_payloads(payloads)` by a signature containing every ordered message ID and mention-reason flag, returning `(users, template_context)` groups. Let existing `send_notification` apply deliverable email/profile behavior. Do not create `notified_at`, retries, or post-save relation writes.

- [ ] **Step 4: Update all three templates and run exact-copy tests**

Use `{% if mentioned_comments or mentioned_replies %}` in subject/body templates. Render escaped Django template variables without `safe` on comment/reply/label content. Preserve existing non-mention copy byte-for-byte when no mention reason exists.

Run:

```bash
python runtests.py -- wagtail.admin.tests.test_comment_notifications
```

Expected: all notification, order, preference, failure, and on-commit tests PASS.

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

**Interfaces:**
- Consumes: form deltas, change collector, audit dispatcher, notification scheduler, actual-page candidate queryset.
- Produces: no-partial-save edit/create actions for draft, JSON autosave, publish, submit, and workflow paths.

- [ ] **Step 1: Add failing full-lifecycle regressions**

Use real occurrence text/ranges in every payload; never submit a phantom ID with unrelated text. Add tests for:

- top-level and reply mention create/edit/remove;
- mention-only edit dirty/audit behavior;
- ordinary save with another author's unchanged hydrated mentions;
- retained target rename/deactivation/deletion/permission loss;
- edit JSON autosave/save/publish/submit workflows;
- create GET/save JSON/publish/submit with comment and reply mentions;
- target permission loss between future validation and provisional save;
- malformed/new-ineligible occurrence leaves no page/revision/comment/reply/audit/mail;
- mail callback runs only after commit.

Representative create assertion:

```python
with self.captureOnCommitCallbacks(execute=True):
    response = self.client.post(self.add_url, post_data)
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
  wagtail.admin.tests.pages.test_create_page.TestCommenting
```

Expected: FAIL because create does not collect/audit/notify mentions, reply parity is absent, and old notification timing is outside the page transaction.

- [ ] **Step 3: Integrate edit actions without post-save validation or relation writes**

Replace view-local notification/deduplication code with:

```python
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

Place collection, audit, and scheduling inside the same existing or newly added `transaction.atomic()` block as page/comment/reply/revision persistence for save, publish, submit, restart-workflow, workflow-action, and cancel-workflow paths. The callback executes after the outermost commit.

- [ ] **Step 4: Recheck create targets on the provisional real page inside one transaction**

Add to `CommentFormSet`:

```python
def revalidate_new_mentions_for_page(self, page):
    candidates = page_mention_candidates(page)
    added = tuple(
        occurrence
        for form in self.iter_mention_forms()
        for occurrence in form.mention_changes.added
    )
    resolve_new_mention_users(added, candidates)
```

For save/publish/submit create actions, use one `transaction.atomic()` around: provisional `add_child`, actual-page recheck, comment/reply JSON save, revision, subscription, audit, notification scheduling, and publish/workflow start. Convert recheck failure into the `mentions` form error and roll back all database effects. Before HTML rerender after rollback, reconstruct the unsaved page/form instance so its PK/path/depth/state do not describe the rolled-back tree node.

- [ ] **Step 5: Verify all edit/create paths and UUID users**

Run:

```bash
python runtests.py -- \
  wagtail.admin.tests.pages.test_edit_page.TestCommenting \
  wagtail.admin.tests.pages.test_create_page.TestCommenting \
  wagtail.admin.tests.test_comment_notifications

USE_EMAIL_USER_MODEL=yes python runtests.py -- \
  wagtail.admin.tests.pages.test_edit_page.TestCommenting \
  wagtail.admin.tests.pages.test_create_page.TestCommenting
```

Expected: all PASS; no partial rows/logs/mail in invalid cases; UUID payloads serialize cleanly.

- [ ] **Step 6: Commit lifecycle integration**

```bash
git add wagtail/admin/views/pages/edit.py wagtail/admin/views/pages/create.py wagtail/admin/forms/comments.py wagtail/admin/tests/pages/test_edit_page.py wagtail/admin/tests/pages/test_create_page.py
git commit -m "Persist mentions across page comment lifecycles"
```

---

### Task 9: Pure Frontend Mention Query, Range, and Wire Helpers

**Files:**
- Create: `client/src/components/CommentApp/utils/mentions.ts`
- Create: `client/src/components/CommentApp/utils/mentions.test.ts`

**Interfaces:**
- Consumes: backend wire schema.
- Produces: `MentionOccurrence`, `SerializedMentionOccurrence`, `MentionSuggestion`, `MentionQuery`, conversion, reconciliation, insertion, and segmentation helpers.

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
  username?: string;
}

export interface MentionQuery {
  start: number;
  end: number;
  query: string;
}
```

Test: beginning/punctuation boundaries; no trigger inside `person@example.com`; email query with a second `@`; Unicode letters; whitespace/newline/unsupported punctuation termination; 1/64/65 UTF-16 units; collapsed selection only; edits before/after/intersecting ranges; insertion at exact range boundaries; duplicate labels/users; repeated occurrences; emoji offsets; multiline paste replacement; deterministic sort; snake/camel round-trip; exact suggestion replacement plus trailing space and injected UUID key.

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

export function reconcileMentionOccurrences(
  previousValue: string,
  nextValue: string,
  mentions: readonly MentionOccurrence[],
): MentionOccurrence[];

export function applyMentionSuggestion(
  value: string,
  mentions: readonly MentionOccurrence[],
  query: MentionQuery,
  suggestion: MentionSuggestion,
  createKey?: () => string,
): MentionEditResult;

export function splitTextByMentions(
  value: string,
  mentions: readonly MentionOccurrence[],
): MentionTextPart[];
```

Use JavaScript string lengths directly for UTF-16 units. Reconciliation must compute the longest common prefix/suffix, shift ranges when the replaced old interval ends at/before a mention start, retain ranges when it starts at/after a mention end, and drop every intersected range. Never infer identity from label text.

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
git commit -m "Add client-side mention range helpers"
```

---

### Task 10: Comment/Reply State, Hydration, Dirty Checks, and Hidden Forms

**Files:**
- Modify: `client/src/components/CommentApp/state/comments.ts`
- Modify: `client/src/components/CommentApp/state/comments.test.ts`
- Modify: `client/src/components/CommentApp/selectors/index.ts`
- Modify: `client/src/components/CommentApp/selectors/selectors.test.ts`
- Modify: `client/src/components/CommentApp/__fixtures__/state.tsx`
- Modify: `client/src/components/CommentApp/components/Form/index.tsx`
- Modify: `client/src/components/CommentApp/components/Form/index.test.tsx`
- Modify: `client/src/components/CommentApp/main.tsx`
- Create: `client/src/components/CommentApp/main.test.tsx`

**Interfaces:**
- Consumes: Task 9 internal/wire types.
- Produces: full occurrence state for comments, existing replies, and new replies; complete hidden JSON; autosave-safe hydration.

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

Hydration tests must load serialized comment/reply occurrences, update via autosave, preserve canonical values, clear working values, and never require author email/URL data.

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

// CommentReply
mentions;
originalMentions;
newMentions;
```

Initialize arrays without sharing mutable references. Dirty comparison must compare canonical serialized occurrence arrays, including key, user ID, range, and label; sorting only normalizes already-valid `(start,end,key)` order.

- [ ] **Step 4: Implement complete hidden forms and wire hydration**

Add serialized `mentions` to `InitialComment` and `InitialCommentReply`. Convert using Task 9 helpers. Always output complete lists for every participating form:

```typescript
value={JSON.stringify(serializeMentionOccurrences(comment.mentions))}
value={JSON.stringify(serializeMentionOccurrences(reply.mentions))}
```

Restore `Author` to ID/name/avatar only. Remove `getMention` and all email/URL state. `loadData` and `updateData` must round-trip comments and replies independently.

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
git add client/src/components/CommentApp/state client/src/components/CommentApp/selectors client/src/components/CommentApp/__fixtures__/state.tsx client/src/components/CommentApp/components/Form client/src/components/CommentApp/main.tsx client/src/components/CommentApp/main.test.tsx
git commit -m "Track mentions for comments and replies"
```

---

### Task 11: Debounced and Race-Safe Suggestion Hook

**Files:**
- Create: `client/src/components/CommentApp/components/MentionTextArea/useMentionSuggestions.ts`
- Create: `client/src/components/CommentApp/components/MentionTextArea/useMentionSuggestions.test.tsx`

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

Tests use fake timers and deferred fetch promises for: no URL/query; exactly 199/200 ms; clearing old results immediately; abort on changed query/close/unmount; older response resolving last; non-OK; invalid top-level/results/item shapes; empty list; composition suppression; close remaining closed until the query changes.

- [ ] **Step 2: Run and verify missing hook**

```bash
npm run test:unit -- --runInBand \
  client/src/components/CommentApp/components/MentionTextArea/useMentionSuggestions.test.tsx
```

Expected: FAIL because the hook does not exist.

- [ ] **Step 3: Implement the state machine**

Use a 200 ms default timer, one `AbortController` per request, and a monotonically increasing request ID checked before every state update. Parse only `id`/`label` strings and optional `username` string. A new query sets loading and clears results before the timer; `AbortError` never sets error.

- [ ] **Step 4: Verify the hook and commit**

```bash
npm run test:unit -- --runInBand \
  client/src/components/CommentApp/components/MentionTextArea/useMentionSuggestions.test.tsx
npm run lint:ts
git add client/src/components/CommentApp/components/MentionTextArea/useMentionSuggestions.ts client/src/components/CommentApp/components/MentionTextArea/useMentionSuggestions.test.tsx
git commit -m "Make mention suggestions race safe"
```

Expected: tests/typecheck PASS; commit contains only the hook and tests.

---

### Task 12: Accessible Native Textarea, Range Rendering, and Comment/Reply UI

**Files:**
- Rewrite: `client/src/components/CommentApp/components/MentionTextArea/index.tsx`
- Rewrite: `client/src/components/CommentApp/components/MentionTextArea/index.test.tsx`
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
- Consumes: Task 9 helpers, Task 10 state, Task 11 hook, existing native `TextArea`.
- Produces: keyboard/pointer/IME-safe mention editing and styled non-link display for comments and replies.

- [ ] **Step 1: Write failing native editor and renderer tests**

Use this component contract:

```typescript
export interface MentionTextAreaProps extends Omit<TextAreaProps, 'onChange'> {
  id: string;
  label: string;
  mentions: readonly MentionOccurrence[];
  mentionSuggestionsUrl?: string;
  onChange(value: string, mentions: MentionOccurrence[]): void;
}
```

Test native `<textarea>` presence and absence of `[contenteditable]`; typing Enter; multiline value; selected-range paste; emoji selection offsets; query recomputation on `select`; composition start/end; ArrowUp/Down wrap; Enter selection; Escape close with propagation stopped; Tab closes without preventDefault; pointer `mousedown` selection without blur; focus/caret restoration; loading/empty/error/ready status text; accessible name; `aria-autocomplete`, `aria-haspopup`, `aria-controls`, and active descendant; no `role=combobox`/`aria-expanded`.

Renderer tests cover plain/multiple/repeated ranges, duplicate labels, emoji/multiline, malformed range fallback, HTML-like escaping, and `<span class="comment__mention">` with no link.

- [ ] **Step 2: Run and verify the contenteditable implementation fails**

```bash
npm run test:unit -- --runInBand \
  client/src/components/CommentApp/components/MentionTextArea/index.test.tsx \
  client/src/components/CommentApp/components/MentionText/index.test.tsx
```

Expected: FAIL on native textarea, ARIA, status, range, and non-link assertions.

- [ ] **Step 3: Rewrite the editor around `TextArea`**

Keep one textarea ref. On native change, call `reconcileMentionOccurrences(oldValue, newValue, mentions)` and emit both values atomically. On select/key/pointer, recompute `findMentionQuery` from the textarea's current `selectionStart/End`. Selection calls `applyMentionSuggestion`, emits once, then uses `requestAnimationFrame` to restore focus/selection.

The textarea attributes are exactly:

```tsx
aria-autocomplete="list"
aria-haspopup="listbox"
aria-controls={listboxId}
aria-activedescendant={activeOptionId || undefined}
```

The popup uses `role="listbox"`; each item uses `role="option"` and `aria-selected`. Keep focus in the textarea. Use a localized `role="status" aria-live="polite"` region for loading, no matches, unavailable, and result-count messages.

- [ ] **Step 4: Integrate all comment and reply modes**

Comments use IDs `comment-mention-editor-${localId}` with localized labels `Add a comment` / `Edit comment`. New replies use `comment-new-reply-mention-editor-${comment.localId}` and `comment.newReplyMentions`; existing reply edits use `comment-reply-mention-editor-${comment.localId}-${reply.localId}` and `reply.newMentions`.

Save commits text and mentions together; cancel restores both; new-reply cancel clears both; display uses `MentionText` for comments and replies. Style selected options for normal and `@media (forced-colors: active)`, cap popup height with scrolling, and remove contenteditable placeholder/editor rules.

- [ ] **Step 5: Run complete CommentApp unit/style/type verification**

```bash
npm run test:unit -- --runInBand client/src/components/CommentApp
./node_modules/.bin/eslint --report-unused-disable-directives client/src/components/CommentApp
./node_modules/.bin/prettier --check client/src/components/CommentApp
./node_modules/.bin/stylelint "client/src/components/CommentApp/**/*.scss"
npm run lint:ts
```

Expected: all PASS and no snapshot/update warnings.

- [ ] **Step 6: Commit accessible comment/reply UI**

```bash
git add client/src/components/CommentApp
git commit -m "Add accessible comment and reply mention editing"
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

1. Open a comment through the first `[data-comment-add]` control.
2. Type multiline text with emoji and `@adm` into the create comment textarea.
3. Assert loading then populated status and run Axe with popup closed/loading/populated.
4. Select `admin` by ArrowDown/Enter and verify a hidden five-field occurrence.
5. Save the comment, save/autosave the page, follow the returned/hydrated edit URL, and assert the same text/range after reload.
6. Edit before/after/through the mention, asserting shifts/retention/drop and native selection replacement/paste.
7. Add, edit, cancel, save, reload, and remove a reply mention.
8. Query a guaranteed no-match string, assert empty status, and run Axe.
9. Press Tab with results open and assert focus moves instead of inserting.

Use `expect(page).toPassAxeTests({include: '.comment'})` for each named state and inspect the hidden inputs rather than private React state.

- [ ] **Step 2: Start the UI server and verify red state**

Prepare once:

```bash
npm --prefix client/tests/integration ci
npm --prefix client/tests/integration exec playwright install chromium
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

### Task 14: Primary-Branch Verification and Reviewer Artifact

**Files:**
- Modify only if verification finds defects: files owned by Tasks 2-13.
- Create during final evidence work: `docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md` in Task 15.
- Do not modify: `CHANGELOG.txt`, `docs/releases/8.0.md`, `CONTRIBUTORS.md`.

**Interfaces:**
- Consumes: complete primary implementation.
- Produces: green primary matrix and a PR body drafted from the final diff.

- [ ] **Step 1: Run the complete focused backend matrix**

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
)

python runtests.py -- "${BACKEND_TESTS[@]}"
USE_EMAIL_USER_MODEL=yes python runtests.py -- "${BACKEND_TESTS[@]}"

uvx --from 'tox>=4,<5' tox \
  -e py313-dj52-sqlite-noelasticsearch-customuser-tz -- "${BACKEND_TESTS[@]}"
uvx --from 'tox>=4,<5' tox \
  -e py313-dj60-sqlite-noelasticsearch-emailuser-tz -- "${BACKEND_TESTS[@]}"
```

Expected: all commands PASS.

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
DJANGO_SETTINGS_MODULE=wagtail.test.settings \
  python -m django makemigrations --check --dry-run
ruff format --check wagtail/admin wagtail/models/pages.py wagtail/migrations/0098_comment_mentions.py
ruff check wagtail/admin wagtail/models/pages.py wagtail/migrations/0098_comment_mentions.py
git diff --check "$OFFICIAL_MAIN"..HEAD
```

Rerun the Task 13 Chromium/Axe command. Run the same user path manually in current Firefox and record Firefox version, OS, keyboard, multiline, paste, emoji, reload, and popup-accessibility outcomes for the PR/compatibility report.

- [ ] **Step 4: Review the final primary diff and history**

```bash
git diff --name-status "$OFFICIAL_MAIN"..HEAD
git diff --stat "$OFFICIAL_MAIN"..HEAD
git log --oneline "$OFFICIAL_MAIN"..HEAD
git status --short --branch
```

Expected: only mention-related code/tests/design/plan files; no generated build output, caches, unrelated edits, release files, or uncommitted changes.

- [ ] **Step 5: Draft the PR description from the final diff**

Use `.github/PULL_REQUEST_TEMPLATE.md`. Include why ranges/native textarea/recipient merging are the right solution; call out UTF-16 validation, create-page recheck, DB-backed candidate filtering, notification overlap, and 7.4 evidence for careful review. Include suggested `CHANGELOG.txt`, `docs/releases/8.0.md`, and contributor wording for a core committer, but do not edit those files.

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
ROOT=/home/jt/dev/made-with-future/wagtail
COMPAT=/home/jt/dev/made-with-future/wagtail-compat-comment-mentions-7.4

git -C "$ROOT" fetch --no-tags https://github.com/wagtail/wagtail.git \
  +refs/heads/main:refs/remotes/upstream/main \
  +refs/heads/stable/7.4.x:refs/remotes/upstream/stable/7.4.x

OFFICIAL_MAIN=$(git -C "$ROOT" rev-parse refs/remotes/upstream/main)
OFFICIAL_STABLE=$(git -C "$ROOT" rev-parse refs/remotes/upstream/stable/7.4.x)
PRIMARY_BASE=$(git -C "$ROOT" merge-base "$OFFICIAL_MAIN" HEAD)

test ! -e "$COMPAT"
test -z "$(git -C "$ROOT" branch --list compat/comment-mentions-7.4)"
git -C "$ROOT" worktree add "$COMPAT" \
  -b compat/comment-mentions-7.4 "$OFFICIAL_STABLE"
```

Expected: clean compatibility branch at the recorded official 7.4 OID. On a resumed execution, reuse the existing retained worktree and assert it is clean; never reset/recreate it.

- [ ] **Step 2: Export the redesigned net runtime/test patch, excluding primary-only artifacts**

```bash
PRIMARY_HEAD=$(git -C "$ROOT" rev-parse HEAD)
PATCH=/tmp/comment-mentions-${PRIMARY_HEAD}.patch

git -C "$ROOT" diff --binary --full-index --no-renames \
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
git -C "$COMPAT" diff --check
git -C "$COMPAT" status --short
git -C "$COMPAT" add \
  wagtail client
git -C "$COMPAT" commit -m "Backport comment mentions to Wagtail 7.4"
COMPAT_HEAD=$(git -C "$COMPAT" rev-parse HEAD)
```

Expected: one retained local backport commit; frontend source is unchanged from the primary feature patch; intentional backend differences are limited to route registration and any recorded migration/test placement seam.

- [ ] **Step 4: Run the same backend/frontend/browser matrix on 7.4**

Run Task 14's `BACKEND_TESTS` under:

```bash
uvx --from 'tox>=4,<5' tox \
  -e py313-dj52-sqlite-noelasticsearch-customuser-tz -- "${BACKEND_TESTS[@]}"
uvx --from 'tox>=4,<5' tox \
  -e py313-dj60-sqlite-noelasticsearch-customuser-tz -- "${BACKEND_TESTS[@]}"
uvx --from 'tox>=4,<5' tox \
  -e py313-dj60-sqlite-noelasticsearch-emailuser-tz -- "${BACKEND_TESTS[@]}"
```

In the compatibility worktree also run Task 14's full frontend checks/build, migration check, Ruff commands, and Task 13's Chromium/Axe scenario against the 7.4 create/edit routes.

Expected: all PASS. Any frontend adaptation or non-declared backend adaptation is a primary design defect; correct the primary implementation, commit it, port the incremental diff, and rerun both matrices.

- [ ] **Step 5: Generate reproducible comparison evidence**

```bash
EVIDENCE=/tmp/wagtail-comment-mentions-compat
mkdir -p "$EVIDENCE"

git -C "$ROOT" diff --binary --full-index --no-renames \
  --output="$EVIDENCE/primary-runtime.patch" \
  "$PRIMARY_BASE" "$PRIMARY_HEAD" -- . \
  ':(exclude)docs/superpowers/**' \
  ':(exclude)CHANGELOG.txt' \
  ':(exclude)CONTRIBUTORS.md' \
  ':(exclude)docs/releases/**'

sha256sum "$EVIDENCE/primary-runtime.patch"
git range-diff --no-color \
  "$PRIMARY_BASE..$PRIMARY_HEAD" \
  "$OFFICIAL_STABLE..$COMPAT_HEAD"
git -C "$ROOT" diff --name-status "$PRIMARY_BASE" "$PRIMARY_HEAD"
git -C "$COMPAT" diff --name-status "$OFFICIAL_STABLE" "$COMPAT_HEAD"
git -C "$ROOT" diff --stat "$PRIMARY_BASE" "$PRIMARY_HEAD"
git -C "$COMPAT" diff --stat "$OFFICIAL_STABLE" "$COMPAT_HEAD"
git -C "$ROOT" diff --check "$PRIMARY_BASE" "$PRIMARY_HEAD"
git -C "$COMPAT" diff --check "$OFFICIAL_STABLE" "$COMPAT_HEAD"
```

`range-diff` is supplementary because the backport is one redesigned net commit. The authoritative report fields are base/head OIDs, patch checksum, full name/status and stat comparison, explicit adaptation table, and command results.

- [ ] **Step 6: Write and commit the compatibility report on primary**

The report contains these completed headings with literal values/output summaries, never placeholders:

```markdown
# Comment mentions: Wagtail 7.4 compatibility

## Recorded revisions
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
git add docs/superpowers/compatibility/2026-07-09-comment-mentions-7.4.md
git commit -m "Document Wagtail 7.4 mention compatibility"
```

- [ ] **Step 7: Final completion audit before publication**

Re-run `git status`, primary/compat OIDs, full required matrix evidence, changed-file/history lists, and the seven acceptance criteria in the design spec one by one. Confirm the compatibility branch remains local and retained. Only after user authorization: push the primary branch, rewrite PR 1 from the final diff/template, verify remote head/body/checks, and leave the PR draft until human review occurs.
