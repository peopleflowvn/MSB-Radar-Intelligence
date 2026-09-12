# -*- coding: utf-8 -*-
from django.db import migrations


def update_otp_template_icon_urls(apps, schema_editor):
    EmailOtpSettings = apps.get_model('accounts', 'EmailOtpSettings')
    for s in EmailOtpSettings.objects.all():
        changed = False
        if s.otp_html_template and 'raw.githubusercontent.com' in s.otp_html_template:
            s.otp_html_template = s.otp_html_template.replace(
                'https://raw.githubusercontent.com/peopleflowvn/MSB-Radar/develop/web/public/apple-touch-icon.png',
                '{{app_icon_url}}'
            )
            changed = True
        if changed:
            s.save(update_fields=['otp_html_template'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0014_normalize_email_otp_domains'),
    ]

    operations = [
        migrations.RunPython(update_otp_template_icon_urls, reverse_code=migrations.RunPython.noop),
    ]
