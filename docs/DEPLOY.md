# Deploy — Vercel + Supabase

Uygulama Vercel'de tek bir Python fonksiyonu olarak çalışır (Django sıfır konfigürasyon),
veritabanı Supabase Postgres'tir. Vercel `manage.py`'yi bulur, `WSGI_APPLICATION`'dan giriş
noktasını çıkarır ve `STATIC_ROOT` tanımlı olduğu için build sırasında `collectstatic`'i
kendisi çalıştırır. Sarmalayıcı dosya, rewrite kuralı veya build script'i **yok**.

## Repodaki deploy dosyaları

| Dosya | Neden |
|---|---|
| `.python-version` | Vercel Python 3.12–3.14 destekliyor (3.15 yok). Canlıda **3.14** kullanılır; yerelde 3.15 sorunsuz. |
| `vercel.json` | Sadece fonksiyon bölgesi: `fra1` (Frankfurt), Supabase ile aynı bölge. |
| `requirements.txt` | Repo kökünde, sadece runtime bağımlılıkları. |

## 1. Ortam değişkenleri (Vercel → Project → Settings → Environment Variables)

Hepsi **Production** ve **Preview** ortamlarına eklenir. Değişkenler build sırasında da okunur
(`collectstatic` ayarları yükler; `DJANGO_SECRET_KEY` veya `VOTER_KEY_SALT` eksikse build düşer).

| Anahtar | Değer | Tür |
|---|---|---|
| `DJANGO_DEBUG` | `False` | düz |
| `DJANGO_ALLOWED_HOSTS` | `.vercel.app` | düz |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://<proje>.vercel.app` | düz |
| `DJANGO_SECRET_KEY` | aşağıdaki komutla üret | **sensitive** |
| `VOTER_KEY_SALT` | aşağıdaki komutla üret, yerelden farklı olsun | **sensitive** |
| `DATABASE_URL` | Supabase **Transaction pooler** adresi, port **6543** | **sensitive** |

Gizli değerleri üretmek için (her biri için ayrı çalıştır):

```bash
.venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(50))"
```

`DATABASE_URL` biçimi:
`postgresql://postgres.<PROJE_REF>:<PAROLA>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres`

- Doğrudan bağlantı (`db.<ref>.supabase.co`) **kullanılmaz**: sadece IPv6, Vercel'den erişilemez.
- `DATABASE_URL_DIRECT` (port 5432) Vercel'e **eklenmez**; sadece yerelde migration için.
- Değişken ekledikten/değiştirdikten sonra **yeniden deploy** gerekir (Deployments → Redeploy).

## 2. Migration'lar (her zaman yerelden)

Migration'lar Vercel build'inde **çalışmaz**. Model değiştiğinde, kodu push'lamadan **önce**
yerelden, session pooler (5432) üzerinden çalıştırılır. Transaction pooler'da migration patlar.

PowerShell:

```powershell
$env:DATABASE_URL = (Select-String -Path .env -Pattern '^DATABASE_URL_DIRECT=(.+)$').Matches[0].Groups[1].Value
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py lock_public_tables
Remove-Item Env:DATABASE_URL
```

bash:

```bash
DATABASE_URL="$DATABASE_URL_DIRECT" python manage.py migrate
DATABASE_URL="$DATABASE_URL_DIRECT" python manage.py lock_public_tables
```

`lock_public_tables` her `migrate`'ten sonra çalıştırılır: yeni tablolarda RLS'i açar ve
Supabase Data API rollerinin (`anon`, `authenticated`) yetkilerini kaldırır (şartname §15.7).

## 3. Deploy

Proje GitHub reposuna bağlı: `main`'e her push production deploy'u, diğer branch'ler preview
deploy'u tetikler. Elle tetiklemek için Vercel → Deployments → Redeploy.

Sıra önemli: **önce migrate, sonra push.** Yeni kod eski şemayla açılırsa 500 verir.

## 4. Deploy sonrası kontrol

- Ana sayfa açılıyor, CSS/JS `/static/...<hash>.css` adreslerinden 200 dönüyor.
- `/boyle-bir-sayfa-yok/` markalı 404 sayfasını gösteriyor (DEBUG kapalı).
- Kayıt → anket oluştur → oy ver akışı çalışıyor.
- Bir süre trafik yokken (soğuk başlangıç) ilk istek 500 vermiyor.

Hata olursa: Vercel → Deployments → ilgili deploy → **Build Logs** (build hatası) veya
**Logs** (çalışma zamanı hatası).

## 5. Yönetici hesabı

```powershell
$env:DATABASE_URL = (Select-String -Path .env -Pattern '^DATABASE_URL_DIRECT=(.+)$').Matches[0].Groups[1].Value
.venv\Scripts\python.exe manage.py createsuperuser
Remove-Item Env:DATABASE_URL
```

`admin` kullanıcı adı ayrılmış olduğu için kullanılamaz. Güçlü bir parola seç; panel
`/admin/` adresinde.

## Yerelde production benzeri çalıştırma

`.claude/launch.json` içindeki `django-prodlike-sqlite` yapılandırması `DEBUG=False` ile
SQLite üzerinde çalışır. Önce `collectstatic` gerekir (hash'li dosya adları için):

```powershell
$env:DJANGO_DEBUG='False'; .venv\Scripts\python.exe manage.py collectstatic --noinput
```

`vercel dev` Vercel CLI gerektirir (`npm i -g vercel`); bu projede kurulu değil.
