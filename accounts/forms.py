from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

User = get_user_model()


class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        label="E-posta",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
        help_text="Kimseye gösterilmez.",
    )

    # Honeypot: hidden from people and screen readers, filled in by naive bots.
    website = forms.CharField(
        label="Web sitesi (boş bırak)",
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}),
    )
    honeypot_name = "website"

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
        labels = {"username": "Kullanıcı adı"}
        help_texts = {"username": "3–20 karakter: harf, rakam ve alt çizgi."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"autocomplete": "username", "autocapitalize": "none"})
        self.fields["password1"].label = "Parola"
        self.fields["password1"].help_text = "En az 8 karakter; sadece rakam veya çok yaygın bir parola olamaz."
        self.fields["password2"].label = "Parola (tekrar)"
        self.fields["password2"].help_text = ""

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Bu kullanıcı adı alınmış.", code="duplicate_username")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Bu e-posta ile zaten bir hesap var.", code="duplicate_email")
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get(self.honeypot_name):
            raise forms.ValidationError("Kayıt tamamlanamadı. Sayfayı yenileyip tekrar dene.", code="honeypot")
        return cleaned


class LoginForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "Kullanıcı adı veya parola hatalı.",
        "inactive": "Bu hesap devre dışı.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Kullanıcı adı"
        self.fields["username"].widget.attrs.update({"autocapitalize": "none"})
        self.fields["password"].label = "Parola"

    def clean_username(self):
        # Usernames are unique case-insensitively, so map "Ayse_K" to the stored "ayse_k".
        username = self.cleaned_data.get("username", "")
        stored = User.objects.filter(username__iexact=username).values_list("username", flat=True).first()
        return stored or username
