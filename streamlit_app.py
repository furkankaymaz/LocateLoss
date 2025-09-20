# ==============================================================================
#      NİHAİ KOD (v14.1): Güvenli Veritabanı ve Hata Düzeltmeleri
# ==============================================================================
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re
import requests
from datetime import datetime

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE BAĞLANTILAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Endüstriyel Hasar İstihbaratı")
st.title("🛰️ Akıllı Endüstriyel Hasar İstihbarat Platformu")

# --- API Bağlantıları ---
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# --- Veritabanı Bağlantısı ---
@st.cache_resource
def init_connection():
    return st.connection("reports_db", type="sql")

conn = init_connection()

# Tabloları oluştur (sadece ilk çalıştırmada çalışır)
with conn.session as s:
    s.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_group_key TEXT UNIQUE,
            first_seen_date TEXT
        );
    ''')
    s.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            report_json TEXT,
            created_date TEXT,
            FOREIGN KEY (event_id) REFERENCES events (id)
        );
    ''')
    s.commit()

# ------------------------------------------------------------------------------
# 2. YAPAY ZEKA DESTEKLİ FONKSİYONLAR (PİPELİNE ADIMLARI)
# ------------------------------------------------------------------------------
# Bu bölümdeki AI fonksiyonlarında (discover_events, group_similar_events, vb.) değişiklik yoktur.
# Okunabilirlik için sadece bir tanesini örnek olarak bırakıyorum.
@st.cache_data(ttl=900)
def discover_events(_client, period_days=7):
    # ... (v14.0 ile aynı)
    prompt = f"Sen bir haber tarama botusun. Son {period_days} gün içinde Türkiye'de 'fabrika, sanayi, depo, liman, santral, OSB' kelimeleri ve 'yangın, patlama, kaza, hasar, sızıntı' kelimelerini içeren önemli haber başlıklarını ve linklerini bul. Sadece bir JSON listesi olarak `[{{\"headline\": \"...\", \"url\": \"...\"}}]` formatında ver. Analiz yapma, sadece listele. En fazla 30 başlık yeterli."
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.2)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', content, re.DOTALL)
        return json.loads(match.group(0)) if match else []
    except Exception: return []

# ... Diğer AI fonksiyonları (group_similar_events, analyze_event_details, find_neighboring_facilities) v14.0 ile aynıdır.
# Bu fonksiyonlar buraya kopyalanabilir.

@st.cache_data(ttl=900)
def group_similar_events(_client, headlines):
    headlines_str = "\n".join([f"- {h['headline']}" for h in headlines])
    prompt = f"""Sen bir haber editörüsün. Sana verdiğim şu haber başlıkları listesini analiz et ve aynı olaya ait olanları grupla. Çıktıyı bir JSON objesi olarak ver. Her anahtar, olay için birleştirici bir başlık olsun, değeri ise o gruba ait orijinal başlıkların listesi olsun.
    BAŞLIKLAR:\n{headlines_str}
    Örnek Çıktı Formatı: {{"Gebze Kimya Fabrikası Yangını": ["Gebze'deki fabrikada korkutan yangın", "Kocaeli'de kimya tesisinde patlama yaşandı"],"İkitelli Mobilya Atölyesi Yangını": ["İkitelli'de bir atölye alevlere teslim oldu"]}}"""
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.0)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else {}
    except Exception: return {}

@st.cache_data(ttl=86400)
def analyze_event_details(_client, headlines_list, group_key):
    prompt = f"""Sen bir sigorta hasar eksperi ve risk analistisin. Sana verdiğim '{group_key}' olayı ile ilgili şu haber başlıklarını ve linklerini analiz et: {json.dumps(headlines_list)}.
    GÖREVİN: Bu bilgileri kullanarak, tek ve birleştirilmiş, detaylı bir JSON raporu oluştur. Hasar tahminini haber metninden kaynak göstererek yap, ASLA tahmin yürütme.
    JSON ANAHTARLARI: olay_tarihi_saati, guncel_durum, tesis_adi_ticari_unvan, sehir_ilce, olay_tipi_ozet, hasar_tahmini (nesne: tutar_araligi_tl, kaynak, aciklama), can_kaybi_ve_yaralilar (nesne: durum, detaylar), kaynak_linkleri (dizi), gorsel_linkleri (dizi), latitude, longitude"""
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match: return json.loads(match.group(0))
        return None
    except Exception: return None

@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=300):
    if not api_key: return []
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
    try:
        response = requests.get(url)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "konum": p.get('vicinity')} for p in results[:5]]
    except Exception: return []


# ------------------------------------------------------------------------------
# 3. GÜVENLİ VERİTABANI İŞLEMLERİ
# ------------------------------------------------------------------------------
# DÜZELTME: Bu fonksiyonlar artık güvenli parametreli sorgular kullanıyor.
def check_event_exists(event_group_key):
    df = conn.query(
        "SELECT id FROM events WHERE event_group_key = :key;",
        params={"key": event_group_key}
    )
    return not df.empty

def save_report_to_db(event_group_key, report_json):
    with conn.session as s:
        # Önce event'i kaydet
        s.execute(
            "INSERT INTO events (event_group_key, first_seen_date) VALUES (:key, :date);",
            params={"key": event_group_key, "date": datetime.now().isoformat()}
        )
        # Son eklenen event'in id'sini al
        result = s.execute(
            "SELECT id FROM events WHERE event_group_key = :key;",
            params={"key": event_group_key}
        )
        event_id = result.fetchone()[0]
        
        # Raporu kaydet
        s.execute(
            "INSERT INTO reports (event_id, report_json, created_date) VALUES (:id, :json, :date);",
            params={"id": event_id, "json": json.dumps(report_json, ensure_ascii=False), "date": datetime.now().isoformat()}
        )
        s.commit()

def get_all_reports_from_db():
    df = conn.query("SELECT e.event_group_key, r.report_json, r.created_date FROM reports r JOIN events e ON r.event_id = e.id ORDER BY r.created_date DESC;", ttl=600) # 10 dakika cache
    reports = []
    for index, row in df.iterrows():
        try:
            report_data = json.loads(row['report_json'])
            report_data['event_group_key'] = row['event_group_key']
            report_data['created_date'] = row['created_date']
            reports.append(report_data)
        except json.JSONDecodeError:
            continue # Bozuk JSON verisini atla
    return reports

# ------------------------------------------------------------------------------
# 4. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
# Bu bölümde önemli bir değişiklik yoktur, v14.0 ile aynıdır.
st.sidebar.header("Otomatik Tarama")
run_auto_search = st.sidebar.button("Son Olayları Bul ve Analiz Et", type="primary", use_container_width=True)
st.sidebar.caption("Son 7 güne ait olayları tarar, tekilleştirir ve analiz eder.")
tab1, tab2 = st.tabs(["Yeni Analiz Sonuçları", "Geçmiş Raporlar Veritabanı"])

if run_auto_search:
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin.")
        st.stop()
    
    with tab1:
        with st.spinner("Aşama 1/5: Potansiyel olaylar web'den taranıyor..."):
            headlines = discover_events(client)
        if not headlines:
            st.warning("Keşif aşamasında yeni bir olay başlığı bulunamadı."); st.stop()
        st.info(f"{len(headlines)} potansiyel başlık bulundu. Şimdi gruplanıyor...")

        with st.spinner("Aşama 2/5: AI ile benzer haberler gruplanıyor..."):
            event_groups = group_similar_events(client, headlines)
        st.success(f"{len(event_groups)} adet benzersiz olay grubu tespit edildi.")
        
        newly_processed_count = 0
        for group_key, group_headlines in event_groups.items():
            st.markdown("---"); st.subheader(f"İncelenen Olay Grubu: {group_key}")
            
            if check_event_exists(group_key):
                st.warning("Bu olay daha önce analiz edilmiş ve veritabanına kaydedilmiş. Atlanıyor.")
                continue

            newly_processed_count += 1
            with st.spinner(f"Aşama 3/5: '{group_key}' için derin analiz yapılıyor..."):
                original_articles = [h for h in headlines if h['headline'] in group_headlines]
                details = analyze_event_details(client, original_articles, group_key)
            if not details:
                st.error("Bu olay için detaylı rapor oluşturulamadı."); continue

            lat, lon = details.get('latitude'), details.get('longitude')
            real_neighbors = find_neighboring_facilities(google_api_key, lat, lon) if lat and lon else []
            details['real_neighbors'] = real_neighbors

            save_report_to_db(group_key, details)
            st.success(f"✔️ Rapor başarıyla oluşturuldu ve veritabanına kaydedildi!")
            
            # Raporu Ekrana Basma (v14.0 ile aynı)
            col1, col2 = st.columns(2)
            # ...
            with col1:
                st.info(f"**Özet:** {details.get('olay_tipi_ozet', 'N/A')}")
                hasar = details.get('hasar_tahmini', {})
                st.metric(label="Hasar Tahmini", value=hasar.get('tutar_araligi_tl', 'Belirtilmemiş'), delta=hasar.get('kaynak', ''), delta_color="off")
            with col2:
                st.info(f"**Güncel Durum:** {details.get('guncel_durum', 'N/A')}")
                can_kaybi = details.get('can_kaybi_ve_yaralilar', {})
                if can_kaybi and can_kaybi.get('durum', 'hayır').lower() == 'evet':
                    st.error(f"**Can Kaybı/Yaralı:** {can_kaybi.get('detaylar', 'Detay Yok')}")
            
            if lat and lon:
                try:
                    m = folium.Map(location=[float(lat), float(lon)], zoom_start=16)
                    folium.Marker([float(lat), float(lon)], popup=f"<b>{details.get('tesis_adi_ticari_unvan')}</b>", tooltip="Ana Tesis", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                    folium_static(m, height=400)
                except (ValueError, TypeError):
                    st.warning("Geçersiz koordinat formatı, harita çizilemiyor.")
            
            with st.expander("Detaylı Raporu, Komşu Tesisleri ve Kaynakları Görüntüle"):
                st.markdown("##### Gerçek Komşu Tesisler (Google Maps Verisi)")
                st.table(pd.DataFrame(real_neighbors)) if real_neighbors else st.write("Yakın çevrede harita servisinden tesis tespit edilemedi.")
                st.markdown("##### Kaynak Linkler")
                for link in details.get('kaynak_linkleri', []): st.markdown(f"- {link}")


        if newly_processed_count == 0 and len(event_groups) > 0:
            st.info("Tüm tespit edilen olaylar daha önce işlenmiş. Yeni bir olay bulunamadı.")

with tab2:
    st.header("Veritabanında Kayıtlı Geçmiş Raporlar")
    all_reports = get_all_reports_from_db()
    if not all_reports:
        st.info("Veritabanında henüz kaydedilmiş bir rapor bulunmamaktadır.")
    else:
        st.success(f"Veritabanında toplam {len(all_reports)} adet rapor bulundu.")
        for report in all_reports:
            tarih = pd.to_datetime(report['created_date']).strftime('%d %b %Y, %H:%M')
            with st.expander(f"**{report.get('tesis_adi_ticari_unvan', 'İsimsiz Tesis')}** - {report.get('sehir_ilce', 'Konum Yok')} (Kayıt: {tarih})"):
                col1, col2 = st.columns(2)
                # ...
                with col1:
                    st.info(f"**Özet:** {report.get('olay_tipi_ozet', 'N/A')}")
                    hasar = report.get('hasar_tahmini', {})
                    st.metric(label="Hasar Tahmini", value=hasar.get('tutar_araligi_tl', 'Belirtilmemiş'), delta=hasar.get('kaynak', ''), delta_color="off")
                with col2:
                    st.info(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")
                st.markdown("##### Gerçek Komşu Tesisler (Google Maps Verisi)")
                st.table(pd.DataFrame(report.get('real_neighbors', []))) if report.get('real_neighbors') else st.write("Komşu tesis bilgisi yok.")
