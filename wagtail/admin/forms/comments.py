from django import forms
from django.contrib.auth import get_user_model
from django.forms import ValidationError
from django.urls import reverse
from django.utils.timezone import now
from django.utils.translation import gettext as _
from modelcluster.forms import BaseChildFormSet
from modelcluster.models import get_serializable_data_for_fields

from wagtail.admin.templatetags.wagtailadmin_tags import avatar_url, user_display_name

from .models import WagtailAdminModelForm


def can_user_be_mentioned_for_page(page, user):
    return (
        user.is_active
        and user.has_perm("wagtailadmin.access_admin")
        and page.permissions_for_user(user).can_edit()
    )


class CommentReplyForm(WagtailAdminModelForm):
    class Meta:
        fields = ("text",)

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
        data["deleted"] = self.cleaned_data.get("DELETE", False) if bound else False
        return data, {self.instance.user_id}


class CommentForm(WagtailAdminModelForm):
    """
    This is designed to be subclassed and have the user overridden to enable user-based validation within the edit handler system
    """

    resolved = forms.BooleanField(required=False)
    mentions = forms.JSONField(required=False)

    def __init__(self, *args, **kwargs):
        self.page = kwargs.pop("page", None)
        super().__init__(*args, **kwargs)

    class Meta:
        formsets = {
            "replies": {
                "form": CommentReplyForm,
                "inherit_kwargs": ["for_user"],
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

    def clean_mentions(self):
        mention_ids = self.cleaned_data["mentions"] or []
        if not isinstance(mention_ids, list):
            raise ValidationError(_("Select a valid user to mention."))

        mention_ids = [
            str(mention_id)
            for mention_id in dict.fromkeys(mention_ids)
            if mention_id is not None and str(mention_id)
        ]
        if not mention_ids:
            return []

        page = self.page or getattr(self.instance, "page", None)
        if page is None:
            raise ValidationError(_("Select a valid user to mention."))

        users_by_id = {
            str(user.pk): user
            for user in get_user_model().objects.filter(
                pk__in=mention_ids, is_active=True
            )
        }

        if set(users_by_id) != set(mention_ids):
            raise ValidationError(_("Select a valid user to mention."))

        users = [users_by_id[mention_id] for mention_id in mention_ids]
        if any(not can_user_be_mentioned_for_page(page, user) for user in users):
            raise ValidationError(_("Select a valid user to mention."))

        return users

    def save_mentions(self):
        if "mentions" not in self.cleaned_data or not self.instance.pk:
            return

        mentioned_users = self.cleaned_data["mentions"]
        mentioned_user_ids = [user.pk for user in mentioned_users]

        self.instance.mentions.exclude(user_id__in=mentioned_user_ids).delete()

        existing_mentions = {
            mention.user_id: mention for mention in self.instance.mentions.all()
        }
        for user in mentioned_users:
            if user.pk not in existing_mentions:
                self.instance.mentions.create(user=user)

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
        replies = []
        for reply_form in self.formsets["replies"].forms:
            reply_data, reply_user_pks = reply_form.serialize(bound)
            replies.append(reply_data)
            user_pks.update(reply_user_pks)

        data = get_serializable_data_for_fields(self.instance)
        data["deleted"] = self.cleaned_data.get("DELETE", False) if bound else False
        data["resolved"] = (
            self.cleaned_data.get("resolved", False)
            if bound
            else self.instance.resolved_at is not None
        )
        if bound and "mentions" in self.cleaned_data:
            mentions = self.cleaned_data["mentions"]
            data["mentions"] = [str(user.pk) for user in mentions]
            user_pks.update(user.pk for user in mentions)
        else:
            if self.instance.pk:
                mention_user_pks = list(
                    self.instance.mentions.values_list("user_id", flat=True)
                )
            else:
                mention_user_pks = []
            data["mentions"] = [str(user_pk) for user_pk in mention_user_pks]
            user_pks.update(mention_user_pks)
        data["replies"] = replies
        return data, user_pks


class CommentFormSet(BaseChildFormSet):
    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["page"] = self.instance
        return kwargs

    def save_mentions(self):
        deleted_forms = set(self.deleted_forms)
        for form in self.forms:
            if form not in deleted_forms:
                form.save_mentions()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        valid_comment_ids = [
            comment.id
            for comment in self.queryset
            if comment.has_valid_contentpath(self.instance)
        ]
        self.queryset = self.queryset.filter(id__in=valid_comment_ids)

    def serialize(self, bound: bool, user):
        def user_data(user):
            return {
                "name": user_display_name(user),
                "avatar_url": avatar_url(user),
                "email": user.email,
                "url": reverse("wagtailusers_users:edit", args=[user.pk]),
            }

        user_pks = {user.pk}
        serialized_comments = []
        for form in self.forms:
            # iterate over comments to retrieve users (to get display names) and serialized versions
            data, comment_user_pks = form.serialize(bound)
            serialized_comments.append(data)
            user_pks.update(comment_user_pks)

        authors = {
            str(user.pk): user_data(user)
            for user in get_user_model()
            .objects.filter(pk__in=user_pks)
            .select_related("wagtail_userprofile")
        }

        comments_data = {
            "comments": serialized_comments,
            "user": user.pk,
            "authors": authors,
            "mention_suggestions_url": reverse(
                "wagtailadmin_pages:comment_mention_suggestions",
                args=[self.instance.pk],
            ),
        }
        return comments_data
