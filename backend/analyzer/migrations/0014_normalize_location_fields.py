from django.db import migrations


def _legacy_field_name():
    return 'location' + '_ref'


def _legacy_column_name():
    return _legacy_field_name() + '_id'


def _table_columns(schema_editor, table_name):
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return {column.name for column in description}


def _drop_indexes_for_column(schema_editor, table_name, column_name):
    if schema_editor.connection.vendor != 'sqlite':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'PRAGMA index_list({table_name!r})')
        index_rows = cursor.fetchall()
        for index_row in index_rows:
            index_name = index_row[1]
            if str(index_name).startswith('sqlite_autoindex_'):
                continue
            cursor.execute(f'PRAGMA index_info({index_name!r})')
            index_columns = [item[2] for item in cursor.fetchall()]
            if column_name not in index_columns:
                continue
            cursor.execute(f'DROP INDEX {schema_editor.quote_name(index_name)}')


def _ensure_location_column(model, schema_editor):
    table_name = model._meta.db_table
    if 'location' in _table_columns(schema_editor, table_name):
        return
    schema_editor.add_field(model, model._meta.get_field('location'))


def _copy_plain_locations(apps, schema_editor, model_name, *, ensure_location=False):
    model = apps.get_model('analyzer', model_name)
    table_name = model._meta.db_table
    if ensure_location:
        _ensure_location_column(model, schema_editor)

    legacy_column = _legacy_column_name()
    columns = _table_columns(schema_editor, table_name)
    if 'location' not in columns or legacy_column not in columns:
        return

    location_model = apps.get_model('analyzer', 'Location')
    location_names = {
        item.id: str(item.name or '').strip()
        for item in location_model.objects.all().only('id', 'name')
    }

    quoted_table = schema_editor.quote_name(table_name)
    quoted_id = schema_editor.quote_name('id')
    quoted_location = schema_editor.quote_name('location')
    quoted_legacy = schema_editor.quote_name(legacy_column)

    select_sql = (
        f"SELECT {quoted_id}, {quoted_location}, {quoted_legacy} "
        f"FROM {quoted_table} WHERE {quoted_legacy} IS NOT NULL"
    )
    update_sql = (
        f"UPDATE {quoted_table} SET {quoted_location} = %s "
        f"WHERE {quoted_id} = %s"
    )

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(select_sql)
        for row_id, existing_location, legacy_location_id in cursor.fetchall():
            if str(existing_location or '').strip():
                continue
            next_location = location_names.get(legacy_location_id, '')
            if not next_location:
                continue
            cursor.execute(update_sql, [next_location, row_id])


def _drop_legacy_location_column(apps, schema_editor, model_name):
    model = apps.get_model('analyzer', model_name)
    table_name = model._meta.db_table
    legacy_column = _legacy_column_name()
    if legacy_column not in _table_columns(schema_editor, table_name):
        return
    _drop_indexes_for_column(schema_editor, table_name, legacy_column)
    quoted_table = schema_editor.quote_name(table_name)
    quoted_column = schema_editor.quote_name(legacy_column)
    schema_editor.execute(f'ALTER TABLE {quoted_table} DROP COLUMN {quoted_column}')


def normalize_legacy_location_columns(apps, schema_editor):
    for model_name in ('Employee', 'Job', 'UserProfile', 'ProfilePanel'):
        _copy_plain_locations(apps, schema_editor, model_name)
    _copy_plain_locations(apps, schema_editor, 'Interview', ensure_location=True)

    for model_name in ('Employee', 'Job', 'UserProfile', 'ProfilePanel', 'Interview'):
        _drop_legacy_location_column(apps, schema_editor, model_name)


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0013_job_location'),
    ]

    operations = [
        migrations.RunPython(normalize_legacy_location_columns, migrations.RunPython.noop),
    ]
