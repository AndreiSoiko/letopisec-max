from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='botuser',
            name='signup_source',
            field=models.TextField(blank=True, default=''),
        ),
    ]
