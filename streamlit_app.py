# ==============================================================================
#  NİHAİ KOD (v48.0): Akıllı Anahtar Kelime Motoru ile Güçlendirilmiş Tarayıcı
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
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
import time

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE YAPILANDIRMA
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="OSINT Hasar Tespiti")
st.title("🛰️ OSINT Tarayıcı & AI Doğrulayıcı Motoru v48")

# --- API Bağlantıları
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# --- Sabitler
RISK_TYPES = {"Yangın": '"yangın"', "Patlama": '"patlama"', "Endüstriyel Kaza": '"endüstriyel kaza"', "Kimyasal Sızıntı": '"kimyasal sızıntı"'}
CORPORATE_SUFFIXES = ['A.Ş.', 'Holding', 'Grup', 'Plastik', 'Kimya', 'Sanayi', 'Tekstil', 'Lojistik', 'Gıda', 'Fabrikası', 'Deposu', 'Tesisleri', 'Enerji', 'Üretim']

# ------------------------------------------------------------------------------
# 2. YENİ ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900)
def get_initial_events(selected_risks):
    """Sol panel için ilk haber listesini oluşturur."""
    if not selected_risks: return []
    locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo"'
    risk_query = " OR ".join([RISK_TYPES[risk] for risk in selected_risks])
    q = f'({locations}) AND ({risk_query})'; rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return []
        sorted_entries = sorted(feed.entries, key=lambda e: getattr(e, 'published_parsed', time.gmtime(0)), reverse=True)
        unique_articles, seen_headlines = [], []
        for entry in sorted_entries:
            headline = entry.title.split(" - ")[0].strip()
            if not any(fuzz.ratio(headline, seen) > 80 for seen in seen_headlines):
                summary = re.sub('<[^<]+?>', '', entry.get('summary', ''))
                unique_articles.append({"headline": headline, "snippet": summary[:150] + '...', "full_summary": summary, "url": entry.link})
                seen_headlines.append(headline)
        return unique_articles[:30]
    except Exception: return []

# YENİ: Akıllı Anahtar Kelime Motoru
@st.cache_data(ttl=86400, show_spinner="Akıllı anahtar kelimeler üretiliyor...")
def extract_keywords_for_search(_client, headline):
    """Bir haber başlığından, arama yapmak için en uygun anahtar kelimeleri AI ile çıkarır."""
    prompt = f"""
    Sen bir arama motoru optimizasyon uzmanısın. Sana verilen haber başlığını analiz et ve bu olayla ilgili internette arama yapmak için en etkili, temiz ve güçlü 3-4 anahtar kelimeyi belirle. Sadece konumu, tesis tipini ve olay türünü dikkate al.
    
    Başlık: "{headline}"
    
    Çıktı olarak sadece virgülle ayrılmış kelime listesi ver. Örnek: Arnavutköy, fabrika, patlama
    """
    try:
        response = _client.chat.completions.create(
            model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}],
            max_tokens=50, temperature=0.0
        )
        return response.choices[0].message.content.strip().split(',')
    except Exception:
        return headline.split() # AI başarısız olursa eski yönteme dön

@st.cache_data(ttl=3600, show_spinner="OSINT Taraması başlatıldı: X ve Google taranıyor...")
def run_multivector_scanner(keywords):
    """Akıllı anahtar kelimelerle çok vektörlü tarama yaparak aday isimleri bulur."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    candidates = set()
    search_query = " ".join(f'"{k.strip()}"' for k in keywords)

    # Çok Vektörlü Tarama
    search_vectors = {
        "X (Twitter) Taraması": f"https://www.google.com/search?q={quote(search_query + ' site:twitter.com')}",
        "Genel Basın Taraması": f"https://www.google.com/search?q={quote(search_query)}"
    }
    
    for source, url in search_vectors.items():
        try:
            response = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            text_content = soup.get_text()
            pattern = r'\b[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*\s(?:' + '|'.join(CORPORATE_SUFFIXES) + r')\b'
            found_names = re.findall(pattern, text_content)
            for name in found_names:
                candidates.add(name.strip())
        except Exception as e:
            st.warning(f"{source} sırasında hata: {e}")
            
    return list(candidates)

@st.cache_data(ttl=3600, show_spinner="AI Doğrulayıcı çalışıyor: Adaylar ve kanıtlar analiz ediliyor...")
def run_verifier_ai(_client, context, candidates):
    """Tarayıcıdan gelen adayları ve ana metni analiz ederek nihai raporu oluşturur."""
    prompt = f"""
    Sen, bir OSINT analistisin. Görevin, sana sunulan kanıtları birleştirerek bir hasar raporu oluşturmak. Halüsinasyona sıfır toleransın var.
    KANIT PAKETİ:
    1. ANA HABER METNİ: "{context}"
    2. TARAYICI BULGULARI (Potansiyel Tesis Adları): {candidates}
    GÖREVİN:
    1. 'TARAYICI BULGULARI' listesindeki adaylardan hangisinin 'ANA HABER METNİ' ile en uyumlu olduğunu tespit et.
    2. Tespit ettiğin doğru isim üzerinden, aşağıdaki JSON formatında detaylı bir rapor oluştur.
    3. Eğer listedeki hiçbir aday metinle uyuşmuyorsa, "tesis_adi" alanına "Teyit Edilemedi" yaz.
    JSON ÇIKTISI (Sadece JSON ver):
    {{
      "tesis_adi": "Doğruladığın ticari unvan.", "guven_skoru": "1-5 arası bir sayı.",
      "kanit_zinciri": "Hangi adayı neden seçtiğini ve metindeki hangi cümlenin bu seçimi desteklediğini açıkla.",
      "sehir_ilce": "Metinde geçen net şehir ve ilçe.", "hasarin_nedeni": "Hasar nedeni.",
      "hasarin_fiziksel_boyutu": "Hasarın fiziksel kapsamı.", "is_durmasi_etkisi": "Faaliyetin durmasına ilişkin bilgi.",
      "tahmini_koordinat": {{"lat": "...", "lon": "..."}}
    }}
    """
    try:
        response = _client.chat.completions.create(
            model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}],
            max_tokens=4096, temperature=0.0, timeout=90.0
        )
        match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"AI Doğrulayıcı Hatası: {e}"); return None

# Coğrafi Zenginleştirme Fonksiyonu
@st.cache_data(ttl=86400)
def get_coords_from_google(api_key, address_text):
    if not api_key or not address_text: return None
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={quote(address_text)}&key={api_key}&language=tr&region=TR"
        response = requests.get(url); results = response.json().get('results', [])
        if results: return results[0].get('geometry', {}).get('location', {})
    except Exception: return None

# ------------------------------------------------------------------------------
# 5. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------
if 'selected_risks' not in st.session_state: st.session_state.selected_risks = list(RISK_TYPES.keys())

col1, col2 = st.columns([1, 2], gap="large")

with col1: # SOL PANEL
    st.header("📰 Olay Akışı")
    st.session_state.selected_risks = st.multiselect("Risk Tiplerini Seçin:", options=list(RISK_TYPES.keys()), default=st.session_state.selected_risks)
    if st.button("Filtrele ve Güncel Olayları Tara", type="primary", use_container_width=True):
        st.session_state.initial_events = get_initial_events(st.session_state.selected_risks)
        st.session_state.selected_event = None; st.session_state.keywords = None; st.session_state.candidates = None; st.session_state.final_report = None
    
    if st.session_state.get('initial_events'):
        for event in st.session_state.initial_events:
            with st.container(border=True):
                st.markdown(f"**{event['headline']}**")
                st.caption(event['snippet'])
                if st.button("Bu Olayı Analiz Et", key=event['url'], use_container_width=True):
                    st.session_state.selected_event = event
                    st.session_state.keywords = None; st.session_state.candidates = None; st.session_state.final_report = None
                    st.rerun()

with col2: # SAĞ PANEL
    st.header("📝 Analiz Paneli")
    if not st.session_state.get('selected_event'):
        st.info("Lütfen sol panelden bir olay seçip 'Bu Olayı Analiz Et' butonuna tıklayın.")
    else:
        event = st.session_state.selected_event
        st.subheader(event['headline'])

        # --- AŞAMA 1: AKILLI ANAHTAR KELİME ve TARAMA ---
        if st.button("1. Adım: Tara ve Aday İsimleri Bul", type="primary", use_container_width=True):
            st.session_state.keywords = extract_keywords_for_search(client, event['headline'])
            st.session_state.candidates = run_multivector_scanner(st.session_state.keywords)
            st.rerun()
        
        # --- AŞAMA 1 SONUÇLARI VE AŞAMA 2 BUTONU ---
        if st.session_state.get('keywords'):
            st.info(f"**Akıllı Anahtar Kelimeler:** `{', '.join(st.session_state.keywords)}`")

        if st.session_state.get('candidates') is not None:
            candidates = st.session_state.candidates
            st.markdown("---")
            if not candidates:
                st.warning("Otomatik tarama sonucunda potansiyel bir tesis adı adayı bulunamadı.")
            else:
                st.write("**Tarama Sonucu Bulunan Potansiyel Adaylar:**")
                st.write(f"`{', '.join(candidates)}`")
                
                if st.button("2. Adım: Adayları Doğrula ve Rapor Oluştur", use_container_width=True):
                    st.session_state.final_report = run_verifier_ai(client, event['full_summary'], candidates)
                    st.rerun()
        
        # --- AŞAMA 2 SONUÇLARI (NİHAİ RAPOR) ---
        if st.session_state.get('final_report'):
            report = st.session_state.final_report
            st.markdown("---")
            col_title, col_score = st.columns([3, 1])
            col_title.subheader(f"Doğrulanan Kimlik: {report.get('tesis_adi', 'Teyit Edilemedi')}")
            col_score.metric("Güven Skoru", f"{report.get('guven_skoru', 0)}/5")
            st.info(f"**Kanıt Zinciri:** {report.get('kanit_zinciri', 'N/A')}")

            st.warning(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'N/A')}")
            st.warning(f"**Fiziksel Boyutu:** {report.get('hasarin_fiziksel_boyutu', 'N/A')}")
            st.info(f"**İş Durması Etkisi:** {report.get('is_durmasi_etkisi', 'N/A')}")
            
            # Harita
            coords = report.get('tahmini_koordinat', {})
            final_coords = None
            if coords and coords.get('lat'):
                try: final_coords = {'lat': float(coords['lat']), 'lng': float(coords['lon'])}
                except (ValueError, TypeError): final_coords = None
            
            if not final_coords:
                address = f"{report.get('tesis_adi', '')}, {report.get('sehir_ilce', '')}"
                if report.get('tesis_adi') != 'Teyit Edilemedi':
                    final_coords = get_coords_from_google(google_api_key, address)

            if final_coords:
                st.subheader("Olay Yeri Haritası")
                m = folium.Map(location=[final_coords['lat'], final_coords['lng']], zoom_start=14)
                folium.TileLayer('CartoDB positron').add_to(m)
                folium.Marker([final_coords['lat'], final_coords['lng']], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                folium_static(m, height=400)
            else:
                st.warning("Konum bilgisi bulunamadığı için harita oluşturulamadı.")
