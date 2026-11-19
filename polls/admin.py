from django.contrib import admin

from .models import Option, Poll, Vote


class OptionInline(admin.TabularInline):
    model = Option
    extra = 0
    max_num = 5
    fields = ("position", "text", "vote_count")
    readonly_fields = ("vote_count",)


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ("question", "author", "status", "total_votes", "created_at")
    list_filter = ("status",)
    search_fields = ("question", "public_id", "author__username")
    readonly_fields = ("public_id", "total_votes", "created_at")
    list_select_related = ("author",)
    inlines = [OptionInline]


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("poll", "option", "user", "created_at")
    list_select_related = ("poll", "option", "user")
    raw_id_fields = ("poll", "option", "user")
