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
