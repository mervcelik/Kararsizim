from django.db import models


class Hit(models.Model):
    """Attempts for one key in one fixed time window. The key is an HMAC, never a raw IP or username."""

    key = models.CharField(max_length=64)
    window = models.BigIntegerField(help_text="Pencerenin başlangıcı (Unix zamanı, saniye).")
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["key", "window"], name="uniq_hit_key_window")]
        indexes = [models.Index(fields=["window"], name="throttle_hit_window_idx")]
