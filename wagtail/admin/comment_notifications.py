from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch

from wagtail.admin.mail import send_notification
from wagtail.models import Comment, CommentReply, PageSubscription


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


def _message_identity(message):
    model_label = message._meta.label_lower
    if message.pk is None:
        return (model_label, None, id(message))
    return (model_label, message.pk)


def _append_unique(messages, message):
    identity = _message_identity(message)
    if all(_message_identity(existing) != identity for existing in messages):
        messages.append(message)


def _add_replies(payload, comment, replies):
    comment_identity = _message_identity(comment)
    thread = next(
        (
            item
            for item in payload.replied_comments
            if _message_identity(item["comment"]) == comment_identity
        ),
        None,
    )
    if thread is None:
        thread = {"comment": comment, "replies": []}
        payload.replied_comments.append(thread)
    for reply in replies:
        _append_unique(thread["replies"], reply)


def _payload_for(payloads, user):
    return payloads.setdefault(user.pk, RecipientPayload(user=user))


def _has_ordinary_changes(changes):
    return bool(
        changes.new_comments
        or changes.resolved_comments
        or changes.deleted_comments
        or changes.new_replies
    )


def _seed_global_subscribers(*, payloads, page, editor, changes):
    if not _has_ordinary_changes(changes):
        return

    subscriptions = (
        PageSubscription.objects.filter(page=page, comment_notifications=True)
        .select_related("user")
        .order_by("pk")
    )
    for subscription in subscriptions:
        user = subscription.user
        if user.pk == editor.pk:
            continue
        payload = _payload_for(payloads, user)
        for comment in changes.new_comments:
            _append_unique(payload.new_comments, comment)
        for comment in changes.resolved_comments:
            _append_unique(payload.resolved_comments, comment)
        for comment in changes.deleted_comments:
            _append_unique(payload.deleted_comments, comment)
        for comment, replies in changes.new_replies:
            _add_replies(payload, comment, replies)


def _add_thread_participants(*, payloads, editor, changes):
    affected_thread_ids = {
        comment.pk for comment in changes.resolved_comments if comment.pk is not None
    }
    affected_thread_ids.update(
        comment.pk for comment, replies in changes.new_replies if comment.pk is not None
    )
    if not affected_thread_ids:
        return

    reply_queryset = CommentReply.objects.select_related("user")
    threads = (
        Comment.objects.filter(pk__in=affected_thread_ids)
        .select_related("user")
        .prefetch_related(Prefetch("replies", queryset=reply_queryset))
        .order_by("pk")
    )
    participant_threads = {}
    participant_users = {}
    for thread in threads:
        participants = [thread.user]
        participants.extend(reply.user for reply in thread.replies.all())
        for user in participants:
            if user.pk == editor.pk:
                continue
            participant_users.setdefault(user.pk, user)
            participant_threads.setdefault(user.pk, set()).add(thread.pk)

    for user_pk, thread_ids in participant_threads.items():
        payload = _payload_for(payloads, participant_users[user_pk])
        for comment in changes.resolved_comments:
            if comment.pk in thread_ids:
                _append_unique(payload.resolved_comments, comment)
        for comment, replies in changes.new_replies:
            if comment.pk in thread_ids:
                _add_replies(payload, comment, replies)


def _prepare_user_id(pk_field, value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        parsed_value = pk_field.to_python(value)
        prepared_value = pk_field.get_prep_value(parsed_value)
    except (OverflowError, TypeError, ValueError, ValidationError):
        return None
    if parsed_value is None or prepared_value is None:
        return None
    return str(prepared_value)


def _add_direct_mentions(*, payloads, editor, changes):
    user_model = get_user_model()
    pk_field = user_model._meta.pk
    occurrences = []
    prepared_ids = set()
    for mentioned_message in changes.mentions:
        for occurrence in mentioned_message.changes.added:
            prepared_id = _prepare_user_id(pk_field, occurrence.get("user_id"))
            if prepared_id is None:
                continue
            occurrences.append((mentioned_message, prepared_id))
            prepared_ids.add(prepared_id)

    if not prepared_ids:
        return

    targets_by_prepared_id = {}
    targets = user_model._default_manager.filter(is_active=True, pk__in=prepared_ids)
    for user in targets:
        prepared_id = str(pk_field.get_prep_value(user.pk))
        targets_by_prepared_id[prepared_id] = user

    for mentioned_message, prepared_id in occurrences:
        user = targets_by_prepared_id.get(prepared_id)
        if user is None or user.pk == editor.pk:
            continue
        payload = _payload_for(payloads, user)
        if mentioned_message.reply is None:
            _append_unique(payload.mentioned_comments, mentioned_message.comment)
        else:
            pair = {
                "comment": mentioned_message.comment,
                "reply": mentioned_message.reply,
            }
            pair_identity = (
                _message_identity(mentioned_message.comment),
                _message_identity(mentioned_message.reply),
            )
            if all(
                (
                    _message_identity(existing["comment"]),
                    _message_identity(existing["reply"]),
                )
                != pair_identity
                for existing in payload.mentioned_replies
            ):
                payload.mentioned_replies.append(pair)


def _prune_mentioned_messages(payload):
    mentioned_comment_ids = {
        _message_identity(comment) for comment in payload.mentioned_comments
    }
    payload.new_comments = [
        comment
        for comment in payload.new_comments
        if _message_identity(comment) not in mentioned_comment_ids
    ]
    payload.resolved_comments = [
        comment
        for comment in payload.resolved_comments
        if _message_identity(comment) not in mentioned_comment_ids
    ]
    payload.deleted_comments = [
        comment
        for comment in payload.deleted_comments
        if _message_identity(comment) not in mentioned_comment_ids
    ]

    mentioned_reply_ids = {
        (_message_identity(item["comment"]), _message_identity(item["reply"]))
        for item in payload.mentioned_replies
    }
    replied_comments = []
    for thread in payload.replied_comments:
        comment_identity = _message_identity(thread["comment"])
        replies = [
            reply
            for reply in thread["replies"]
            if (comment_identity, _message_identity(reply)) not in mentioned_reply_ids
        ]
        if replies:
            replied_comments.append({"comment": thread["comment"], "replies": replies})
    payload.replied_comments = replied_comments


def _payload_has_content(payload):
    return bool(
        payload.new_comments
        or payload.resolved_comments
        or payload.deleted_comments
        or payload.replied_comments
        or payload.mentioned_comments
        or payload.mentioned_replies
    )


def build_recipient_payloads(*, page, editor, changes):
    payloads = {}
    _seed_global_subscribers(
        payloads=payloads,
        page=page,
        editor=editor,
        changes=changes,
    )
    _add_thread_participants(
        payloads=payloads,
        editor=editor,
        changes=changes,
    )
    _add_direct_mentions(
        payloads=payloads,
        editor=editor,
        changes=changes,
    )

    for user_pk, payload in list(payloads.items()):
        _prune_mentioned_messages(payload)
        if not _payload_has_content(payload):
            del payloads[user_pk]
    return payloads


def _payload_signature(payload):
    return (
        tuple(_message_identity(comment) for comment in payload.new_comments),
        tuple(_message_identity(comment) for comment in payload.resolved_comments),
        tuple(_message_identity(comment) for comment in payload.deleted_comments),
        tuple(
            (
                _message_identity(thread["comment"]),
                tuple(_message_identity(reply) for reply in thread["replies"]),
            )
            for thread in payload.replied_comments
        ),
        tuple(_message_identity(comment) for comment in payload.mentioned_comments),
        tuple(
            (
                _message_identity(item["comment"]),
                _message_identity(item["reply"]),
            )
            for item in payload.mentioned_replies
        ),
    )


def _section_context(payload):
    return {
        "new_comments": list(payload.new_comments),
        "resolved_comments": list(payload.resolved_comments),
        "deleted_comments": list(payload.deleted_comments),
        "replied_comments": [
            {"comment": thread["comment"], "replies": list(thread["replies"])}
            for thread in payload.replied_comments
        ],
        "mentioned_comments": list(payload.mentioned_comments),
        "mentioned_replies": [dict(item) for item in payload.mentioned_replies],
    }


def group_identical_payloads(payloads):
    groups = []
    group_indexes = {}
    for payload in payloads.values():
        signature = _payload_signature(payload)
        group_index = group_indexes.get(signature)
        if group_index is None:
            group_indexes[signature] = len(groups)
            groups.append(([payload.user], _section_context(payload)))
        else:
            groups[group_index][0].append(payload.user)
    return groups


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
