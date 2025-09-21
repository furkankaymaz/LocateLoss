# ==============================================================================
#  "Tek Dosyalık Güç Merkezi" MVP (v37.0)
# ==============================================================================
import streamlit as st
import pandas as pd
import requests
import feedparser
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re
from urllib.parse import quote, urlparse
from datetime import datetime
from rapidfuzz import fuzz

# Metin Çıkarma Kütüphaneleri
import trafilatura
from bs4 import BeautifulSoup
import readability

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE API BAĞLANTILARI
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Endüstriyel Hasar Motoru")
st.title("🛰️ Akıllı Endüstriyel Hasar Motoru")

# --- API Bağlantıları (Streamlit Secrets'ten) ---
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. VERİTABANI KURULUMU VE YÖNETİMİ (DAHİLİ)
# ------------------------------------------------------------------------------
@st.cache_resource
def get_db_connection():
    # Streamlit'in kendi bağlantı yönetimi ile SQLite veritabanı oluştur/bağlan
    return st.connection("events_db", type="sql", url="sqlite:///events.db")

conn = get_db_connection()

# Uygulama ilk çalıştığında veritabanı tablosunu oluştur
with conn.session as s:
    s.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY,
            headline TEXT,
            url TEXT UNIQUE,
            source TEXT,
            published_date TEXT,
            full_text TEXT,
            status TEXT DEFAULT 'new',
            report_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    s.commit()

# ------------------------------------------------------------------------------
# 3. YARDIMCI FONKSİYONLAR (METİN ÇEKME, AI ZİNCİRİ, HARİTA)
# ------------------------------------------------------------------------------

# -- Metin Çıkarma Motoru --
@st.cache_data(ttl=86400) # Bir URL'yi günde bir defadan fazla çekme
def fetch_article_text(url: str) -> str:
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        html_doc = resp.text
        
        # 1. Katman: Trafilatura
        extracted = trafilatura.extract(html_doc, include_comments=False, include_tables=False)
        if extracted and len(extracted.strip()) > 300: return extracted.strip()

        # 2. Katman: Readability
        doc = readability.Document(html_doc)
        text = BeautifulSoup(doc.summary(), "lxml").get_text(separator="\n", strip=True)
        if text and len(text.strip()) > 300: return text.strip()

        # 3. Katman: BeautifulSoup Fallback
        soup = BeautifulSoup(html_doc, "lxml")
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        text = "\n".join([p for p in paragraphs if len(p) > 50])
        return text.strip()
    except Exception:
        return ""

# -- AI Analiz Zinciri --
def extract_clues_from_text(_client, full_text):
    prompt = f"GÖREV: Aşağıdaki haber metnini oku ve X'te arama yapmak için kullanılabilecek en spesifik ipuçlarını çıkar. Çıktıyı SADECE JSON formatında ver.\nHABER METNİ: \"{full_text[:8000]}\"\n\nJSON YAPISI: {{\"en_spesifik_konum\": \"...\", \"tesis_tipi\": \"...\", \"olay_detaylari\": \"...\"}}"
    response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=1024, temperature=0.0)
    match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
    return json.loads(match.group(0)) if match else {}

def simulate_x_search_for_name(_client, clues):
    prompt = f"Sen bir OSINT uzmanısın. Görevin, sana verilen ipuçlarını kullanarak X (Twitter) üzerinde nokta atışı bir arama simülasyonu yapmak ve olayın yaşandığı tesisin ticari unvanını teyit etmektir. ASLA TAHMİN YÜRÜTME.\nİPUÇLARI: {clues}\n\nÇIKTI FORMATI (SADECE JSON): {{\"tesis_adi\": \"Yüksek kesinlikle bulunan isim VEYA 'Teyit Edilemedi'\", \"kanit\": \"İsmi nasıl bulduğunun açıklaması.\"}}"
    response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.0)
    match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
    return json.loads(match.group(0)) if match else {}

def generate_final_report(_client, full_text, company_info):
    prompt = f"Sen elit bir sigorta risk analistisin. Bilgiler şunlar:\n- TEYİT EDİLMİŞ TESİS BİLGİSİ: {company_info}\n- OLAYIN HABER METNİ: \"{full_text[:8000]}\"\n\nGÖREVİN: Bu bilgileri kullanarak, aşağıdaki tüm anahtarları dolduran nihai ve detaylı JSON raporunu oluştur.\n\nJSON YAPISI: \"sehir_ilce\", \"tahmini_koordinat\": {{\"lat\": \"...\", \"lon\": \"...\"}}, \"maddi_hasar_fiziksel_boyut\", \"is_durmasi_kar_kaybi\", \"hasarin_nedeni\", \"yapilan_mudahale\", \"guncel_durum\", \"cevreye_etki\", \"gorsel_url\""
    response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
    match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
    final_data = json.loads(match.group(0)) if match else {}
    final_data.update(company_info)
    return final_data

# -- Harita Fonksiyonu --
def find_neighboring_facilities(api_key, lat, lon):
    if not all([api_key, lat, lon]): return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=1000&type=establishment&keyword=fabrika|depo|sanayi|tesis&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "adres": p.get('vicinity'), "lat": p.get('geometry',{}).get('location',{}).get('lat'),"lng": p.get('geometry',{}).get('location',{}).get('lng')} for p in results[:10]]
    except Exception: return []

# ------------------------------------------------------------------------------
# 4. ANA İŞ AKIŞI VE STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------

# --- Sol Sütun: Kontrol Paneli ---
with st.sidebar:
    st.header("Kontrol Paneli")
    if st.button("📰 Yeni Olayları Tara", type="primary", use_container_width=True):
        with st.spinner("Haber kaynakları taranıyor ve veritabanına ekleniyor..."):
            locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo"'
            events = '"yangın" OR "patlama" OR "kaza" OR "sızıntı"'
            q = f'({locations}) AND ({events})'
            rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:3d&hl=tr&gl=TR&ceid=TR:tr"
            
            feed = feedparser.parse(rss_url)
            
            # Veritabanındaki mevcut başlıkları çek
            existing_headlines_df = conn.query("SELECT headline FROM articles;")
            existing_headlines = existing_headlines_df['headline'].tolist()

            new_articles_count = 0
            for entry in feed.entries:
                headline = entry.title.split(" - ")[0]
                url = entry.link
                source = urlparse(url).netloc
                
                # Benzerlik kontrolü
                is_similar = any(fuzz.ratio(headline, old_headline) > 85 for old_headline in existing_headlines)

                if not is_similar:
                    full_text = fetch_article_text(url)
                    if full_text and len(full_text) > 300:
                        # Veritabanına yeni makaleyi ekle
                        with conn.session as s:
                            s.execute(
                                "INSERT INTO articles (headline, url, source, published_date, full_text, status) VALUES (:headline, :url, :source, :published, :text, 'new') ON CONFLICT(url) DO NOTHING;",
                                params={"headline": headline, "url": url, "source": entry.get("published"), "published": entry.get("published"), "text": full_text}
                            )
                            s.commit()
                        existing_headlines.append(headline)
                        new_articles_count += 1
        st.success(f"{new_articles_count} yeni olay adayı veritabanına eklendi.")
        st.rerun()

    st.markdown("---")
    
    # Analiz bekleyen olayları veritabanından çek
    new_events_df = conn.query("SELECT id, headline FROM articles WHERE status = 'new' ORDER BY id DESC;")
    if not new_events_df.empty:
        st.subheader("Analiz Bekleyen Olaylar")
        event_options = {f"{row['headline']} (ID: {row['id']})": row['id'] for index, row in new_events_df.iterrows()}
        selected_event_display = st.radio("Bir olay seçin:", event_options.keys())
        st.session_state.selected_event_id = event_options[selected_event_display]
    else:
        st.info("Analiz bekleyen yeni olay bulunmuyor.")

# --- Sağ Sütun: Analiz ve Rapor Paneli ---
if 'selected_event_id' in st.session_state:
    event_id = st.session_state.selected_event_id
    
    # Seçilen olayın tüm bilgilerini veritabanından al
    event_data = conn.query(f"SELECT * FROM articles WHERE id = {event_id};", ttl=0).iloc[0]
    
    st.header("Analiz Paneli")
    st.subheader(event_data['headline'])
    st.caption(f"Kaynak: {event_data['source']} | [Haber Linki]({event_data['url']})")

    if event_data['status'] == 'new':
        if st.button("✅ Bu Olayı Analiz Et", type="primary", use_container_width=True):
            with st.status("İstihbarat Analisti Protokolü yürütülüyor...", expanded=True) as status:
                full_text = event_data['full_text']
                
                status.write("Aşama 1: Haber metninden ipuçları çıkarılıyor...")
                clues = extract_clues_from_text(client, full_text)
                
                status.write("Aşama 2: İpuçları ile X'te kontrollü arama simüle ediliyor...")
                company_info = simulate_x_search_for_name(client, clues)
                
                status.write("Aşama 3: Nihai rapor oluşturuluyor...")
                report_data = generate_final_report(client, full_text, company_info)
                
                status.write("Aşama 4: Rapor coğrafi verilerle zenginleştiriliyor...")
                coords = report_data.get('tahmini_koordinat', {})
                lat, lon = coords.get('lat'), coords.get('lon')
                if lat and lon:
                   report_data['komsu_tesisler'] = find_neighboring_facilities(google_api_key, lat, lon)
                
                # Raporu ve durumu veritabanına kaydet
                with conn.session as s:
                    s.execute(
                        "UPDATE articles SET status = 'processed', report_json = :report WHERE id = :id;",
                        params={"report": json.dumps(report_data, ensure_ascii=False), "id": event_id}
                    )
                    s.commit()
                
                status.update(label="Analiz Başarıyla Tamamlandı!", state="complete", expanded=False)
                st.rerun()

    # Eğer olay daha önce analiz edildiyse, raporu veritabanından göster
    if event_data['status'] == 'processed':
        st.success("Bu olay daha önce analiz edildi. Rapor aşağıdadır.")
        report = json.loads(event_data['report_json'])
        
        st.subheader(f"Rapor: {report.get('tesis_adi', 'İsimsiz Tesis')}")
        st.info(f"**Kanıt:** *\"{report.get('kanit', 'Kanıt bulunamadı.')}\"*")
        
        # ... (Rapor gösterme kodunun geri kalanı, önceki versiyonlarla aynı) ...
        with st.expander("Detaylı Raporu Görüntüle", expanded=True):
            if report.get('gorsel_url') and 'http' in report.get('gorsel_url'):
                st.image(report['gorsel_url'])
            
            st.markdown("##### Hasar Analizi")
            col_m, col_k = st.columns(2)
            with col_m: st.warning(f"**Maddi Hasar (Fiziksel Boyut):** {report.get('maddi_hasar_fiziksel_boyut', 'Detay Yok')}")
            with col_k: st.error(f"**İş Durması / Kar Kaybı:** {report.get('is_durmasi_kar_kaybi', 'Detay Yok')}")

            st.markdown("##### Olay Yönetimi ve Etkileri")
            st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'Detay Yok')}")
            st.info(f"**Güncel Durum:** {report.get('guncel_durum', 'Detay Yok')}")

            coords = report.get('tahmini_koordinat', {})
            lat, lon = coords.get('lat'), coords.get('lon')
            if lat and lon:
                try:
                    m = folium.Map(location=[float(lat), float(lon)], zoom_start=14, tiles="CartoDB positron")
                    folium.Marker([float(lat), float(lon)], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                    neighbors = report.get('komsu_tesisler', [])
                    for n in neighbors:
                        if n.get('lat') and n.get('lng'):
                            folium.Marker([n['lat'], n['lng']], popup=f"<b>{n['tesis_adi']}</b>", icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                    folium_static(m, height=400)
                    st.table(pd.DataFrame(neighbors)[['tesis_adi', 'adres']])
                except (ValueError, TypeError): st.warning("Harita çizilemiyor.")
