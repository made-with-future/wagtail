from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import transaction
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from wagtail.admin.comment_mentions import MentionChanges
from wagtail.admin.comment_notifications import (
    RecipientPayload,
    build_recipient_payloads,
    group_identical_payloads,
    schedule_comment_notifications,
)
from wagtail.admin.commenting import (
    CommentingChanges,
    MentionedMessage,
    collect_commenting_changes,
    log_commenting_changes,
)
from wagtail.models import (
    Comment,
    CommentMention,
    CommentReply,
    CommentReplyMention,
    Page,
    PageSubscription,
)
from wagtail.test.utils import WagtailTestUtils
from wagtail.users.models import UserProfile

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


class CommentNotificationTestCase(WagtailTestUtils, TestCase):
    def setUp(self):
        self.page = Page(title="Notification page", slug="notification-page")
        Page.get_first_root_node().add_child(instance=self.page)
        self.editor = self.create_user(
            "editor",
            email="editor@example.com",
            first_name="Editor",
            last_name="Person",
        )

    def create_notification_user(self, username, **kwargs):
        kwargs.setdefault("email", f"{username}@example.com")
        kwargs.setdefault("first_name", username.title())
        kwargs.setdefault("last_name", "Person")
        return self.create_user(username, **kwargs)

    def create_comment(self, text, *, user=None):
        return Comment.objects.create(
            page=self.page,
            user=user or self.editor,
            contentpath="title",
            text=text,
        )

    def create_reply(self, comment, text, *, user=None):
        return CommentReply.objects.create(
            comment=comment,
            user=user or self.editor,
            text=text,
        )

    def mentioned_message(
        self,
        *,
        comment,
        user,
        reply=None,
        key=ADDED_KEY,
        user_id=None,
        added=None,
        removed=(),
    ):
        if added is None:
            added = (
                mention_occurrence(
                    key=key,
                    user_id=str(user.pk) if user_id is None else user_id,
                ),
            )
        return MentionedMessage(
            comment=comment,
            reply=reply,
            changes=MentionChanges(added=added, removed=removed),
        )


class TestRecipientPayloads(CommentNotificationTestCase):
    def test_subscription_change_and_direct_mention_are_merged_per_recipient(self):
        mentioned_subscriber = self.create_notification_user("mentioned-subscriber")
        PageSubscription.objects.create(
            page=self.page,
            user=mentioned_subscriber,
            comment_notifications=True,
        )
        comment_a = self.create_comment("An ordinary new comment")
        comment_b = self.create_comment("Please review this section")
        changes = empty_changes(
            new_comments=[comment_a, comment_b],
            mentions=[
                self.mentioned_message(comment=comment_b, user=mentioned_subscriber)
            ],
        )

        payloads = build_recipient_payloads(
            page=self.page,
            editor=self.editor,
            changes=changes,
        )

        payload = payloads[mentioned_subscriber.pk]
        self.assertEqual(payload.mentioned_comments, [comment_b])
        self.assertEqual(payload.new_comments, [comment_a])
        self.assertNotIn(comment_b, payload.new_comments)
        self.assertTrue(payload.has_mentions)

    def test_subscriber_thread_and_direct_reasons_merge_without_duplicates(self):
        recipient = self.create_notification_user("overlap")
        PageSubscription.objects.create(
            page=self.page,
            user=recipient,
            comment_notifications=True,
        )
        new_comment = self.create_comment("New")
        thread = self.create_comment("Existing thread", user=recipient)
        new_reply = self.create_reply(thread, "Thread reply")
        mentioned_comment = self.create_comment("Mentioned")
        changes = empty_changes(
            new_comments=[new_comment],
            resolved_comments=[thread],
            new_replies=[(thread, [new_reply])],
            mentions=[
                self.mentioned_message(comment=mentioned_comment, user=recipient)
            ],
        )

        payloads = build_recipient_payloads(
            page=self.page,
            editor=self.editor,
            changes=changes,
        )

        self.assertEqual(list(payloads), [recipient.pk])
        payload = payloads[recipient.pk]
        self.assertEqual(payload.new_comments, [new_comment])
        self.assertEqual(payload.resolved_comments, [thread])
        self.assertEqual(
            payload.replied_comments,
            [{"comment": thread, "replies": [new_reply]}],
        )
        self.assertEqual(payload.mentioned_comments, [mentioned_comment])

    def test_actor_is_excluded_by_canonical_primary_key_from_every_reason(self):
        PageSubscription.objects.create(
            page=self.page,
            user=self.editor,
            comment_notifications=True,
        )
        thread = self.create_comment("Editor's thread", user=self.editor)
        reply = self.create_reply(thread, "New reply")
        pk_field = get_user_model()._meta.pk
        prepared_editor_id = str(pk_field.get_prep_value(self.editor.pk))
        changes = empty_changes(
            new_comments=[thread],
            resolved_comments=[thread],
            new_replies=[(thread, [reply])],
            mentions=[
                self.mentioned_message(
                    comment=thread,
                    user=self.editor,
                    user_id=prepared_editor_id,
                )
            ],
        )

        payloads = build_recipient_payloads(
            page=self.page,
            editor=self.editor,
            changes=changes,
        )

        self.assertNotIn(self.editor.pk, payloads)
        self.assertEqual(payloads, {})

    def test_direct_mention_ignores_page_subscription_opt_out(self):
        recipient = self.create_notification_user("direct")
        PageSubscription.objects.create(
            page=self.page,
            user=recipient,
            comment_notifications=False,
        )
        comment = self.create_comment("Direct mention")

        payloads = build_recipient_payloads(
            page=self.page,
            editor=self.editor,
            changes=empty_changes(
                mentions=[self.mentioned_message(comment=comment, user=recipient)]
            ),
        )

        self.assertEqual(payloads[recipient.pk].mentioned_comments, [comment])

    def test_all_direct_targets_are_resolved_in_one_active_user_query(self):
        first = self.create_notification_user("first-target")
        second = self.create_notification_user("second-target")
        comment = self.create_comment("Several targets")
        added = (
            mention_occurrence(user_id=str(first.pk)),
            mention_occurrence(key=REMOVED_KEY, user_id=str(second.pk)),
        )
        changes = empty_changes(
            mentions=[
                self.mentioned_message(
                    comment=comment,
                    user=first,
                    added=added,
                )
            ]
        )
        user_table = get_user_model()._meta.db_table

        with CaptureQueriesContext(transaction.get_connection()) as queries:
            payloads = build_recipient_payloads(
                page=self.page,
                editor=self.editor,
                changes=changes,
            )

        direct_user_queries = [
            query["sql"] for query in queries if f'FROM "{user_table}"' in query["sql"]
        ]
        self.assertEqual(len(direct_user_queries), 1)
        self.assertEqual(set(payloads), {first.pk, second.pk})

    def test_direct_target_lookup_uses_the_default_user_manager(self):
        recipient = self.create_notification_user("default-manager")
        comment = self.create_comment("Default manager target")
        changes = empty_changes(
            mentions=[self.mentioned_message(comment=comment, user=recipient)]
        )
        user_model = get_user_model()

        with mock.patch.object(user_model, "objects", new=mock.Mock()):
            payloads = build_recipient_payloads(
                page=self.page,
                editor=self.editor,
                changes=changes,
            )

        self.assertEqual(payloads[recipient.pk].mentioned_comments, [comment])

    def test_prepared_and_display_user_ids_resolve_to_the_same_recipient(self):
        recipient = self.create_notification_user("alias-target")
        comment = self.create_comment("Aliased target")
        pk_field = get_user_model()._meta.pk
        display_id = str(recipient.pk)
        prepared_id = str(pk_field.get_prep_value(recipient.pk))
        if display_id == prepared_id:
            self.skipTest("User PK has no distinct prepared/display alias")
        added = (
            mention_occurrence(user_id=display_id),
            mention_occurrence(key=REMOVED_KEY, user_id=prepared_id),
        )

        payloads = build_recipient_payloads(
            page=self.page,
            editor=self.editor,
            changes=empty_changes(
                mentions=[
                    self.mentioned_message(
                        comment=comment,
                        user=recipient,
                        added=added,
                    )
                ]
            ),
        )

        self.assertEqual(list(payloads), [recipient.pk])
        self.assertEqual(payloads[recipient.pk].mentioned_comments, [comment])

    def test_inactive_and_deleted_direct_targets_are_not_planned(self):
        inactive = self.create_notification_user("inactive")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        deleted = self.create_notification_user("deleted")
        deleted_id = str(deleted.pk)
        deleted.delete()
        comment = self.create_comment("Unavailable targets")
        added = (
            mention_occurrence(user_id=str(inactive.pk)),
            mention_occurrence(key=REMOVED_KEY, user_id=deleted_id),
        )

        payloads = build_recipient_payloads(
            page=self.page,
            editor=self.editor,
            changes=empty_changes(
                mentions=[
                    self.mentioned_message(
                        comment=comment,
                        user=inactive,
                        added=added,
                    )
                ]
            ),
        )

        self.assertEqual(payloads, {})

    def test_thread_participants_receive_only_affected_thread_sections(self):
        global_subscriber = self.create_notification_user("global")
        first_participant = self.create_notification_user("first-participant")
        second_participant = self.create_notification_user("second-participant")
        PageSubscription.objects.create(
            page=self.page,
            user=global_subscriber,
            comment_notifications=True,
        )
        first_thread = self.create_comment("First thread", user=first_participant)
        second_thread = self.create_comment("Second thread")
        self.create_reply(
            second_thread,
            "Existing participant reply",
            user=second_participant,
        )
        unrelated_new = self.create_comment("Global new comment")
        deleted = Comment(
            page=self.page,
            user=self.editor,
            contentpath="title",
            text="Deleted global comment",
        )
        first_reply = self.create_reply(first_thread, "First new reply")
        second_reply = self.create_reply(second_thread, "Second new reply")
        changes = empty_changes(
            new_comments=[unrelated_new],
            resolved_comments=[first_thread, second_thread],
            deleted_comments=[deleted],
            new_replies=[
                (first_thread, [first_reply]),
                (second_thread, [second_reply]),
            ],
        )

        payloads = build_recipient_payloads(
            page=self.page,
            editor=self.editor,
            changes=changes,
        )

        global_payload = payloads[global_subscriber.pk]
        self.assertEqual(global_payload.new_comments, [unrelated_new])
        self.assertEqual(
            global_payload.resolved_comments,
            [first_thread, second_thread],
        )
        self.assertEqual(global_payload.deleted_comments, [deleted])
        self.assertEqual(
            global_payload.replied_comments,
            [
                {"comment": first_thread, "replies": [first_reply]},
                {"comment": second_thread, "replies": [second_reply]},
            ],
        )

        first_payload = payloads[first_participant.pk]
        self.assertEqual(first_payload.new_comments, [])
        self.assertEqual(first_payload.resolved_comments, [first_thread])
        self.assertEqual(first_payload.deleted_comments, [])
        self.assertEqual(
            first_payload.replied_comments,
            [{"comment": first_thread, "replies": [first_reply]}],
        )

        second_payload = payloads[second_participant.pk]
        self.assertEqual(second_payload.new_comments, [])
        self.assertEqual(second_payload.resolved_comments, [second_thread])
        self.assertEqual(second_payload.deleted_comments, [])
        self.assertEqual(
            second_payload.replied_comments,
            [{"comment": second_thread, "replies": [second_reply]}],
        )

    def test_occurrences_dedupe_per_message_without_cross_message_keys(self):
        recipient = self.create_notification_user("multi-mention")
        first_comment = self.create_comment("First mention")
        second_comment = self.create_comment("Second mention")
        reply = self.create_reply(second_comment, "Mentioned reply")
        repeated = (
            mention_occurrence(user_id=str(recipient.pk)),
            mention_occurrence(key=REMOVED_KEY, user_id=str(recipient.pk)),
        )
        changes = empty_changes(
            mentions=[
                self.mentioned_message(
                    comment=first_comment,
                    user=recipient,
                    added=repeated,
                ),
                self.mentioned_message(
                    comment=second_comment,
                    user=recipient,
                    key=ADDED_KEY,
                ),
                self.mentioned_message(
                    comment=second_comment,
                    reply=reply,
                    user=recipient,
                    key=ADDED_KEY,
                ),
            ]
        )

        payload = build_recipient_payloads(
            page=self.page,
            editor=self.editor,
            changes=changes,
        )[recipient.pk]

        self.assertEqual(
            payload.mentioned_comments,
            [first_comment, second_comment],
        )
        self.assertEqual(
            payload.mentioned_replies,
            [{"comment": second_comment, "reply": reply}],
        )

    def test_exact_reply_pruning_preserves_other_replies_and_recipient_isolation(self):
        mentioned = self.create_notification_user("mentioned")
        ordinary = self.create_notification_user("ordinary")
        for user in (mentioned, ordinary):
            PageSubscription.objects.create(
                page=self.page,
                user=user,
                comment_notifications=True,
            )
        thread = self.create_comment("Thread")
        mentioned_reply = self.create_reply(thread, "Mentioned reply")
        ordinary_reply = self.create_reply(thread, "Ordinary reply")
        changes = empty_changes(
            new_replies=[(thread, [mentioned_reply, ordinary_reply])],
            mentions=[
                self.mentioned_message(
                    comment=thread,
                    reply=mentioned_reply,
                    user=mentioned,
                )
            ],
        )

        payloads = build_recipient_payloads(
            page=self.page,
            editor=self.editor,
            changes=changes,
        )

        mentioned_payload = payloads[mentioned.pk]
        ordinary_payload = payloads[ordinary.pk]
        self.assertEqual(
            mentioned_payload.replied_comments,
            [{"comment": thread, "replies": [ordinary_reply]}],
        )
        self.assertEqual(
            mentioned_payload.mentioned_replies,
            [{"comment": thread, "reply": mentioned_reply}],
        )
        self.assertEqual(
            ordinary_payload.replied_comments,
            [{"comment": thread, "replies": [mentioned_reply, ordinary_reply]}],
        )
        self.assertIsNot(
            mentioned_payload.replied_comments,
            ordinary_payload.replied_comments,
        )
        for attribute in (
            "new_comments",
            "resolved_comments",
            "deleted_comments",
            "replied_comments",
            "mentioned_comments",
            "mentioned_replies",
        ):
            self.assertIsNot(
                getattr(mentioned_payload, attribute),
                getattr(ordinary_payload, attribute),
            )
        self.assertIsNot(
            mentioned_payload.replied_comments[0]["replies"],
            ordinary_payload.replied_comments[0]["replies"],
        )
        mentioned_payload.replied_comments[0]["replies"].clear()
        self.assertEqual(
            ordinary_payload.replied_comments[0]["replies"],
            [mentioned_reply, ordinary_reply],
        )

    def test_lookup_rows_do_not_suppress_or_create_mention_novelty(self):
        recipient = self.create_notification_user("lookup-target")
        comment = self.create_comment("Comment lookup")
        reply = self.create_reply(comment, "Reply lookup")
        CommentMention.objects.create(comment=comment, user=recipient)
        CommentReplyMention.objects.create(reply=reply, user=recipient)
        with_added_occurrences = empty_changes(
            mentions=[
                self.mentioned_message(comment=comment, user=recipient),
                self.mentioned_message(
                    comment=comment,
                    reply=reply,
                    user=recipient,
                    key=REMOVED_KEY,
                ),
            ]
        )

        payload = build_recipient_payloads(
            page=self.page,
            editor=self.editor,
            changes=with_added_occurrences,
        )[recipient.pk]

        self.assertEqual(payload.mentioned_comments, [comment])
        self.assertEqual(
            payload.mentioned_replies,
            [{"comment": comment, "reply": reply}],
        )

        lookup_only = empty_changes(
            mentions=[
                self.mentioned_message(
                    comment=comment,
                    user=recipient,
                    added=(),
                    removed=(mention_occurrence(user_id=str(recipient.pk)),),
                )
            ]
        )
        self.assertEqual(
            build_recipient_payloads(
                page=self.page,
                editor=self.editor,
                changes=lookup_only,
            ),
            {},
        )


class TestPayloadGrouping(CommentNotificationTestCase):
    def test_identical_payloads_group_without_recipient_context(self):
        first = self.create_notification_user("first")
        second = self.create_notification_user("second")
        comment = self.create_comment("Same context")
        first_payload = RecipientPayload(first, new_comments=[comment])
        second_payload = RecipientPayload(second, new_comments=[comment])

        groups = group_identical_payloads(
            {first.pk: first_payload, second.pk: second_payload}
        )

        self.assertEqual(len(groups), 1)
        users, context = groups[0]
        self.assertEqual(users, [first, second])
        self.assertNotIn("user", context)
        self.assertEqual(context["new_comments"], [comment])
        self.assertIsNot(context["new_comments"], first_payload.new_comments)

    def test_message_identity_prevents_grouping_collisions(self):
        users = [
            self.create_notification_user(f"identity-{index}") for index in range(6)
        ]
        first_saved = self.create_comment("Same text")
        second_saved = self.create_comment("Same text")
        same_pk_reply = CommentReply(
            pk=first_saved.pk,
            comment=first_saved,
            user=self.editor,
            text=first_saved.text,
        )
        first_unsaved = Comment(
            page=self.page,
            user=self.editor,
            contentpath="title",
            text="Deleted",
        )
        second_unsaved = Comment(
            page=self.page,
            user=self.editor,
            contentpath="title",
            text="Deleted",
        )
        payloads = {
            users[0].pk: RecipientPayload(users[0], new_comments=[first_saved]),
            users[1].pk: RecipientPayload(users[1], new_comments=[same_pk_reply]),
            users[2].pk: RecipientPayload(users[2], new_comments=[second_saved]),
            users[3].pk: RecipientPayload(users[3], deleted_comments=[first_unsaved]),
            users[4].pk: RecipientPayload(users[4], deleted_comments=[second_unsaved]),
            users[5].pk: RecipientPayload(
                users[5],
                replied_comments=[{"comment": first_saved, "replies": [same_pk_reply]}],
            ),
        }

        groups = group_identical_payloads(payloads)

        self.assertEqual(len(groups), len(payloads))

    def test_reply_nesting_is_part_of_the_group_signature(self):
        first = self.create_notification_user("nested-first")
        second = self.create_notification_user("nested-second")
        thread = self.create_comment("Thread")
        first_reply = self.create_reply(thread, "First")
        second_reply = self.create_reply(thread, "Second")
        payloads = {
            first.pk: RecipientPayload(
                first,
                replied_comments=[
                    {"comment": thread, "replies": [first_reply, second_reply]}
                ],
            ),
            second.pk: RecipientPayload(
                second,
                replied_comments=[
                    {"comment": thread, "replies": [second_reply, first_reply]}
                ],
            ),
        }

        self.assertEqual(len(group_identical_payloads(payloads)), 2)


class TestCommentNotificationScheduling(CommentNotificationTestCase):
    def test_delivery_waits_for_transaction_commit(self):
        recipient = self.create_notification_user("commit-recipient")
        PageSubscription.objects.create(
            page=self.page,
            user=recipient,
            comment_notifications=True,
        )
        comment = self.create_comment("Committed comment")

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            schedule_comment_notifications(
                page=self.page,
                editor=self.editor,
                changes=empty_changes(new_comments=[comment]),
            )
            self.assertEqual(callbacks, [])
            self.assertEqual(mail.outbox, [])

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [recipient.email])

    def test_rolled_back_inner_transaction_discards_delivery(self):
        recipient = self.create_notification_user("rollback-recipient")
        PageSubscription.objects.create(
            page=self.page,
            user=recipient,
            comment_notifications=True,
        )
        comment = self.create_comment("Rolled back comment")

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with transaction.atomic():
                schedule_comment_notifications(
                    page=self.page,
                    editor=self.editor,
                    changes=empty_changes(new_comments=[comment]),
                )
                transaction.set_rollback(True)
            self.assertEqual(mail.outbox, [])

        self.assertEqual(callbacks, [])
        self.assertEqual(mail.outbox, [])

    def test_empty_payloads_do_not_register_a_callback(self):
        edited = self.create_comment("Edited only")

        with mock.patch(
            "wagtail.admin.comment_notifications.transaction.on_commit"
        ) as on_commit:
            schedule_comment_notifications(
                page=self.page,
                editor=self.editor,
                changes=empty_changes(edited_comments=[edited]),
            )

        on_commit.assert_not_called()

    def test_profile_opt_out_and_missing_email_are_filtered_at_send_time(self):
        opted_out = self.create_notification_user("opted-out")
        no_email = self.create_notification_user("no-email")
        no_email.email = ""
        no_email.save(update_fields=["email"])
        profile = UserProfile.get_for_user(opted_out)
        profile.updated_comments_notifications = False
        profile.save(update_fields=["updated_comments_notifications"])
        comment = self.create_comment("Filtered direct mentions")
        changes = empty_changes(
            mentions=[
                self.mentioned_message(comment=comment, user=opted_out),
                self.mentioned_message(
                    comment=comment,
                    user=no_email,
                    key=REMOVED_KEY,
                ),
            ]
        )

        payloads = build_recipient_payloads(
            page=self.page,
            editor=self.editor,
            changes=changes,
        )
        self.assertEqual(set(payloads), {opted_out.pk, no_email.pk})

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            schedule_comment_notifications(
                page=self.page,
                editor=self.editor,
                changes=changes,
            )

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(mail.outbox, [])

    def test_failed_send_is_logged_and_does_not_stop_later_recipients(self):
        recipients = [
            self.create_notification_user("failure-first"),
            self.create_notification_user("failure-second"),
        ]
        for recipient in recipients:
            PageSubscription.objects.create(
                page=self.page,
                user=recipient,
                comment_notifications=True,
            )
        comment = self.create_comment("Failure isolation")
        attempts = []

        def fail_first_send(subject, message, recipient_list, **kwargs):
            attempts.append(recipient_list)
            if len(attempts) == 1:
                raise RuntimeError("mail transport failed")
            return 1

        with mock.patch(
            "wagtail.admin.mail.send_mail", side_effect=fail_first_send
        ) as send_mail:
            with self.assertLogs("wagtail.admin", level="ERROR") as logs:
                with self.captureOnCommitCallbacks(execute=True):
                    schedule_comment_notifications(
                        page=self.page,
                        editor=self.editor,
                        changes=empty_changes(new_comments=[comment]),
                    )

        self.assertEqual(send_mail.call_count, 2)
        self.assertEqual(attempts, [[recipients[0].email], [recipients[1].email]])
        self.assertIn("Failed to send notification email", "\n".join(logs.output))

    @override_settings(WAGTAILADMIN_NOTIFICATION_USE_HTML=True)
    def test_html_alternative_is_sent_for_mentions(self):
        recipient = self.create_notification_user("html-recipient")
        comment = self.create_comment('Please review <script> & "quotes"')
        changes = empty_changes(
            mentions=[self.mentioned_message(comment=comment, user=recipient)]
        )

        with self.captureOnCommitCallbacks(execute=True):
            schedule_comment_notifications(
                page=self.page,
                editor=self.editor,
                changes=changes,
            )

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(
            message.subject,
            'Editor Person mentioned you in comments on "Notification page"',
        )
        self.assertEqual(len(message.alternatives), 1)
        alternative = message.alternatives[0]
        self.assertEqual(alternative.mimetype, "text/html")
        self.assertIn(
            "Please review &lt;script&gt; &amp; &quot;quotes&quot;",
            alternative.content,
        )
        self.assertNotIn("Please review <script>", alternative.content)


class TestCommentNotificationTemplates(CommentNotificationTestCase):
    def setUp(self):
        super().setUp()
        self.recipient = self.create_notification_user("mentioned")
        self.comment = self.create_comment("Please review this section")
        self.reply = self.create_reply(self.comment, "I have updated it")

    def template_context(self, **overrides):
        context = {
            "page": self.page,
            "editor": self.editor,
            "user": self.recipient,
            "new_comments": [],
            "resolved_comments": [],
            "deleted_comments": [],
            "replied_comments": [],
            "mentioned_comments": [self.comment],
            "mentioned_replies": [{"comment": self.comment, "reply": self.reply}],
        }
        context.update(overrides)
        return context

    def test_plain_text_mention_copy_is_exact(self):
        context = self.template_context(
            new_comments=[self.create_comment("Another new comment")],
            resolved_comments=[self.create_comment("A resolved comment")],
            deleted_comments=[
                Comment(
                    page=self.page,
                    user=self.editor,
                    contentpath="title",
                    text="A deleted comment",
                )
            ],
            replied_comments=[
                {
                    "comment": self.comment,
                    "replies": [self.create_reply(self.comment, "Another reply")],
                }
            ],
        )

        subject = render_to_string(
            "wagtailadmin/notifications/updated_comments_subject.txt",
            context,
        ).strip()
        body = render_to_string(
            "wagtailadmin/notifications/updated_comments.txt",
            context,
        ).strip()

        self.assertEqual(
            subject,
            'Editor Person mentioned you in comments on "Notification page"',
        )
        self.assertEqual(
            body,
            "Hello Mentioned,\n\n"
            'Editor Person mentioned you in comments on "Notification page".\n\n\n'
            "Mentions:\n"
            ' - Comment: "Please review this section"\n'
            ' - Reply to "Please review this section": "I have updated it"\n\n\n'
            "New comments:\n"
            ' - "Another new comment"\n\n\n'
            "Resolved comments:\n"
            ' - "A resolved comment"\n\n\n'
            "Deleted comments:\n"
            ' - "A deleted comment"\n\n\n'
            "New replies:\n\n"
            '  New replies to: "Please review this section"\n'
            '   - "Another reply"\n\n'
            f"You can edit the page here: http://testserver/admin/pages/{self.page.pk}/edit/\n\n\n"
            "Edit your notification preferences here: "
            "http://testserver/admin/account/#tab-notifications",
        )
        section_headings = [
            "Mentions:",
            "New comments:",
            "Resolved comments:",
            "Deleted comments:",
            "New replies:",
        ]
        self.assertEqual(
            [body.index(heading) for heading in section_headings],
            sorted(body.index(heading) for heading in section_headings),
        )
        self.assertEqual(
            body.count('Comment: "Please review this section"'),
            1,
        )

    def test_non_mention_subject_intro_and_sections_are_unchanged(self):
        context = self.template_context(
            mentioned_comments=[],
            mentioned_replies=[],
            new_comments=[self.comment],
            replied_comments=[{"comment": self.comment, "replies": [self.reply]}],
        )

        subject = render_to_string(
            "wagtailadmin/notifications/updated_comments_subject.txt",
            context,
        ).strip()
        body = render_to_string(
            "wagtailadmin/notifications/updated_comments.txt",
            context,
        ).strip()

        self.assertEqual(
            subject,
            'Editor Person has updated comments on "Notification page"',
        )
        self.assertEqual(
            body,
            "Hello Mentioned,\n\n"
            'Editor Person has updated comments on "Notification page".\n\n\n'
            "New comments:\n"
            ' - "Please review this section"\n\n\n'
            "New replies:\n\n"
            '  New replies to: "Please review this section"\n'
            '   - "I have updated it"\n\n'
            f"You can edit the page here: http://testserver/admin/pages/{self.page.pk}/edit/\n\n\n"
            "Edit your notification preferences here: "
            "http://testserver/admin/account/#tab-notifications",
        )
        self.assertNotIn("Mentions:", body)

    def test_plain_text_is_literal_while_html_is_escaped(self):
        self.page.title = 'Page <draft> & "quoted"'
        self.page.draft_title = self.page.title
        self.editor.first_name = "Editor <admin>"
        self.editor.last_name = "& O'Reilly"
        self.comment.text = '<script>alert("comment")</script> & O\'Reilly'
        self.reply.text = '<b>reply</b> & "quoted"'
        context = self.template_context()

        subject = render_to_string(
            "wagtailadmin/notifications/updated_comments_subject.txt",
            context,
        ).strip()
        text_body = render_to_string(
            "wagtailadmin/notifications/updated_comments.txt",
            context,
        ).strip()
        html_body = render_to_string(
            "wagtailadmin/notifications/updated_comments.html",
            context,
        )

        self.assertIn('Page <draft> & "quoted"', subject)
        self.assertIn("Editor <admin> & O'Reilly", subject)
        self.assertIn(
            'Comment: "<script>alert("comment")</script> & O\'Reilly"',
            text_body,
        )
        self.assertIn(
            'Reply to "<script>alert("comment")</script> & O\'Reilly": '
            '"<b>reply</b> & "quoted""',
            text_body,
        )
        self.assertNotIn("&lt;script&gt;", text_body)
        self.assertIn("Page &lt;draft&gt; &amp; &quot;quoted&quot;", html_body)
        self.assertIn("Editor &lt;admin&gt; &amp; O&#x27;Reilly", html_body)
        self.assertIn(
            "&lt;script&gt;alert(&quot;comment&quot;)&lt;/script&gt; "
            "&amp; O&#x27;Reilly",
            html_body,
        )
        self.assertIn(
            "&lt;b&gt;reply&lt;/b&gt; &amp; &quot;quoted&quot;",
            html_body,
        )
        self.assertNotIn("<script>alert", html_body)

    def test_html_mention_copy_and_order_are_exact(self):
        context = self.template_context(
            new_comments=[self.create_comment("New")],
            resolved_comments=[self.create_comment("Resolved")],
            deleted_comments=[
                Comment(
                    page=self.page,
                    user=self.editor,
                    contentpath="title",
                    text="Deleted",
                )
            ],
            replied_comments=[
                {
                    "comment": self.comment,
                    "replies": [self.create_reply(self.comment, "New reply")],
                }
            ],
        )

        html_body = render_to_string(
            "wagtailadmin/notifications/updated_comments.html",
            context,
        )

        soup = self.get_soup(html_body)
        mentions_heading = next(
            heading for heading in soup.find_all("h3") if heading.string == "Mentions"
        )
        self.assertEqual(str(mentions_heading), "<h3>Mentions</h3>")
        self.assertEqual(
            str(mentions_heading.find_next_sibling("ul")),
            '<ul>\n<li>Comment: "Please review this section"</li>\n'
            '<li>Reply to "Please review this section": "I have updated it"</li>\n'
            "</ul>",
        )
        headings = [
            "<h3>Mentions</h3>",
            "<h3>New comments</h3>",
            "<h3>Resolved comments</h3>",
            "<h3>Deleted comments</h3>",
            "<h3>New replies</h3>",
        ]
        self.assertEqual(
            [html_body.index(heading) for heading in headings],
            sorted(html_body.index(heading) for heading in headings),
        )
        for heading in headings:
            self.assertEqual(html_body.count(heading), 1)
