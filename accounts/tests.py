from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase


class UserModelTests(TestCase):
    def test_email_is_lowercased(self):
        user = get_user_model().objects.create_user("Mehmet", "Mehmet@Example.COM", "parola-12345")
        self.assertEqual(user.email, "mehmet@example.com")

    def test_username_unique_case_insensitive_at_db_level(self):
        User = get_user_model()
        User.objects.create_user("KullaniciAdi", "a@example.com", "parola-12345")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("kullaniciadi", "b@example.com", "parola-12345")
