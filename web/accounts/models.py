import random
import secrets
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models, transaction


def _gen_bot_user_id() -> int:
    """Генерирует уникальный user_id в диапазоне 10^15..10^18-1 для веб-пользователей."""
    return random.randint(10**15, 10**18 - 1)


class WebUserManager(BaseUserManager):
    def create_user(self, email: str, password: str = None, **extra):
        if not email:
            raise ValueError("Email обязателен")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class WebUser(AbstractBaseUser, PermissionsMixin):
    """Пользователь веб-сайта. Каждый получает запись в таблице users (bot DB)."""
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=150, blank=True)

    # Социальная авторизация
    vk_id = models.BigIntegerField(null=True, blank=True, unique=True)
    yandex_id = models.CharField(max_length=100, null=True, blank=True, unique=True)

    # Привязка аккаунта MAX-мессенджера
    bot_user_id = models.BigIntegerField(null=True, blank=True, unique=True)
    is_max_linked = models.BooleanField(default=False)
    max_link_code = models.CharField(max_length=8, blank=True)
    max_link_code_expires = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = WebUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Веб-пользователь"
        verbose_name_plural = "Веб-пользователи"

    def __str__(self):
        return self.email

    def get_display_name(self) -> str:
        return self.display_name or self.email.split("@")[0]

    def generate_max_link_code(self):
        from django.utils import timezone
        from datetime import timedelta
        self.max_link_code = secrets.token_hex(4).upper()
        self.max_link_code_expires = timezone.now() + timedelta(minutes=15)
        self.save(update_fields=["max_link_code", "max_link_code_expires"])
        return self.max_link_code

    @transaction.atomic
    def initialize_bot_user(self, source: str = ""):
        """Создаёт запись в таблице users (bot DB) для нового веб-пользователя."""
        from billing.models import BotUser
        bot_user_id = _gen_bot_user_id()
        while BotUser.objects.filter(user_id=bot_user_id).exists():
            bot_user_id = _gen_bot_user_id()
        BotUser.objects.create(
            user_id=bot_user_id,
            username=f"web_{self.pk}",
            first_name=self.get_display_name(),
            signup_source=source[:40],
        )
        self.bot_user_id = bot_user_id
        self.save(update_fields=["bot_user_id"])

    @property
    def star_balance(self) -> int:
        from billing.models import BotUser
        if not self.bot_user_id:
            return 0
        return BotUser.objects.filter(user_id=self.bot_user_id).values_list("star_balance", flat=True).first() or 0

    @property
    def free_minutes(self) -> float:
        from billing.models import BotUser
        if not self.bot_user_id:
            return 0.0
        return float(BotUser.objects.filter(user_id=self.bot_user_id).values_list("free_minutes", flat=True).first() or 0)
