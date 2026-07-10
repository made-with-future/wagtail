from django import forms
from django.contrib.auth import get_user_model
from django.forms import ValidationError
from django.urls import reverse
from django.utils.timezone import now
from django.utils.translation import gettext as _
from modelcluster.forms import BaseChildFormSet
from modelcluster.models import get_serializable_data_for_fields

from wagtail.admin.comment_mentions import (
    InvalidMentionTargets,
    current_mention_email,
    future_page_mention_candidates,
    page_mention_candidates,
    resolve_new_mention_users,
    sync_message_mention_lookups,
)
from wagtail.admin.templatetags.wagtailadmin_tags import avatar_url, user_display_name

from .comment_mentions import CommentMentionsField, MentionedMessageFormMixin
from .models import WagtailAdminModelForm


class CommentReplyForm(MentionedMessageFormMixin, WagtailAdminModelForm):
    mentions = CommentMentionsField(required=False)

    class Meta:
        fields = ("text", "mentions")

    def clean(self):
        cleaned_data = super().clean()
        user = self.for_user

        if not self.instance.pk:
            self.instance.user = user
        elif self.instance.user != user:
            # trying to edit someone else's comment reply
            if any(field for field in self.changed_data):
                # includes DELETION_FIELD_NAME, as users cannot delete each other's individual comment replies
                # if deleting a whole thread, this should be done by deleting the parent Comment instead
                self.add_error(
                    None, ValidationError(_("You cannot edit another user's comment."))
                )
        return cleaned_data

    def serialize(self, bound):
        data = get_serializable_data_for_fields(self.instance)
        data["user"] = (
            str(self.instance.user_id) if self.instance.user_id is not None else None
        )
        mentions = self.serialized_mentions(bound=bound)
        data["mentions"] = mentions
        data["deleted"] = self.cleaned_data.get("DELETE", False) if bound else False
        return (
            data,
            {self.instance.user_id},
            {occurrence["user_id"] for occurrence in mentions},
        )


class CommentForm(MentionedMessageFormMixin, WagtailAdminModelForm):
    """
    This is designed to be subclassed and have the user overridden to enable user-based validation within the edit handler system
    """

    resolved = forms.BooleanField(required=False)
    mentions = CommentMentionsField(required=False)

    class Meta:
        formsets = {
            "replies": {
                "form": CommentReplyForm,
                "inherit_kwargs": ["for_user", "page", "parent_page"],
            }
        }

    def clean(self):
        cleaned_data = super().clean()
        user = self.for_user

        if not self.instance.pk:
            self.instance.user = user
        elif self.instance.user != user:
            # trying to edit someone else's comment
            if (
                any(
                    field
                    for field in self.changed_data
                    if field not in ["resolved", "position", "contentpath"]
                )
                or cleaned_data["contentpath"].split(".")[0]
                != self.instance.contentpath.split(".")[0]
            ):
                # users can resolve each other's base comments and change their positions within a field, or move a comment between blocks in a StreamField
                self.add_error(
                    None, ValidationError(_("You cannot edit another user's comment."))
                )
        return cleaned_data

    def save(self, *args, **kwargs):
        if self.cleaned_data.get("resolved", False):
            if not self.instance.resolved_at:
                self.instance.resolved_at = now()
                self.instance.resolved_by = self.for_user
        else:
            self.instance.resolved_by = None
            self.instance.resolved_at = None

        return super().save(*args, **kwargs)

    def serialize(self, bound):
        user_pks = {self.instance.user_id}
        mentioned_user_ids = set()
        replies = []
        for reply_form in self.formsets["replies"].forms:
            reply_data, reply_user_pks, reply_mentioned_user_ids = reply_form.serialize(
                bound
            )
            replies.append(reply_data)
            user_pks.update(reply_user_pks)
            mentioned_user_ids.update(reply_mentioned_user_ids)

        data = get_serializable_data_for_fields(self.instance)
        data["user"] = (
            str(self.instance.user_id) if self.instance.user_id is not None else None
        )
        data["deleted"] = self.cleaned_data.get("DELETE", False) if bound else False
        data["resolved"] = (
            self.cleaned_data.get("resolved", False)
            if bound
            else self.instance.resolved_at is not None
        )
        mentions = self.serialized_mentions(bound=bound)
        data["mentions"] = mentions
        mentioned_user_ids.update(occurrence["user_id"] for occurrence in mentions)
        data["replies"] = replies
        return data, user_pks, mentioned_user_ids


class CommentFormSet(BaseChildFormSet):
    def __init__(self, *args, **kwargs):
        form_kwargs = kwargs.get("form_kwargs") or {}
        self.for_user = form_kwargs.get("for_user")
        self.parent_page = form_kwargs.get("parent_page")
        super().__init__(*args, **kwargs)
        valid_comment_ids = [
            comment.id
            for comment in self.queryset
            if comment.has_valid_contentpath(self.instance)
        ]
        self.queryset = self.queryset.filter(id__in=valid_comment_ids)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["page"] = self.instance
        return kwargs

    def clean(self):
        super().clean()
        if not any(
            form.mention_changes.added
            for form in self.iter_mention_forms(valid_only=True)
        ):
            return
        if self.instance.pk:
            candidates = page_mention_candidates(self.instance)
        else:
            candidates = future_page_mention_candidates(
                parent_page=self.parent_page,
                owner=self.for_user,
            )

        try:
            self.validate_new_mentions(candidates)
        except InvalidMentionTargets:
            pass

    def iter_mention_forms(self, *, include_deleted=False, valid_only=False):
        for comment_form in self.forms:
            comment_deleted = comment_form.cleaned_data.get("DELETE", False)
            if (include_deleted or not comment_deleted) and (
                not valid_only or not comment_form.errors
            ):
                yield comment_form

            if comment_deleted and not include_deleted:
                continue
            replies = comment_form.formsets.get("replies")
            if replies is None:
                continue
            for reply_form in replies.forms:
                reply_deleted = reply_form.cleaned_data.get("DELETE", False)
                if (include_deleted or not reply_deleted) and (
                    not valid_only or not reply_form.errors
                ):
                    yield reply_form

    def validate_new_mentions(self, candidates):
        occurrence_forms = [
            (form, occurrence)
            for form in self.iter_mention_forms(valid_only=True)
            for occurrence in form.mention_changes.added
        ]
        if not occurrence_forms:
            return ()

        try:
            return resolve_new_mention_users(
                [occurrence for form, occurrence in occurrence_forms],
                candidates,
            )
        except InvalidMentionTargets as error:
            invalid_forms = []
            for index in error.invalid_indices:
                form = occurrence_forms[index][0]
                if form not in invalid_forms:
                    invalid_forms.append(form)
            for form in invalid_forms:
                form.invalid_target_mentions = list(form.cleaned_data["mentions"])
                form.add_error("mentions", form.mention_validation_error)
            raise

    def sync_mention_lookups(self):
        deleted_comment_forms = set(self.deleted_forms)
        for form in self.forms:
            if form in deleted_comment_forms:
                continue
            if form.instance.pk:
                sync_message_mention_lookups(
                    message=form.instance,
                    occurrences=form.cleaned_data["mentions"],
                )
            replies = form.formsets["replies"]
            deleted_reply_forms = set(replies.deleted_forms)
            for reply_form in replies.forms:
                if reply_form not in deleted_reply_forms and reply_form.instance.pk:
                    sync_message_mention_lookups(
                        message=reply_form.instance,
                        occurrences=reply_form.cleaned_data["mentions"],
                    )

    def serialize(self, bound: bool, user):
        def user_data(user):
            return {
                "name": user_display_name(user),
                "avatar_url": avatar_url(user),
            }

        user_pks = {user.pk}
        mentioned_user_ids = set()
        serialized_comments = []
        for form in self.forms:
            # iterate over comments to retrieve users (to get display names) and serialized versions
            data, comment_user_pks, comment_mentioned_user_ids = form.serialize(bound)
            serialized_comments.append(data)
            user_pks.update(comment_user_pks)
            mentioned_user_ids.update(comment_mentioned_user_ids)

        authors = {
            str(author.pk): user_data(author)
            for author in get_user_model()
            ._default_manager.filter(pk__in=user_pks)
            .select_related("wagtail_userprofile")
        }

        user_model = get_user_model()
        pk_field = user_model._meta.pk
        mentioned_users = list(
            user_model._default_manager.filter(pk__in=mentioned_user_ids)
        )
        users_by_prepared_id = {
            str(pk_field.get_prep_value(mentioned_user.pk)): mentioned_user
            for mentioned_user in mentioned_users
        }
        mentioned_users_data = {}
        for mention_user_id in mentioned_user_ids:
            try:
                parsed_user_id = pk_field.to_python(mention_user_id)
                prepared_user_id = str(pk_field.get_prep_value(parsed_user_id))
            except (OverflowError, TypeError, ValueError, ValidationError):
                continue
            if mentioned_user := users_by_prepared_id.get(prepared_user_id):
                mentioned_users_data[mention_user_id] = {
                    "email": current_mention_email(mentioned_user)
                }

        comments_data = {
            "comments": serialized_comments,
            "user": str(user.pk),
            "authors": authors,
            "mentioned_users": mentioned_users_data,
        }
        if self.instance.pk is not None:
            comments_data["mention_suggestions_url"] = reverse(
                "wagtailadmin_pages:comment_mention_suggestions",
                args=[self.instance.pk],
            )
        elif self.parent_page is not None:
            comments_data["mention_suggestions_url"] = reverse(
                "wagtailadmin_pages:create_comment_mention_suggestions",
                args=[
                    self.instance._meta.app_label,
                    self.instance._meta.model_name,
                    self.parent_page.pk,
                ],
            )
        return comments_data
