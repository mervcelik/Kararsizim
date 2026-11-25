from django.core.management.base import BaseCommand
from django.db import connection

# Supabase exposes the public schema through its Data API (PostgREST) to the anon and
# authenticated roles. Django connects as the table owner, which bypasses RLS, so enabling
# RLS without policies and revoking grants locks out the Data API without affecting the app.
EXTERNAL_ROLES = ("anon", "authenticated")
# Explicit "nobody via the Data API" policy. It grants nothing, but documents the intent
# and keeps Supabase's "RLS enabled, no policy" advisor quiet. RLS is never FORCEd:
# forcing it would apply these policies to the owner role and lock Django out.
DENY_POLICY = "data_api_deny_all"


class Command(BaseCommand):
    help = (
        "Supabase: public şemasındaki tüm tablolarda RLS açar, anon/authenticated için "
        "erişimi reddeden politika ekler ve bu rollerin yetkilerini kaldırır."
    )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write("PostgreSQL değil, atlandı.")
            return

        with connection.cursor() as cursor:
            cursor.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", [list(EXTERNAL_ROLES)])
            roles = [row[0] for row in cursor.fetchall()]

            cursor.execute(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity"
            )
            tables = [row[0] for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')

            policies_added = 0
            if roles:
                role_list = ", ".join(roles)
                cursor.execute(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT EXISTS ("
                    "  SELECT 1 FROM pg_policies p WHERE p.schemaname = 'public' "
                    "  AND p.tablename = c.relname AND p.policyname = %s)",
                    [DENY_POLICY],
                )
                for (table,) in cursor.fetchall():
                    cursor.execute(
                        f'CREATE POLICY {DENY_POLICY} ON public."{table}" '
                        f"AS PERMISSIVE FOR ALL TO {role_list} USING (false) WITH CHECK (false)"
                    )
                    policies_added += 1

                cursor.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role_list}")
                cursor.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role_list}")
                cursor.execute(
                    f"ALTER DEFAULT PRIVILEGES FOR ROLE {connection.settings_dict['USER'].split('.')[0]} "
                    f"IN SCHEMA public REVOKE ALL ON TABLES FROM {role_list}"
                )
                cursor.execute(
                    f"ALTER DEFAULT PRIVILEGES FOR ROLE {connection.settings_dict['USER'].split('.')[0]} "
                    f"IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {role_list}"
                )

        self.stdout.write(self.style.SUCCESS(
            f"RLS açılan tablo: {len(tables)}. Eklenen deny politikası: {policies_added}. "
            f"Yetkisi kaldırılan roller: {', '.join(roles) or 'yok'}."
        ))
