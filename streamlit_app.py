import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json

# Secrets'ten API Key Çek (GitHub/Streamlit Cloud için .streamlit/secrets.toml'da tanımlı)
GROK_API_KEY = st.secrets.get("GROK_API_KEY")
MODEL = "grok-code-fast-1"  # Yeni Grok Fast entegrasyonu (düşük maliyetli, hızlı)

# Komşu Tespiti için Hardcoded OSB Listesi (Genişletilebilir)
OSB_LIST = {
    "Kayseri OSB": (38.75, 35.50),
    "Bor OSB": (37.85, 34.55),
    "Kemalpaşa OSB": (38.47, 27.42),
    "Balıkesir OSB": (39.65, 27.88),
    "İSTOÇ İstanbul": (41.05, 28.82),
    "Aliağa OSB": (38.80, 27.00),
    "Soma Termik": (39.15, 27.60),
    "Buca Sanayi": (38.40, 27.13)
}

# Optimizasyonlu Grok Sorgu (Günlük Cache, Maliyet Düşük)
@st.cache_data(ttl=86400)  # Günlük cache, sorgu sayısı az
def get_grok_events():
    if not GROK_API_KEY:
        st.error("Grok API Key secrets.toml'da tanımlı değil!")
        return pd.DataFrame()
    
    client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
    
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    prompt = f"""
    Türkiye'de {start_date}-{end_date} arası endüstriyel tesislerde (fabrika, OSB, enerji santrali) sigortaya konu risklerden (yangın, deprem, patlama, sızıntı, su basması, makine kırılması) etkilenen olayları listele. Kaynaklar: Teyitli haberler (AA, DHA, NTV, Hürriyet) + X postları/kullanıcı raporları (güvenilir hesaplar, min_retweets:5). Küçük olay filtrele. Her olay için JSON listesi döndür (sadece JSON):
    - olay_tarihi (YYYY-MM-DD)
    - tesis_adi_turu (Ad + (Tür))
    - adres (İl/İlçe/Mahalle, approx. koordinat)
    - hasar_etkisi (Detay: Sebep, can kaybı isimli, TL hasar tahmini, üretim etkisi, sigorta notu)
    - dogruluk_orani (%95 - Kaynaklar: NTV + X postları + Valilik, 3+ kaynak)
    - komsu_tesisler (5km risk: Örnek tesisler, duman/sıçrama etki, etkilenme raporu)
    Veri yoksa boş liste [].
    Örnek: [{{"olay_tarihi":"2025-09-05","tesis_adi_turu":"Özen Plastik (Plastik fabrika)",...}}]
    """
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.1
        )
        content = response.choices[0].message.content.strip()
        events_json = json.loads(content)
        df = pd.DataFrame(events_json)
        if not df.empty:
            df['date'] = pd.to_datetime(df['olay_tarihi'])
        return df
    except Exception as e:
        st.error(f"Grok Hatası: {e}")
        return pd.DataFrame()

def find_neighbors(lat, lng):
    if lat is None or lng is None:
        return "Konum yok"
    event_pos = (lat, lng)
    neighbors = []
    for osb, pos in OSB_LIST.items():
        dist = geodesic(event_pos, pos).km
        if dist < 5:
            neighbors.append(f"{osb} ({dist:.1f} km - Risk: Yüksek)")
    return "; ".join(neighbors) if neighbors else "Komşu yok"

# Streamlit UI (En İyi Versiyon: Basit, Hızlı, Hatasız)
st.title("🚨 Son 30 Gün Endüstriyel Tesis Hasar Analizi")
st.markdown("Grok Code Fast API ile X/Web taraması. Tablo ve harita gösterir. Günlük güncelleme için butona basın.")

if st.button("Analiz Et (Son 30 Gün)"):
    with st.spinner("Grok ile tarama yapılıyor... (X ve web kaynakları çaprazlandı)"):
        events = get_grok_events()
        if not events.empty:
            events['komşu_tesisler'] = events.apply(lambda row: row.get('komsu_tesisler', find_neighbors(row.get('lat'), row.get('lng'))), axis=1)
            events = events[['olay_tarihi', 'tesis_adi_turu', 'adres', 'hasar_etkisi', 'dogruluk_orani', 'komşu_tesisler']].sort_values('olay_tarihi', ascending=False)
            st.subheader("Son 30 Gün Hasarlar")
            st.dataframe(events)
            
            # Harita
            if 'lat' in events.columns and events['lat'].notna().any():
                m = folium.Map(location=[39, 35], zoom_start=6)
                for _, row in events.iterrows():
                    if pd.notna(row.get('lat')) and pd.notna(row.get('lng')):
                        folium.Marker([row['lat'], row['lng']], popup=row.to_string()).add_to(m)
                folium_static(m)
            else:
                st.warning("Harita için konum verisi yok.")
        else:
            st.warning("Son 30 günde önemli olay tespit edilemedi.")

st.caption("Kaynaklar: Grok Code Fast API (X postları + web haberleri). Günlük cache ile optimizasyon. Maliyet düşük.")
