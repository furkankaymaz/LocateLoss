diff --git a//dev/null b/README.md
index 0000000000000000000000000000000000000000..03eee7b2fca9d8f7660bdc489278103df017ef87 100644
--- a//dev/null
+++ b/README.md
@@ -0,0 +1,33 @@
+# LocateLoss Streamlit Uygulaması
+
+Bu depo, Grok Code Fast API'sini kullanarak Türkiye'deki endüstriyel tesislerde
+son 30 gün içerisinde yaşanan sigorta kapsamındaki olayları analiz eden bir
+Streamlit uygulaması içerir. Uygulama, olayları tablo halinde sunar ve uygun
+koordinat bilgisine sahip olayları etkileşimli bir haritada gösterir.
+
+## Kurulum
+
+1. Gerekli Python paketlerini kurun:
+
+   ```bash
+   pip install -r requirements.txt
+   ```
+
+2. Grok API anahtarınızı `streamlit secrets` aracılığıyla veya uygulama arayüzü
+   üzerinden girerek sağlayın. `secrets` kullanmak için proje klasörünüzdeki
+   `.streamlit/secrets.toml` dosyasına aşağıdaki formatta ekleme yapabilirsiniz:
+
+   ```toml
+   GROK_API_KEY = "grok_api_anahtariniz"
+   ```
+
+## Çalıştırma
+
+Uygulamayı başlatmak için aşağıdaki komutu çalıştırın:
+
+```bash
+streamlit run app.py
+```
+
+Butona tıklayarak Grok API üzerinden son 30 günün olaylarını çekebilir, sonuçları
+inceleyebilir ve harita üzerinde görüntüleyebilirsiniz.
