from django.db import migrations, models
import django.utils.timezone


def prepare_existing_opportunities(apps, schema_editor):
    Opportunity = apps.get_model("rb", "RBOpportunity")
    for row in Opportunity.objects.filter(stage_entered_at__isnull=True).iterator():
        row.stage_entered_at = row.updated_at or row.created_at
        row.save(update_fields=["stage_entered_at"])

    open_states = ("new", "accepted", "contacting")
    duplicate_keys = (Opportunity.objects.filter(status__in=open_states)
                      .values("person_id", "product")
                      .annotate(total=models.Count("id")).filter(total__gt=1))
    rank = {"contacting": 3, "accepted": 2, "new": 1}
    for key in duplicate_keys.iterator():
        rows = list(Opportunity.objects.filter(
            person_id=key["person_id"], product=key["product"],
            status__in=open_states))
        rows.sort(key=lambda row: (rank.get(row.status, 0), row.updated_at), reverse=True)
        for duplicate in rows[1:]:
            duplicate.status = "lost"
            duplicate.close_reason = "Gộp cơ hội trùng khi nâng cấp hệ thống"
            duplicate.save(update_fields=["status", "close_reason"])


class Migration(migrations.Migration):

    dependencies = [
        ("rb", "0003_rbopportunity_next_action_at_rbopportunity_note_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="rbopportunity",
            name="stage_entered_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(prepare_existing_opportunities, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="rbopportunity",
            name="stage_entered_at",
            field=models.DateTimeField(default=django.utils.timezone.now, db_index=True),
        ),
        migrations.AddIndex(
            model_name="rbopportunity",
            index=models.Index(fields=["assigned_to", "status", "next_action_at"],
                               name="rb_opp_owner_status_due_idx"),
        ),
        migrations.AddConstraint(
            model_name="rbopportunity",
            constraint=models.UniqueConstraint(
                condition=models.Q(status__in=("new", "accepted", "contacting")),
                fields=("person", "product"),
                name="uq_rb_open_opportunity_person_product"),
        ),
    ]
