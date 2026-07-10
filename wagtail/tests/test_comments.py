from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from wagtail.models import (
    Comment,
    CommentMention,
    CommentReply,
    CommentReplyMention,
    Page,
)


class CommentTestingUtils:
    def setUp(self):
        self.page = Page.objects.get(title="Welcome to the Wagtail test site!")
        self.revision_1 = self.page.save_revision()
        self.revision_2 = self.page.save_revision()

    def create_comment(self, revision_created):
        return Comment.objects.create(
            page=self.page,
            user=get_user_model().objects.first(),
            text="test",
            contentpath="title",
            revision_created=revision_created,
        )


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

    def test_reply_occurrences_round_trip(self):
        comment = self.create_comment(self.revision_1)
        reply = CommentReply.objects.create(
            comment=comment,
            user=get_user_model().objects.first(),
            text="reply",
        )
        occurrence = {
            "key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb",
            "user_id": str(comment.user_id),
            "start": 0,
            "end": 3,
            "label": "@Jo",
        }

        reply.mentions = [occurrence]
        reply.save()
        reply.refresh_from_db()

        self.assertEqual(reply.mentions, [occurrence])

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

        with self.assertRaises(IntegrityError), transaction.atomic():
            CommentMention.objects.create(comment=comment, user=target)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CommentReplyMention.objects.create(reply=reply, user=target)

        second_comment = self.create_comment(self.revision_2)
        second_reply = CommentReply.objects.create(
            comment=second_comment,
            user=comment.user,
            text="second reply",
        )
        CommentMention.objects.create(comment=second_comment, user=target)
        CommentReplyMention.objects.create(reply=second_reply, user=target)
        CommentMention.objects.create(comment=comment, user=comment.user)
        CommentReplyMention.objects.create(reply=reply, user=comment.user)

        self.assertEqual(CommentMention.objects.filter(user=target).count(), 2)
        self.assertEqual(CommentReplyMention.objects.filter(user=target).count(), 2)
        self.assertEqual(CommentMention.objects.filter(comment=comment).count(), 2)
        self.assertEqual(CommentReplyMention.objects.filter(reply=reply).count(), 2)

    def test_deleting_target_removes_lookups_but_preserves_occurrences(self):
        comment = self.create_comment(self.revision_1)
        reply = CommentReply.objects.create(
            comment=comment,
            user=get_user_model().objects.first(),
            text="reply",
        )
        target = get_user_model().objects.exclude(pk=comment.user_id).first()
        occurrence = {
            "key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb",
            "user_id": str(target.pk),
            "start": 0,
            "end": 3,
            "label": "@Jo",
        }
        comment.mentions = [occurrence]
        reply.mentions = [occurrence]
        comment.save()
        reply.save()
        CommentMention.objects.create(comment=comment, user=target)
        CommentReplyMention.objects.create(reply=reply, user=target)

        target.delete()

        self.assertFalse(CommentMention.objects.filter(comment=comment).exists())
        self.assertFalse(CommentReplyMention.objects.filter(reply=reply).exists())
        comment.refresh_from_db()
        reply.refresh_from_db()
        self.assertEqual(comment.mentions, [occurrence])
        self.assertEqual(reply.mentions, [occurrence])

    def test_lookup_models_have_no_reverse_accessors(self):
        for model in (Comment, CommentReply, get_user_model()):
            related_models = {field.related_model for field in model._meta.get_fields()}
            self.assertNotIn(CommentMention, related_models)
            self.assertNotIn(CommentReplyMention, related_models)

    def test_ordinary_save_updates_comment_text(self):
        comment = self.create_comment(self.revision_1)

        comment.text = "updated"
        comment.save()
        comment.refresh_from_db()

        self.assertEqual(comment.text, "updated")

    def test_save_with_update_fields_updates_mentions_only(self):
        comment = self.create_comment(self.revision_1)
        occurrence = {
            "key": "29cc6a1f-00ed-41d7-94b1-d46a947962cb",
            "user_id": str(comment.user_id),
            "start": 0,
            "end": 3,
            "label": "@Jo",
        }
        comment.text = "not saved"
        comment.mentions = [occurrence]

        comment.save(update_fields=["mentions"])
        comment.refresh_from_db()

        self.assertEqual(comment.mentions, [occurrence])
        self.assertEqual(comment.text, "test")

    def test_ordinary_save_commits_staged_reply_changes(self):
        comment = self.create_comment(self.revision_1)
        reply = CommentReply(
            user=get_user_model().objects.first(),
            text="reply",
        )
        comment.replies.add(reply)

        self.assertIsNone(reply.pk)
        comment.save()
        self.assertIsNotNone(reply.pk)

        managed_reply = comment.replies.get_object_list()[0]
        managed_reply.text = "updated"
        comment.save()
        managed_reply.refresh_from_db()
        self.assertEqual(managed_reply.text, "updated")

        comment.replies.remove(managed_reply)
        comment.save()
        self.assertFalse(CommentReply.objects.filter(pk=managed_reply.pk).exists())


class TestRevisionDeletion(CommentTestingUtils, TestCase):
    fixtures = ["test.json"]

    def setUp(self):
        super().setUp()
        self.revision_3 = self.page.save_revision()
        self.old_comment = self.create_comment(self.revision_1)
        self.new_comment = self.create_comment(self.revision_3)

    def test_deleting_old_revision_moves_comment_revision_created_forwards(self):
        # test that when a revision is deleted, a comment linked to it via revision_created has its revision_created moved
        # to the next revision
        self.revision_1.delete()
        self.old_comment.refresh_from_db()
        self.assertEqual(self.old_comment.revision_created, self.revision_2)

    def test_deleting_most_recent_revision_deletes_created_comments(self):
        # test that when the most recent revision is deleted, any comments created on it are also deleted
        self.revision_3.delete()
        with self.assertRaises(Comment.DoesNotExist):
            self.new_comment.refresh_from_db()
