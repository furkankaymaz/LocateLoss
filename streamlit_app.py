# ==============================================================================
#      NİHAİ KOD (v8.4): f-string Formatlama Hatası Düzeltildi
# ==============================================================================
import streamlit as st
import pandas as pd
from datetime import datetime
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re

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
# 3. İKİ AŞAMALI VERİ ÇEKME FONKSİYONLARI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900)
def find_latest_events(key, base_url, model, event_count=5):
    client = OpenAI(api_key=key, base_url=base_url)
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    # DÜZELTME: f-string içindeki literal {} karakterleri {{}} olarak yazıldı.
    prompt = f"""
    Bugünün tarihi {current_date}. Görevin, Türkiye'de son 3 ay içinde meydana gelmiş önemli endüstriyel hasar olaylarını (fabrika yangını, kimyasal sızıntı, büyük patlama vb.) bulmaktır.
    
    Bana bulduğun olaylar arasından **en güncel {event_count} tanesinin** bir listesini ver.
    
    Öncelikli kaynakların X (Twitter) ve güvenilir ulusal haber ajansları (Anadolu Ajansı, Demirören Haber Ajansı vb.) olsun.
    
    Çıktıyı, her olay için "headline" (manşet) ve "url" (haber linki) anahtarlarını içeren bir JSON dizisi olarak döndür. Başka hiçbir açıklama veya metin ekleme. Sadece ham JSON dizisini ver.
    Örnek: [ {{"headline": "...", "url": "..."}} ]
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0.0
        )
        content = response.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        else:
            st.warning("API'den geçerli bir JSON dizisi alınamadı. Ham yanıt aşağıdadır:")
            st.code(content)
            return []
    except Exception as e:
        st.error(f"Olay arama sırasında bir hata oluştu: {e}")
        return []

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
    - "hasar_tahmini" (Bu bir nesne olmalı: "tutar_araligi_tl", "kaynak", "aciklama" alt anahtarlarıyla)
    - "can_kaybi_ve_yaralilar" (Bu bir nesne olmalı: "durum", "detaylar" alt anahtarlarıyla)
    - "cevre_tesis_analizi" (Bu bir nesneler dizisi olmalı: "tesis_adi", "risk_faktoru", "aciklama" alt anahtarlarıyla)
    - "kaynak_linkleri" (Bu bir metin dizisi olmalı)
    - "gorsel_linkleri" (Bu bir metin dizisi olmalı)
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
# 4. GÖRSEL ARAYÜZ (Bu bölümde değişiklik yapılmadı)
# ------------------------------------------------------------------------------
st.header("📈 En Son Tespit Edilen Hasarlar (Test Modu: Son 1 Olay)")

if st.button("En Son Olayı Bul ve Analiz Et", type="primary", use_container_width=True):
    with st.spinner("1. Aşama: Son olaylar taranıyor..."):
        latest_events = find_latest_events(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])

    if not latest_events:
        st.info("Belirtilen kriterlere uygun, raporlanacak bir endüstriyel olay tespit edilemedi.")
    else:
        st.success(f"**{len(latest_events)} adet potansiyel olay bulundu.** Şimdi en güncel olanı derinlemesine analiz ediliyor...")

        event = latest_events[0]
        event_details = analyze_single_event(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"], event.get('headline'), event.get('url'))

        if not event_details:
            st.error("Olay bulundu ancak detaylı analiz sırasında bir sorun oluştu veya analiz sonucu geçerli formatta değildi.")
        else:
            events_df = pd.DataFrame([event_details])
            events_df['olay_tarihi_saati'] = pd.to_datetime(events_df['olay_tarihi_saati'], errors='coerce')
            st.subheader("Analiz Edilen Son Olay Raporu")

            row = events_df.iloc[0].fillna('')
            with st.expander(f"**{row['olay_tarihi_saati'].strftime('%d %b %Y, %H:%M')} - {row['tesis_adi_ticari_unvan']} ({row['sehir_ilce']})**", expanded=True):
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
                    if can_kaybi.get('durum', 'Bilinmiyor').lower() == 'evet':
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
