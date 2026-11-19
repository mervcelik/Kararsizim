from django import forms

from .models import MAX_OPTIONS, MIN_OPTIONS, Option, Poll

OPTION_MAX_LENGTH = Option._meta.get_field("text").max_length


class PollForm(forms.Form):
    """Options arrive as repeated `options` inputs so the server, not the JS, enforces the 2–5 rule."""

    question = forms.CharField(
        label="Soru",
        min_length=10,
        max_length=Poll._meta.get_field("question").max_length,
        error_messages={
            "required": "Bir soru yazmalısın.",
            "min_length": "Soru en az 10 karakter olmalı.",
            "max_length": "Soru en fazla 140 karakter olabilir.",
        },
        widget=forms.TextInput(attrs={"placeholder": "Bugün sinemaya mı gitsem, restorana mı?"}),
    )
    description = forms.CharField(
        label="Açıklama",
        required=False,
        max_length=Poll._meta.get_field("description").max_length,
        error_messages={"max_length": "Açıklama en fazla 280 karakter olabilir."},
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "İstersen biraz detay ver."}),
        help_text="İsteğe bağlı.",
    )

    def __init__(self, *args, daily_count=0, daily_limit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.daily_count = daily_count
        self.daily_limit = daily_limit
        self.option_errors = []
        raw = self.data.getlist("options") if self.is_bound else []
        self.raw_options = [value.strip() for value in raw]

    @property
    def option_values(self):
        """Values to re-render: what the user typed, padded to MAX_OPTIONS rows."""
        values = self.raw_options[:MAX_OPTIONS]
        return values + [""] * (MAX_OPTIONS - len(values))

    def clean(self):
        cleaned = super().clean()
        if self.daily_limit is not None and self.daily_count >= self.daily_limit:
            raise forms.ValidationError(
                f"Bugün en fazla {self.daily_limit} anket açabilirsin. Yarın tekrar dene.",
                code="daily_limit",
            )

        options = [value for value in self.raw_options if value]
        if len(options) < MIN_OPTIONS:
            self.option_errors.append("En az 2 seçenek gerekli.")
        elif len(options) > MAX_OPTIONS:
            self.option_errors.append("En fazla 5 seçenek ekleyebilirsin.")
        if any(len(value) > OPTION_MAX_LENGTH for value in options):
            self.option_errors.append(f"Her seçenek en fazla {OPTION_MAX_LENGTH} karakter olabilir.")
        folded = [value.casefold() for value in options]
        if len(set(folded)) != len(folded):
            self.option_errors.append("Aynı seçeneği iki kez yazmışsın.")

        cleaned["options"] = options
        return cleaned

    def is_valid(self):
        # Option errors are shown next to the option rows, not with the non-field errors.
        return super().is_valid() and not self.option_errors
