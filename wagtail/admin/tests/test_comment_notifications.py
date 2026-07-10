from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from wagtail.admin.comment_mentions import MentionChanges
from wagtail.admin.commenting import (
    CommentingChanges,
    MentionedMessage,
    collect_commenting_changes,
    log_commenting_changes,
)
from wagtail.models import Comment, CommentReply, Page

ADDED_KEY = "29cc6a1f-00ed-41d7-94b1-d46a947962cb"
REMOVED_KEY = "f4cf21fd-7dad-40e0-83da-d90310d2425f"


def mention_occurrence(*, key=ADDED_KEY, user_id="42", label="@user"):
    return {
        "key": key,
        "user_id": user_id,
        "start": 0,
        "end": len(label),
        "label": label,
    }


def reply_formset(
    *,
    forms=(),
    deleted_forms=(),
    new_objects=(),
    deleted_objects=(),
    changed_objects=(),
):
    return SimpleNamespace(
        forms=list(forms),
        deleted_forms=list(deleted_forms),
        new_objects=list(new_objects),
        deleted_objects=list(deleted_objects),
        changed_objects=list(changed_objects),
    )


def message_form(*, instance, changes=None, replies=None):
    form = mock.Mock()
    form.instance = instance
    form.mention_changes = changes or MentionChanges()
    form.formsets = {"replies": replies or reply_formset()}
    return form


class TrackingCommentFormSet:
    def __init__(
        self,
        *,
        forms=(),
        deleted_forms=(),
        new_objects=(),
        deleted_objects=(),
        changed_objects=(),
    ):
        self.forms = list(forms)
        self.deleted_forms = list(deleted_forms)
        self._values = {
            "new_objects": list(new_objects),
            "deleted_objects": list(deleted_objects),
            "changed_objects": list(changed_objects),
        }
        self.attribute_reads = dict.fromkeys(self._values, 0)

    def _read(self, name):
        self.attribute_reads[name] += 1
        return self._values[name]

    @property
    def new_objects(self):
        return self._read("new_objects")

    @property
    def deleted_objects(self):
        return self._read("deleted_objects")

    @property
    def changed_objects(self):
        return self._read("changed_objects")


class TestCommentingChanges(TestCase):
    def test_collects_changes_in_formset_order_without_queries(self):
        shared_key = ADDED_KEY
        first_comment_changes = MentionChanges(
            added=(mention_occurrence(key=shared_key, user_id="42"),)
        )
        first_reply_changes = MentionChanges(
            removed=(
                mention_occurrence(key=REMOVED_KEY, user_id="17", label="@former"),
            )
        )
        second_comment_changes = MentionChanges(
            removed=(mention_occurrence(key=REMOVED_KEY, user_id="23"),)
        )
        second_reply_changes = MentionChanges(
            added=(mention_occurrence(key=shared_key, user_id="84"),)
        )

        first_comment = Comment(pk=1, text="first")
        second_comment = Comment(pk=2, text="second", resolved_at=mock.sentinel.time)
        new_comment = Comment(pk=3, text="new")
        deleted_comment = Comment(pk=4, text="deleted")
        first_reply = CommentReply(pk=11, comment=first_comment, text="first reply")
        second_reply = CommentReply(pk=12, comment=second_comment, text="second reply")
        new_reply = CommentReply(pk=13, comment=first_comment, text="new reply")
        deleted_reply = CommentReply(
            pk=14, comment=second_comment, text="deleted reply"
        )

        first_reply_form = message_form(
            instance=first_reply, changes=first_reply_changes
        )
        second_reply_form = message_form(
            instance=second_reply, changes=second_reply_changes
        )
        first_comment_form = message_form(
            instance=first_comment,
            changes=first_comment_changes,
            replies=reply_formset(
                forms=[first_reply_form],
                new_objects=[new_reply],
                changed_objects=[(first_reply, ["mentions"])],
            ),
        )
        second_comment_form = message_form(
            instance=second_comment,
            changes=second_comment_changes,
            replies=reply_formset(
                forms=[second_reply_form],
                deleted_objects=[deleted_reply],
                changed_objects=[(second_reply, ["text"])],
            ),
        )
        formset = TrackingCommentFormSet(
            forms=[first_comment_form, second_comment_form],
            new_objects=[new_comment],
            deleted_objects=[deleted_comment],
            changed_objects=[
                (first_comment, ["mentions"]),
                (second_comment, ["resolved", "text"]),
            ],
        )

        with self.assertNumQueries(0):
            changes = collect_commenting_changes(formset)

        self.assertEqual(
            formset.attribute_reads,
            {"new_objects": 1, "deleted_objects": 1, "changed_objects": 1},
        )
        self.assertEqual(changes.new_comments, [new_comment])
        self.assertEqual(changes.deleted_comments, [deleted_comment])
        self.assertEqual(changes.resolved_comments, [second_comment])
        self.assertEqual(changes.edited_comments, [first_comment, second_comment])
        self.assertEqual(changes.new_replies, [(first_comment, [new_reply])])
        self.assertEqual(changes.deleted_replies, [(second_comment, [deleted_reply])])
        self.assertEqual(
            changes.edited_replies,
            [(first_comment, [first_reply]), (second_comment, [second_reply])],
        )
        self.assertEqual(len(changes.mentions), 4)
        self.assertIs(changes.mentions[0].comment, first_comment)
        self.assertIsNone(changes.mentions[0].reply)
        self.assertIs(changes.mentions[0].changes, first_comment_changes)
        self.assertIs(changes.mentions[1].comment, first_comment)
        self.assertIs(changes.mentions[1].reply, first_reply)
        self.assertIs(changes.mentions[1].changes, first_reply_changes)
        self.assertIs(changes.mentions[2].comment, second_comment)
        self.assertIsNone(changes.mentions[2].reply)
        self.assertIs(changes.mentions[2].changes, second_comment_changes)
        self.assertIs(changes.mentions[3].comment, second_comment)
        self.assertIs(changes.mentions[3].reply, second_reply)
        self.assertIs(changes.mentions[3].changes, second_reply_changes)
        self.assertEqual(
            changes.mentions[0].changes.added[0]["key"],
            changes.mentions[3].changes.added[0]["key"],
        )

    def test_deleted_parent_and_reply_forms_do_not_contribute_mentions(self):
        changes = MentionChanges(added=(mention_occurrence(),))
        deleted_comment = Comment(pk=1, text="deleted")
        deleted_parent_reply = CommentReply(
            pk=11, comment=deleted_comment, text="deleted with parent"
        )
        deleted_parent_reply_form = message_form(
            instance=deleted_parent_reply, changes=changes
        )
        deleted_comment_form = message_form(
            instance=deleted_comment,
            changes=changes,
            replies=reply_formset(forms=[deleted_parent_reply_form]),
        )

        live_comment = Comment(pk=2, text="live")
        deleted_reply = CommentReply(pk=12, comment=live_comment, text="deleted")
        deleted_reply_form = message_form(instance=deleted_reply, changes=changes)
        live_comment_form = message_form(
            instance=live_comment,
            replies=reply_formset(
                forms=[deleted_reply_form], deleted_forms=[deleted_reply_form]
            ),
        )
        formset = TrackingCommentFormSet(
            forms=[deleted_comment_form, live_comment_form],
            deleted_forms=[deleted_comment_form],
        )

        collected = collect_commenting_changes(formset)

        self.assertEqual(collected.mentions, [])


def empty_changes(**overrides):
    values = {
        "new_comments": [],
        "deleted_comments": [],
        "resolved_comments": [],
        "edited_comments": [],
        "new_replies": [],
        "deleted_replies": [],
        "edited_replies": [],
        "mentions": [],
    }
    values.update(overrides)
    return CommentingChanges(**values)


class TestMentionAuditData(TestCase):
    def setUp(self):
        self.page = Page(pk=1, title="Page", slug="page")
        self.comment = Comment(
            pk=7, page=self.page, contentpath="title", text="Comment"
        )
        self.reply = CommentReply(pk=8, comment=self.comment, text="Reply")
        self.mention_changes = MentionChanges(
            added=(mention_occurrence(key=ADDED_KEY, user_id=42),),
            removed=(
                mention_occurrence(
                    key=REMOVED_KEY, user_id="17", label="@old@example.com"
                ),
            ),
        )
        self.expected_audit_delta = {
            "added": [{"key": ADDED_KEY, "user_id": "42"}],
            "removed": [{"key": REMOVED_KEY, "user_id": "17"}],
        }

    def test_comment_and_reply_logs_include_only_stable_mention_data(self):
        with mock.patch("wagtail.models.pages.log") as log:
            self.comment.log_edit(mention_changes=self.mention_changes)
            self.reply.log_edit(mention_changes=self.mention_changes)

        self.assertEqual(log.call_count, 2)
        comment_data = log.call_args_list[0].kwargs["data"]
        reply_data = log.call_args_list[1].kwargs["data"]
        self.assertEqual(comment_data["mentions"], self.expected_audit_delta)
        self.assertEqual(reply_data["mentions"], self.expected_audit_delta)
        self.assertEqual(set(comment_data["mentions"]["added"][0]), {"key", "user_id"})
        self.assertEqual(
            set(comment_data["mentions"]["removed"][0]), {"key", "user_id"}
        )

    def test_logs_without_mention_changes_keep_the_existing_payload(self):
        with mock.patch("wagtail.models.pages.log") as log:
            self.comment.log_edit()
            self.reply.log_edit(mention_changes=MentionChanges())

        self.assertNotIn("mentions", log.call_args_list[0].kwargs["data"])
        self.assertNotIn("mentions", log.call_args_list[1].kwargs["data"])

    def test_dispatcher_matches_mention_changes_by_message_identity(self):
        equal_comment = Comment(
            pk=self.comment.pk,
            page=self.page,
            contentpath="title",
            text="Equal but distinct",
        )
        equal_reply = CommentReply(
            pk=self.reply.pk,
            comment=self.comment,
            text="Equal but distinct",
        )
        changes = empty_changes(
            edited_comments=[equal_comment, self.comment],
            edited_replies=[(self.comment, [equal_reply, self.reply])],
            mentions=[
                MentionedMessage(
                    comment=self.comment,
                    reply=None,
                    changes=self.mention_changes,
                ),
                MentionedMessage(
                    comment=self.comment,
                    reply=self.reply,
                    changes=self.mention_changes,
                ),
            ],
        )

        with mock.patch("wagtail.models.pages.log") as log:
            log_commenting_changes(
                changes=changes,
                revision=mock.sentinel.revision,
                actor=mock.sentinel.actor,
            )

        self.assertEqual(log.call_count, 4)
        self.assertNotIn("mentions", log.call_args_list[0].kwargs["data"])
        self.assertEqual(
            log.call_args_list[1].kwargs["data"]["mentions"],
            self.expected_audit_delta,
        )
        self.assertNotIn("mentions", log.call_args_list[2].kwargs["data"])
        self.assertEqual(
            log.call_args_list[3].kwargs["data"]["mentions"],
            self.expected_audit_delta,
        )

    def test_dispatcher_attaches_mention_changes_to_create_actions(self):
        changes = empty_changes(
            new_comments=[self.comment],
            new_replies=[(self.comment, [self.reply])],
            mentions=[
                MentionedMessage(
                    comment=self.comment,
                    reply=None,
                    changes=self.mention_changes,
                ),
                MentionedMessage(
                    comment=self.comment,
                    reply=self.reply,
                    changes=self.mention_changes,
                ),
            ],
        )

        with mock.patch("wagtail.models.pages.log") as log:
            log_commenting_changes(
                changes=changes,
                revision=mock.sentinel.revision,
                actor=mock.sentinel.actor,
            )

        self.assertEqual(
            [call.kwargs["action"] for call in log.call_args_list],
            ["wagtail.comments.create", "wagtail.comments.create_reply"],
        )
        self.assertEqual(
            log.call_args_list[0].kwargs["data"]["mentions"],
            self.expected_audit_delta,
        )
        self.assertEqual(
            log.call_args_list[1].kwargs["data"]["mentions"],
            self.expected_audit_delta,
        )
