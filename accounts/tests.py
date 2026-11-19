from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .forms import RegisterForm

User = get_user_model()
PASSWORD = "kararsiz-Test-2026"


def register_data(**overrides):
    data = {
        "username": "yeni_kullanici",
        "email": "yeni@example.com",
        "password1": PASSWORD,
        "password2": PASSWORD,
    }
    data.update(overrides)
    return data


class UserModelTests(TestCase):
    def test_email_is_lowercased(self):
        user = User.objects.create_user("Mehmet", "Mehmet@Example.COM", PASSWORD)
        self.assertEqual(user.email, "mehmet@example.com")

    def test_username_unique_case_insensitive_at_db_level(self):
        User.objects.create_user("KullaniciAdi", "a@example.com", PASSWORD)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("kullaniciadi", "b@example.com", PASSWORD)


class RegisterFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user("KullaniciAdi", "mevcut@example.com", PASSWORD)

    def test_duplicate_email_rejected(self):
        form = RegisterForm(register_data(email="Mevcut@Example.com"))
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["email"], ["Bu e-posta ile zaten bir hesap var."])

    def test_username_case_insensitive_duplicate_rejected(self):
        form = RegisterForm(register_data(username="kullaniciadi"))
        self.assertFalse(form.is_valid())
        self.assertIn("Bu kullanıcı adı alınmış.", form.errors["username"])

    def test_invalid_username_characters_rejected(self):
        for username in ("ab", "çok-güzel", "boşluk var", "a" * 21):
            with self.subTest(username=username):
                form = RegisterForm(register_data(username=username))
                self.assertFalse(form.is_valid())
                self.assertIn("username", form.errors)

    def test_reserved_username_rejected(self):
        form = RegisterForm(register_data(username="Admin"))
        self.assertFalse(form.is_valid())
        self.assertIn("Bu kullanıcı adı kullanılamaz.", form.errors["username"])

    def test_short_password_rejected(self):
        form = RegisterForm(register_data(password1="kisa1", password2="kisa1"))
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)


class AuthFlowTests(TestCase):
    def test_register_logs_in_and_redirects_home(self):
        response = self.client.post(reverse("accounts:register"), register_data(), follow=True)
        self.assertRedirects(response, "/")
        self.assertTrue(response.context["user"].is_authenticated)
        self.assertContains(response, "Hoş geldin, @yeni_kullanici")
        self.assertEqual(User.objects.get().email, "yeni@example.com")

    def test_login_is_case_insensitive_and_respects_next(self):
        User.objects.create_user("ayse_k", "ayse@example.com", PASSWORD)
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "Ayse_K", "password": PASSWORD, "next": "/kullanici/ayse_k/"},
        )
        self.assertRedirects(response, "/kullanici/ayse_k/", fetch_redirect_response=False)

    def test_wrong_password_shows_turkish_error(self):
        User.objects.create_user("ayse_k", "ayse@example.com", PASSWORD)
        response = self.client.post(reverse("accounts:login"), {"username": "ayse_k", "password": "yanlis"})
        self.assertContains(response, "Kullanıcı adı veya parola hatalı.")

    def test_login_page_shows_create_notice_for_create_next(self):
        response = self.client.get(reverse("accounts:login"), {"next": "/anket/olustur/"})
        self.assertContains(response, "Anket oluşturmak için giriş yapman gerekiyor.")

    def test_logout_requires_post(self):
        user = User.objects.create_user("ayse_k", "ayse@example.com", PASSWORD)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)


class EmailPrivacyTests(TestCase):
    def test_email_never_rendered_for_logged_in_user(self):
        user = User.objects.create_user("gizli_kisi", "gizli.adres@example.com", PASSWORD)
        self.client.force_login(user)
        for url in ("/", reverse("accounts:login"), reverse("accounts:register")):
            with self.subTest(url=url):
                response = self.client.get(url, follow=True)
                self.assertNotContains(response, "gizli.adres@example.com")
                self.assertNotContains(response, "gizli.adres")
