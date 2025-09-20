# ==============================================================================
#      NİHAİ KOD (v19.0): v4 Tabanlı, Gelişmiş ve Stabil Sürüm
# ==============================================================================
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re
import requests

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Endüstriyel Hasar Analiz Paneli")
st.title("🛰️ Akıllı Endüstriyel Hasar Analiz Paneli")

# --- API Konfigürasyonları ---
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

# ANA ANALİZ MOTORU: AI'dan bütünleşik ve detaylı bir rapor ister.
@st.cache_data(ttl=1800) # 30 dakikalık cache
def get_industrial_events_from_ai(_client):
    # GÜNCELLEME: v17'deki en gelişmiş ve zorlayıcı prompt'u v4'ün yapısına entegre ettik.
    prompt = f"""
    Sen, Türkiye odaklı çalışan, elit seviye bir sigorta ve risk istihbarat analistisin. Görevinin merkezinde doğruluk, kanıt ve derinlemesine detay vardır. Yüzeysel özetler kabul edilemez.

    ANA GÖREVİN: Web'i (haber ajansları) ve X'i (Twitter) aktif olarak tarayarak Türkiye'de son 15 gün içinde meydana gelmiş, sigortacılık açısından en önemli **en fazla 10 adet** endüstriyel veya enerji tesisi hasar olayını bul.

    KRİTİK TALİMATLAR:
    1.  **DERİNLEMESİNE BİLGİ TOPLA:** Sadece başlıkları değil, bulduğun haber metinlerinin ve X paylaşımlarının içeriğini OKU.
    2.  **KAYNAK GÖSTERME ZORUNLUDUR:** Özellikle tesis adı ve hasar tahmini gibi kritik bilgiler için kaynağını belirt.
    3.  **TEKİLLEŞTİR:** Farklı kaynaklardaki aynı olayı tek bir zengin rapor altında birleştir.

    ÇIKTI FORMATI: Bulgularını, her bir olay için aşağıdaki detaylı anahtarlara sahip bir JSON nesnesi içeren bir JSON dizisi olarak döndür.
    
    JSON NESNE YAPISI:
    - "tesis_adi": Yüksek doğrulukla tespit edilmiş ticari unvan.
    - "tesis_adi_kaynak": Tesis adını hangi kaynaklara (X, haber ajansı vb.) dayanarak bulduğunun açıklaması.
    - "sehir_ilce": Olayın yaşandığı yer.
    - "olay_tarihi": Olayın tarihi (YYYY-AA-GG formatında).
    - "hasarin_nedeni": Olayın tahmini nedeni (Örn: "Elektrik panosundaki kısa devre").
    - "hasarin_fiziksel_boyutu": Hasarın fiziksel etkisi (Örn: "Fabrikanın 5000 metrekarelik depo bölümü tamamen yandı.").
    - "hasar_tahmini_parasal": Parasal hasar bilgisi ve kaynağı.
    - "guncel_durum": Üretim durdu mu, soruşturma başladı mı gibi en son bilgiler.
    - "latitude": Olay yerinin enlemi (Sadece sayı, tahmin de olabilir).
    - "longitude": Olay yerinin boylamı (Sadece sayı, tahmin de olabilir).
    - "kaynak_urller": Kullandığın tüm haber ve X linklerinin listesi (dizi).
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=8192, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            df = pd.DataFrame(json.loads(match.group(0)))
            if not df.empty:
                df['olay_tarihi'] = pd.to_datetime(df['olay_tarihi'], errors='coerce')
                df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
                df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
                return df.sort_values(by='olay_tarihi', ascending=False).reset_index(drop=True)
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Ana Analiz Motorunda Hata: {e}"); return pd.DataFrame()

# COĞRAFİ ZENGİNLEŞTİRME
@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=500):
    if not api_key or pd.isna(lat) or pd.isna(lon): return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "konum": p.get('vicinity')} for p in results[:10]]
    except Exception as e:
        st.warning(f"Google Places API hatası: {e}"); return []

# ------------------------------------------------------------------------------
# 3. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
st.sidebar.header("Analiz Kontrolü")
run_analysis = st.sidebar.button("Son Olayları Analiz Et", type="primary", use_container_width=True)
st.sidebar.caption("Web'i ve X'i tarayarak en güncel ve önemli olayları bulur, detaylı analiz eder.")

if 'events_df' not in st.session_state:
    st.session_state.events_df = pd.DataFrame()

if run_analysis:
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()

    with st.spinner("Ana Analiz Motoru çalıştırılıyor... Bu işlem birkaç dakika sürebilir."):
        # 1. AI'dan temel raporu al
        df = get_industrial_events_from_ai(client)
        
        # 2. Raporu Google Maps verisiyle zenginleştir
        if not df.empty:
            df['komsu_tesisler_harita'] = df.apply(
                lambda row: find_neighboring_facilities(google_api_key, row['latitude'], row['longitude']),
                axis=1
            )
        st.session_state.events_df = df

if not st.session_state.events_df.empty:
    df = st.session_state.events_df
    st.success(f"{len(df)} adet önemli olay raporu oluşturuldu.")
    
    # GÜNCELLEME: Raporları daha okunaklı bir formatta, tek tek göster
    for index, row in df.iterrows():
        st.markdown("---")
        st.subheader(f"{row.get('tesis_adi', 'İsimsiz Tesis')} - {row.get('sehir_ilce', 'Konum Yok')}")
        st.caption(f"Olay Tarihi: {row.get('olay_tarihi', pd.NaT).strftime('%d %B %Y') if pd.notna(row.get('olay_tarihi')) else 'Bilinmiyor'} | Tesis Adı Kaynağı: {row.get('tesis_adi_kaynak', 'N/A')}")

        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Hasarın Nedeni:** {row.get('hasarin_nedeni', 'N/A')}")
        with col2:
            st.error(f"**Güncel Durum:** {row.get('guncel_durum', 'N/A')}")

        st.warning(f"**Hasarın Fiziksel Boyutu:** {row.get('hasarin_fiziksel_boyutu', 'N/A')}")
        st.metric(label="Parasal Hasar Tahmini", value=row.get('hasar_tahmini_parasal', 'Tespit Edilemedi'))

        with st.expander("Harita, Komşu Tesisler ve Kaynakları Görüntüle"):
            lat, lon = row.get('latitude'), row.get('longitude')
            if pd.notna(lat) and pd.notna(lon):
                m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB positron")
                folium.Marker([lat, lon], popup=f"<b>{row.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                folium_static(m, height=400)
            else:
                st.info("Rapor, harita çizimi için yeterli koordinat bilgisi içermiyor.")

            st.markdown("##### Komşu Tesisler (Google Harita Verisi)")
            neighbors_data = row.get('komsu_tesisler_harita', [])
            if neighbors_data:
                st.table(pd.DataFrame(neighbors_data))
            else:
                st.write("Yakın çevrede harita servisinden tesis tespit edilemedi veya koordinat bilgisi yoktu.")
            
            st.markdown("##### Kaynak Linkler")
            kaynaklar = row.get('kaynak_urller', [])
            if kaynaklar:
                for link in kaynaklar:
                    st.markdown(f"- {link}")
            else:
                st.write("Kaynak link bulunamadı.")
else:
    st.info("Başlamak için lütfen kenar çubuğundaki 'Son Olayları Analiz Et' butonuna tıklayın.")
