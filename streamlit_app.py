# ==============================================================================
#  NİHAİ KOD (v46.0): Haber Zenginleştirme Protokolü ve Dinamik Filtreleme
# ==============================================================================
import streamlit as st
import pandas as pd
import feedparser
from openai import OpenAI
import json
import re
from urllib.parse import quote
import folium
from streamlit_folium import folium_static
import requests
from rapidfuzz import fuzz
import time

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE YAPILANDIRMA
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Akıllı Hasar Tespiti")
st.title("🛰️ Akıllı Endüstriyel Hasar Tespit Motoru")

# --- API Bağlantıları
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# --- Sabitler
RISK_TYPES = {
    "Yangın": '"yangın"',
    "Patlama": '"patlama"',
    "Endüstriyel Kaza": '"endüstriyel kaza" OR "iş kazası"',
    "Kimyasal Sızıntı": '"kimyasal sızıntı" OR "gaz sızıntısı"',
    "Yapısal Çökme": '"çökme" OR "göçük"',
    "Doğal Afet Hasarı": '"sel" OR "fırtına" OR "deprem hasarı"'
}

# ------------------------------------------------------------------------------
# 2. VERİ TOPLAMA VE ZENGİNLEŞTİRME FONKSİYONLARI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900)
def get_initial_events(selected_risks):
    """Seçilen risk tiplerine göre Google News'ten ilk olay listesini çeker ve tekilleştirir."""
    if not selected_risks: return []
    
    locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo" OR "tesis"'
    risk_query = " OR ".join([RISK_TYPES[risk] for risk in selected_risks])
    q = f'({locations}) AND ({risk_query})'
    rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return []
        
        sorted_entries = sorted(feed.entries, key=lambda e: getattr(e, 'published_parsed', time.gmtime(0)), reverse=True)
        
        unique_articles, seen_headlines = [], []
        for entry in sorted_entries:
            headline = entry.title.split(" - ")[0].strip()
            if not any(fuzz.ratio(headline, seen) > 80 for seen in seen_headlines):
                summary = re.sub('<[^<]+?>', '', entry.get('summary', ''))
                unique_articles.append({
                    "headline": headline, "snippet": summary[:150] + '...',
                    "full_summary": summary, "url": entry.link
                })
                seen_headlines.append(headline)
        return unique_articles[:40]
    except Exception as e:
        st.sidebar.error(f"RSS Hatası: {e}"); return []

@st.cache_data(ttl=3600)
def enrich_event_with_targeted_search(headline):
    """Seçilen bir haber başlığı ile yeni ve hedefli bir Google araması yaparak ek kanıtlar toplar."""
    try:
        # Anahtar kelimelerle daha isabetli bir arama yap
        search_query = f'"{headline}"'
        rss_url = f"https://news.google.com/rss/search?q={quote(search_query)}&hl=tr&gl=TR&ceid=TR:tr"
        feed = feedparser.parse(rss_url)
        
        context = "ÇAPRAZ KONTROL İÇİN EK KANITLAR:\n\n"
        for entry in feed.entries[:5]: # En alakalı ilk 5 sonucu al
            title = entry.title
            summary = re.sub('<[^<]+?>', '', entry.get('summary', ''))
            context += f"- Kaynak Başlık: {title}\n- Kaynak Özet: {summary}\n\n"
        return context
    except Exception:
        return "Ek kanıt toplanamadı."

# ------------------------------------------------------------------------------
# 3. İKİ AŞAMALI AI ANALİZ FONKSİYONLARI (SIFIR HALÜSİNASYON ODAKLI)
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def run_detective_ai(_client, original_summary, enriched_context):
    """Aşama 1: Zenginleştirilmiş veriyi analiz ederek kimlik tespiti yapar."""
    prompt = f"""
    Sen, kanıta dayalı çalışan bir OSINT (Açık Kaynak İstihbarat) uzmanısın. Halüsinasyona sıfır toleransın var. SANA VERİLEN METİNLERİN DIŞINA ASLA ÇIKMA.

    GÖREV: Sana bir ana haber özeti ve bu olayla ilgili yapılmış gerçek zamanlı bir Google aramasından 5 ek kanıt metni veriyorum. Bu istihbarat paketini analiz ederek olayın yaşandığı tesisin TİCARİ UNVANINI ve konumunu bul. Cevaplarını doğrudan bu metinlerden alıntılarla destekle.

    İSTİHBARAT PAKETİ:
    ---
    ANA HABER ÖZETİ: {original_summary}
    ---
    {enriched_context}
    ---

    ÇIKTI (Sadece JSON ver, yorum ekleme):
    {{
      "tesis_adi": "Metinler arasında geçen en olası ve teyitli ticari unvan.",
      "guven_skoru": "1-5 arası bir sayı. (5 = Birden çok kaynakta aynı isim geçiyorsa)",
      "kanit_zinciri": "Bu isme hangi metinden ulaştığını ALINTILAYARAK açıkla. Örneğin: 'ABC Kimya A.Ş. ismi, 'Kaynak Başlık:...' özetinde geçen '...ABC Kimya fabrikasında...' cümlesiyle teyit edilmiştir.'",
      "sehir_ilce": "Metinlerde geçen net şehir ve ilçe.",
      "tahmini_koordinat": {{"lat": "...", "lon": "..."}}
    }}
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.0)
        match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Dedektif AI Hatası: {e}"); return None

@st.cache_data(ttl=3600)
def run_analyst_ai(_client, full_context, facility_name):
    """Aşama 2: Teyit edilmiş kimlik ve zenginleştirilmiş veri üzerinden hasar analizi yapar."""
    prompt = f"""
    Sen, detay odaklı bir sigorta risk analistisin. Bir hasar olayının yaşandığı tesisin kimliği '{facility_name}' olarak teyit edildi.
    GÖREVİN: Sana verilen zenginleştirilmiş istihbarat metnini kullanarak, bu tesisle ilgili sigortacılık detaylarını çıkar. Her bilgiyi metinden bir kanıtla destekle.
    
    İSTİHBARAT METNİ: {full_context}

    ÇIKTI (Sadece JSON ver):
    {{
      "hasarin_nedeni_kaynakli": "Hasarın olası nedeni ve bu bilginin geçtiği cümle.",
      "hasarin_fiziksel_boyutu": "Hasarın fiziksel kapsamı (örn: '5000 m² depo alanı yandı').",
      "etkilenen_degerler": "Hasardan etkilenen spesifik varlıklar (makine, stok vb.).",
      "is_durmasi_etkisi": "Üretimin durup durmadığı hakkında bilgi ve kanıtı.",
      "yapilan_mudahale": "Olay yerine kimlerin, nasıl müdahale ettiğinin detayı.",
      "cevre_etkisi_metinsel": "Komşu tesislere veya çevreye olan etkiden bahsediliyor mu? Varsa alıntıla."
    }}
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Analist AI Hatası: {e}"); return None
        
# Coğrafi Zenginleştirme Fonksiyonları (v45 ile aynı, değişiklik yok)
@st.cache_data(ttl=86400)
def get_coords_from_google(api_key, address_text):
    if not api_key or not address_text: return None
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={quote(address_text)}&key={api_key}&language=tr&region=TR"
        response = requests.get(url); results = response.json().get('results', [])
        if results: return results[0].get('geometry', {}).get('location', {})
        return None
    except Exception: return None

@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon):
    if not all([api_key, lat, lon]): return []
    try:
        keywords = quote("fabrika|depo|sanayi|tesis|lojistik|antrepo")
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius=1000&keyword={keywords}&key={api_key}"
        response = requests.get(url, timeout=10)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "adres": p.get('vicinity'), "lat": p.get('geometry',{}).get('location',{}).get('lat'),"lng": p.get('geometry',{}).get('location',{}).get('lng')} for p in results[:10]]
    except Exception: return []

# ------------------------------------------------------------------------------
# 5. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------
if 'selected_risks' not in st.session_state:
    st.session_state.selected_risks = list(RISK_TYPES.keys())

col1, col2 = st.columns([1, 2], gap="large")

with col1:
    st.header("📰 Olay Akışı")
    st.session_state.selected_risks = st.multiselect(
        "İlgilendiğiniz Risk Tiplerini Seçin:",
        options=list(RISK_TYPES.keys()),
        default=st.session_state.selected_risks
    )
    
    if st.button("Filtrele ve Güncel Olayları Tara", type="primary", use_container_width=True):
        st.session_state.initial_events = get_initial_events(st.session_state.selected_risks)
        # Yeni tarama yapıldığında seçimi ve raporları temizle
        st.session_state.selected_event = None
        st.session_state.stage1_report = None
        st.session_state.stage2_report = None


    if 'initial_events' in st.session_state and st.session_state.initial_events:
        for event in st.session_state.initial_events:
            with st.container(border=True):
                st.markdown(f"**{event['headline']}**")
                st.caption(event['snippet'])
                if st.button("Bu Olayı Analiz Et", key=event['url'], use_container_width=True):
                    st.session_state.selected_event = event
                    st.session_state.stage1_report = None
                    st.session_state.stage2_report = None
                    st.rerun()
    elif 'initial_events' in st.session_state:
        st.warning("Seçilen filtrelere uygun bir olay bulunamadı.")


with col2:
    st.header("📝 Analiz Paneli")
    if not st.session_state.get('selected_event'):
        st.info("Lütfen sol panelden analiz etmek için bir olay seçin ve 'Bu Olayı Analiz Et' butonuna tıklayın.")
    else:
        event = st.session_state.selected_event
        st.subheader(event['headline'])
        
        # --- AŞAMA 1 BUTONU ---
        if st.button("1. Adım: Haberi Zenginleştir ve Kimliği Tespit Et", type="primary", use_container_width=True):
            if not client: st.error("Lütfen Grok API anahtarını ekleyin.")
            else:
                with st.spinner("Hedefli Google Taraması yapılıyor ve kanıtlar toplanıyor..."):
                    enriched_context = enrich_event_with_targeted_search(event['headline'])
                    st.session_state.enriched_context = enriched_context

                with st.spinner("Dedektif AI, zenginleştirilmiş veriyi analiz ediyor..."):
                    st.session_state.stage1_report = run_detective_ai(client, event['full_summary'], enriched_context)
                    st.session_state.stage2_report = None

        # --- AŞAMA 1 SONUÇLARI VE AŞAMA 2 BUTONU ---
        if st.session_state.get('stage1_report'):
            s1_report = st.session_state.stage1_report
            st.markdown("---")
            
            with st.expander("Zenginleştirilmiş İstihbarat Metni (AI'ın Gördüğü Veri)", expanded=False):
                st.text(st.session_state.get('enriched_context', ''))

            col_title, col_score = st.columns([3, 1])
            col_title.subheader(f"Tespit Edilen Kimlik: {s1_report.get('tesis_adi', 'Bulunamadı')}")
            col_score.metric("Güven Skoru", f"{s1_report.get('guven_skoru', 0)}/5")
            st.info(f"**Kanıt Zinciri:** {s1_report.get('kanit_zinciri', 'N/A')}")
            
            is_identified = s1_report.get('tesis_adi') not in [None, "Tespit Edilemedi", "Bulunamadı"]
            if is_identified:
                if st.button("2. Adım: Detaylı Hasar Analizi Yap", use_container_width=True):
                    full_context = f"ANA HABER:{event['full_summary']}\n\n{st.session_state.enriched_context}"
                    with st.spinner(f"Analist AI çalışıyor: '{s1_report.get('tesis_adi')}' için hasar detayları çıkarılıyor..."):
                        st.session_state.stage2_report = run_analyst_ai(client, full_context, s1_report.get('tesis_adi'))

        # --- AŞAMA 2 SONUÇLARI VE HARİTA ---
        if st.session_state.get('stage2_report'):
            s2_report = st.session_state.stage2_report
            st.markdown("---")
            st.subheader("Derinlemesine Hasar Analizi")
            c1, c2 = st.columns(2)
            c1.warning(f"**Hasarın Nedeni:** {s2_report.get('hasarin_nedeni_kaynakli', 'N/A')}")
            c2.warning(f"**Fiziksel Boyutu:** {s2_report.get('hasarin_fiziksel_boyutu', 'N/A')}")
            c1.info(f"**Etkilenen Değerler:** {s2_report.get('etkilenen_degerler', 'N/A')}")
            c2.info(f"**İş Durması Etkisi:** {s2_report.get('is_durmasi_etkisi', 'N/A')}")
            st.success(f"**Yapılan Müdahale:** {s2_report.get('yapilan_mudahale', 'N/A')}")
            st.error(f"**Metinsel Çevre Analizi:** {s2_report.get('cevre_etkisi_metinsel', 'N/A')}")
            
            # Harita ve Komşu Tesisler
            st.subheader("Olay Yeri Haritası ve Çevresel Riskler")
            final_coords = None
            s1_report = st.session_state.stage1_report
            if s1_report.get('tahmini_koordinat') and s1_report['tahmini_koordinat'].get('lat'):
                try: final_coords = {'lat': float(s1_report['tahmini_koordinat']['lat']), 'lng': float(s1_report['tahmini_koordinat']['lon'])}
                except (ValueError, TypeError): final_coords = None
            
            if not final_coords:
                with st.spinner("Google Geocoding ile kesin konum aranıyor..."):
                    address = f"{s1_report.get('tesis_adi')}, {s1_report.get('sehir_ilce')}"
                    final_coords = get_coords_from_google(google_api_key, address)
            
            if final_coords:
                neighbors = find_neighboring_facilities(google_api_key, final_coords['lat'], final_coords['lng'])
                m = folium.Map(location=[final_coords['lat'], final_coords['lng']], zoom_start=14)
                folium.TileLayer('CartoDB positron').add_to(m)
                folium.Marker([final_coords['lat'], final_coords['lng']], popup=f"<b>{s1_report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                for n in neighbors:
                    if n.get('lat') and n.get('lng'): folium.Marker([n['lat'], n['lng']], popup=f"<b>{n['tesis_adi']}</b>", icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                folium_static(m, height=400)
                if neighbors: st.dataframe(pd.DataFrame(neighbors)[['tesis_adi', 'adres']])
            else:
                st.warning("Olay konumu harita üzerinde gösterilemedi.")
