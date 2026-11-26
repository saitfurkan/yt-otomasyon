# Son Tanık: Nasıl kullanılır

1. Senaryoyu Claude hazırlar, `hazir/` klasörüne `01-ad.md` olarak koyar.
2. Telegram'da botuna yaz: `/senaryo 01-ad`
3. Senaryoyu oku, sesli mesaj(lar) olarak gönder (kısa parçalar olabilir).
4. `/bitti` yaz.
5. Bot 30-40 dakikada ana videoyu, kapağı ve 3 Shorts'u üretir, YouTube'a zamanlanmış yükler ve Telegram'dan haber verir.

Açılış sesi (bir kez): "Karar verilmeden önce, son sözü tanık söyler." cümlesini sesli mesaj olarak gönder, mesajın altına `ident` yaz.

Gerekli GitHub Secrets: TELEGRAM_BOT_TOKEN, PIXABAY_API_KEY (veya PEXELS_API_KEY), CF_ACCOUNT_ID, CF_API_TOKEN, GEMINI_API_KEY, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN.
