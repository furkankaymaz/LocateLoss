# ==============================================================================
#      NİHAİ KOD (v9.0): Güvenilir Veri Kaynağı Entegrasyonu
# ==============================================================================
import streamlit as st
import pandas as pd
from datetime import datetime
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re
import feedparser # Haberleri çekmek için yeni kütüphane
from urllib.parse import quote # URL'de Türkçe karakterleri kodlamak için

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------

st.set_page_config(layout="wide", page_title="Endüstriyel Hasar Analizi")
st.title("🚨 Akıllı Endüstriyel Hasar Takip Platformu")
st.markdown(f"**Son Güncelleme:** {datetime.now().strftime('%d %B %Y, %H:%M')}")
st.markdown("---")

API_SERVICE = "Grok_XAI"
API_CONFIGS = {"Grok_XAI": {"base_url": "https://api.x.ai/v1", "model": "grok-4-fast-reasoning"}}
SELECTED_CONFIG = API_CONFIGS[API_SERVICE]
API_KEY_NAME = "GROK_API_KEY"
api_key = st.secrets.get(API_KEY_NAME)

# ------------------------------------------------------------------------------
# 2. API BAĞLANTI KONTROLÜ
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def validate_api_key(key, base_url, model):
    if not key: return False, "API Anahtarı bulunamadı.", "Lütfen Streamlit Secrets ayarlarınızı kontrol edin."
    try:
        OpenAI(api_key=key, base_url=base_url).chat.completions.create(model=model, messages=[{"role": "user", "content": "Test"}], max_tokens=10)
        return True, f"API bağlantısı başarılı: **{API_SERVICE} ({model})**", ""
    except Exception as e:
        return False, "API Bağlantı Hatası.", f"Detay: {e}"

st.sidebar.subheader("⚙️ API Bağlantı Durumu")
is_valid, status_message, solution_message = validate_api_key(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])
if is_valid:
    st.sidebar.success(f"✅ {status_message}")
else:
    st.sidebar.error(f"❌ {status_message}"); st.sidebar.warning(solution_message); st.stop()

# ------------------------------------------------------------------------------
# 3. VERİ ÇEKME VE ANALİZ FONKSİYONLARI
# ------------------------------------------------------------------------------

# YENİ FONKSİYON: Google Haberler RSS üzerinden güvenilir şekilde olayları bulur.
@st.cache_data(ttl=900) # 15 dakikada bir haberleri yeniden kontrol et
def fetch_news_from_google_rss(limit=5):
    # Anahtar kelimelerle daha isabetli sonuçlar alıyoruz
    search_query = '"fabrika yangını" OR "sanayi sitesinde yangın" OR "endüstriyel patlama" OR "OSB yangın"'
    encoded_query = quote(search_query)
    
    # Google News Türkiye için RSS URL'i
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            st.warning("Google Haberler RSS akışından herhangi bir sonuç bulunamadı.")
            return []
            
        events = []
        for entry in feed.entries[:limit]:
            events.append({
                "headline": entry.title,
                "url": entry.link
            })
        return events
    except Exception as e:
        st.error(f"Haber akışı çekilirken bir hata oluştu: {e}")
        return []

# ANALİZ FONKSİYONU (Değişiklik yok, hala aynı görevi yapıyor)
@st.cache_data(ttl=86400)
def analyze_single_event(key, base_url, model, headline, url):
    client = OpenAI(api_key=key, base_url=base_url)
    prompt = f"""
    Sen bir sigorta hasar eksperisin. Sana verilen şu haberi analiz et: "{headline}" ({url}).
    GÖREVİN: X (Twitter) ve diğer haber ajanslarını kullanarak bu tek olayı çapraz kontrol et ve aşağıda belirtilen anahtarlara sahip TEK BİR JSON nesnesi olarak detaylı bir rapor oluştur.
    ÖNCELİK: Haberde veya X paylaşımlarında geçen **firma adını** tam ve doğru olarak tespit et. Karmaşık teyitlere (ticaret sicil vb.) gerek yok, sadece kaynaklarda belirtilen ismi bul.

    JSON ÇIKTI ANAHTARLARI:
    - "olay_tarihi_saati"
    - "guncel_durum"
    - "tesis_adi_ticari_unvan"
    - "sehir_ilce"
    - "olay_tipi_ozet"
    - "hasar_tahmini" (nesne: "tutar_araligi_tl", "kaynak", "aciklama")
    - "can_kaybi_ve_yaralilar" (nesne: "durum", "detaylar")
    - "cevre_tesis_analizi" (nesneler dizisi: "tesis_adi", "risk_faktoru", "aciklama")
    - "kaynak_linkleri" (metin dizisi)
    - "gorsel_linkleri" (metin dizisi)
    - "latitude"
    - "longitude"

    SON KONTROL: Raporu oluşturduktan sonra, tüm alanların (özellikle firma adı ve hasar tahmini) haber kaynaklarıyla tutarlı olduğunu son bir kez kontrol et.
    """
    try:
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        else:
            match_markdown = re.search(r'```json\s*(\{.*\})\s*```', content, re.DOTALL)
            if match_markdown:
                return json.loads(match_markdown.group(1))
        st.warning("Detaylı analizden geçerli bir JSON nesnesi alınamadı. Ham yanıt aşağıdadır:")
        st.code(content)
        return None
    except Exception as e:
        st.error(f"Detaylı analiz sırasında bir hata oluştu: {e}")
        return None

# ------------------------------------------------------------------------------
# 4. GÖRSEL ARAYÜZ
# ------------------------------------------------------------------------------
st.header("📈 En Son Tespit Edilen Hasarlar (Test Modu: Son 1 Olay)")

if st.button("En Son Olayı Bul ve Analiz Et", type="primary", use_container_width=True):
    # DEĞİŞİKLİK: Artık yapay zeka yerine güvenilir RSS kaynağını çağırıyoruz.
    with st.spinner("1. Aşama: Güvenilir haber kaynakları taranıyor..."):
        latest_events = fetch_news_from_google_rss(limit=1) # Test için sadece 1 haber alalım

    if not latest_events:
        st.info("Belirtilen anahtar kelimelerle (fabrika yangını vb.) son zamanlarda raporlanmış bir olay bulunamadı.")
    else:
        st.success(f"**1 adet potansiyel olay bulundu.** Şimdi yapay zeka ile derinlemesine analiz ediliyor...")

        event = latest_events[0]
        with st.spinner(f"2. Aşama: '{event.get('headline')}' başlıklı haber analiz ediliyor..."):
            event_details = analyze_single_event(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"], event.get('headline'), event.get('url'))

        if not event_details:
            st.error("Olay bulundu ancak yapay zeka analizi sırasında bir sorun oluştu veya analiz sonucu geçerli formatta değildi.")
        else:
            # Raporlama ve Haritalama bölümü eskisi gibi devam ediyor...
            events_df = pd.DataFrame([event_details])
            # ... (Bundan sonraki kod aynı kaldığı için kısaltılmıştır)
            
            # Önceki versiyondaki raporlama kodunun tamamı buraya gelecek.
            # Kodun geri kalanını bir önceki versiyondan kopyalayabilirsiniz.
            # (Streamlit arayüz, expander, harita vb. kısımlar)
            events_df['olay_tarihi_saati'] = pd.to_datetime(events_df.get('olay_tarihi_saati'), errors='coerce')
            st.subheader("Analiz Edilen Son Olay Raporu")

            row = events_df.iloc[0].fillna('')
            
            # Tarih formatlaması için kontrol
            tarih_str = "Tarih Belirtilmemiş"
            if pd.notna(row['olay_tarihi_saati']):
                tarih_str = row['olay_tarihi_saati'].strftime('%d %b %Y, %H:%M')

            with st.expander(f"**{tarih_str} - {row['tesis_adi_ticari_unvan']} ({row['sehir_ilce']})**", expanded=True):
                st.subheader(row['olay_tipi_ozet'])
                st.info(f"**Güncel Durum:** {row['guncel_durum']}")

                gorsel_linkleri = row.get('gorsel_linkleri')
                if gorsel_linkleri and isinstance(gorsel_linkleri, list) and gorsel_linkleri[0]:
                    st.image(gorsel_linkleri[0], caption="Olay Yerinden Görüntü", use_column_width=True)

                st.markdown("---")
                col1, col2 = st.columns(2)
                with col1:
                    hasar_tahmini = row.get('hasar_tahmini', {})
                    st.markdown(f"##### Hasar Tahmini: `{hasar_tahmini.get('tutar_araligi_tl', 'Belirtilmemiş')}`")
                    st.caption(f"Kaynak: {hasar_tahmini.get('kaynak', 'Bilinmiyor')}")
                    st.write(hasar_tahmini.get('aciklama', ''))

                    can_kaybi = row.get('can_kaybi_ve_yaralilar', {})
                    if can_kaybi and can_kaybi.get('durum', 'Bilinmiyor').lower() == 'evet':
                        st.error(f"**Can Kaybı / Yaralı:** {can_kaybi.get('detaylar', 'Detay belirtilmemiş.')}")

                with col2:
                    st.markdown("##### Çevre Tesisler İçin Risk Analizi")
                    cevre_tesis_data = row.get('cevre_tesis_analizi',[])
                    if cevre_tesis_data:
                        st.table(pd.DataFrame(cevre_tesis_data))
                    else:
                        st.write("Çevre tesis riski belirtilmemiş.")

                st.markdown("---"); st.markdown("##### Tıklanabilir Kaynak Linkleri")
                kaynak_linkleri = row.get('kaynak_linkleri', [])
                if kaynak_linkleri:
                    links_md = "".join([f"- [{link.split('//')[-1].split('/')[0]}]({link})\n" for link in kaynak_linkleri])
                    st.markdown(links_md)
                else:
                    st.write("Kaynak link bulunamadı.")

            st.header("🗺️ Olay Yeri İncelemesi")
            # Enlem/boylam değerlerini sayısal yapmaya çalış, hatalı olanı NaN yap
            events_df['latitude'] = pd.to_numeric(events_df['latitude'], errors='coerce')
            events_df['longitude'] = pd.to_numeric(events_df['longitude'], errors='coerce')
            map_df = events_df.dropna(subset=['latitude', 'longitude'])
            
            if not map_df.empty:
                row = map_df.iloc[0]
                map_center = [row['latitude'], row['longitude']]
                m = folium.Map(location=map_center, zoom_start=15, tiles="CartoDB positron")

                popup_html = f"<h4>{row['tesis_adi_ticari_unvan']}</h4><b>Durum:</b> {row['guncel_durum']}"
                iframe = folium.IFrame(popup_html, width=250, height=100)
                popup = folium.Popup(iframe, max_width=250)

                folium.Marker(
                    location=[row['latitude'], row['longitude']],
                    popup=popup,
                    tooltip=row['tesis_adi_ticari_unvan'],
                    icon=folium.Icon(color='red', icon='fire')
                ).add_to(m)

                folium_static(m, width=None, height=500)
            else:
                st.warning("Olay için geçerli bir konum (enlem/boylam) bilgisi bulunamadığından harita gösterilemiyor.")
