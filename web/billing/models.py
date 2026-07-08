"""
Unmanaged-модели для таблиц бота + managed-модели для веб-платежей.
managed=False означает, что Django не создаёт и не удаляет эти таблицы.
"""
from django.db import models
from django.conf import settings


class BotUser(models.Model):
    """Таблица users бота — общая с MAX-ботом."""
    user_id = models.BigIntegerField(primary_key=True)
    username = models.TextField(blank=True, null=True)
    first_name = models.TextField(blank=True, null=True)
    trial_used = models.BooleanField(default=False)
    star_balance = models.IntegerField(default=0)
    free_minutes = models.FloatField(default=0)
    email = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = "users"

    def __str__(self):
        return f"BotUser({self.user_id})"


class BotSubscription(models.Model):
    """Таблица subscriptions бота."""
    user_id = models.BigIntegerField()
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    minutes_total = models.IntegerField()
    minutes_used = models.FloatField()
    stars_paid = models.IntegerField()
    telegram_charge_id = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "subscriptions"


class BotApiKey(models.Model):
    """Таблица api_keys бота."""
    user_id = models.BigIntegerField()
    key_hash = models.TextField()
    name = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "api_keys"


class BotApiJob(models.Model):
    """Таблица api_jobs бота."""
    id = models.TextField(primary_key=True)
    user_id = models.BigIntegerField()
    status = models.TextField(default="pending")
    mode = models.TextField()
    file_url = models.TextField()
    language = models.TextField(default="ru-RU")
    translate_to = models.TextField(blank=True, default="")
    custom_prompt = models.TextField(blank=True, default="")
    duration_sec = models.FloatField(null=True, blank=True)
    result_text = models.TextField(null=True, blank=True)
    result_analysis = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "api_jobs"


class WebTinkoffOrder(models.Model):
    """Платёжные заказы T-Bank, созданные через веб-сайт."""
    order_id = models.CharField(max_length=100, primary_key=True)
    web_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tinkoff_orders"
    )
    payment_type = models.CharField(max_length=20, default="topup")
    amount_rub = models.IntegerField()
    tinkoff_payment_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "web_tinkoff_orders"
        verbose_name = "Веб-заказ T-Bank"
        verbose_name_plural = "Веб-заказы T-Bank"
