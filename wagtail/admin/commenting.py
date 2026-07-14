from dataclasses import dataclass

from wagtail.admin.comment_mentions import MentionChanges
from wagtail.models import Comment, CommentReply


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


def get_resolved_comments(changed_objects):
    return [
        obj
        for obj, fields in changed_objects
        if obj.resolved_at and "resolved" in fields
    ]


def get_edited_comments(changed_objects):
    return [
        obj for obj, fields in changed_objects if {"text", "mentions"} & set(fields)
    ]


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


def _changes_for(message, changes):
    for mentioned_message in changes.mentions:
        candidate = (
            mentioned_message.reply
            if mentioned_message.reply is not None
            else mentioned_message.comment
        )
        if candidate is message:
            return mentioned_message.changes
    return None


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
