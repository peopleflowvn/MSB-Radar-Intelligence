from django.db import migrations


def create_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "CREATE INDEX IF NOT EXISTS talent_searchprojection_fts_gin "
        "ON talent_searchprojection USING GIN "
        "(to_tsvector('simple', searchable_text))")
    # JSONB containment indexes support skills/industries/source arrays without
    # expanding IDs into Python or an enormous IN clause.
    for column in ("skills_norm", "industries_norm", "source_channels",
                   "application_positions"):
        schema_editor.execute(
            f"CREATE INDEX IF NOT EXISTS talent_searchprojection_{column}_gin "
            f"ON talent_searchprojection USING GIN ({column})")


def drop_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for name in ("talent_searchprojection_fts_gin",
                 "talent_searchprojection_skills_norm_gin",
                 "talent_searchprojection_industries_norm_gin",
                 "talent_searchprojection_source_channels_gin",
                 "talent_searchprojection_application_positions_gin"):
        schema_editor.execute(f"DROP INDEX IF EXISTS {name}")


class Migration(migrations.Migration):
    dependencies = [("talent", "0014_candidatesetrun_cancel_requested_and_more")]
    operations = [migrations.RunPython(create_indexes, drop_indexes)]
