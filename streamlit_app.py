# ==============================================================================
#      NİHAİ KOD (v15.0): İnsan Onaylı Kürasyon ve Derin Analiz Modeli
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
from sqlalchemy import text

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE BAĞLANTILAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Endüstriyel Hasar İstihbaratı")
st.title("🛰️ Akıllı Endüstriyel Hasar İstihbarat Platformu")

# --- API ve Veritabanı Bağlantıları ---
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

@st.cache_resource
def init_connection():
    return st.connection("reports_db", type="sql", url="sqlite:///reports_db.db")

conn = init_connection()

def create_tables_if_not_exist():
    with conn.session as s:
        s.execute(text('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, event_group_key TEXT UNIQUE, first_seen_date TEXT);'))
        s.execute(text('CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, event_id INTEGER, report_json TEXT, created_date TEXT, FOREIGN KEY (event_id) REFERENCES events (id));'))
        s.commit()

create_tables_if_not_exist()

# Session State'i başlat
if 'draft_reports' not in st.session_state:
    st.session_state.draft_reports = {}

# ------------------------------------------------------------------------------
# 2. YAPAY ZEKA DESTEKLİ FONKSİYONLAR
# ------------------------------------------------------------------------------
@st.cache_data(ttl=900)
def discover_events(_client, period_days=7):
    prompt = f"Sen bir haber tarama botusun. Son {period_days} gün içinde Türkiye'de 'fabrika, sanayi, depo, liman, santral, OSB' ve 'yangın, patlama, kaza, hasar, sızıntı' kelimelerini içeren önemli haber başlıklarını ve linklerini bul. Sadece bir JSON listesi olarak `[{{\"headline\": \"...\", \"url\": \"...\"}}]` formatında ver. En fazla 30 başlık yeterli."
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.2)
        content = response.choices[0].message.content
        match = re.search(r'\[.*\]', content, re.DOTALL)
        return json.loads(match.group(0)) if match else []
    except Exception as e:
        st.error(f"Keşif aşamasında hata: {e}"); return []

@st.cache_data(ttl=900)
def group_similar_events(_client, headlines):
    headlines_str = "\n".join([f"- {h['headline']}" for h in headlines])
    prompt = f"Sen bir haber editörüsün. Sana verdiğim şu haber başlıkları listesini analiz et ve aynı olaya ait olanları grupla. Çıktıyı bir JSON objesi olarak ver. Her anahtar, olay için birleştirici bir başlık olsun, değeri ise o gruba ait orijinal başlıkların listesi olsun.\nBAŞLIKLAR:\n{headlines_str}"
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.0)
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else {}
    except Exception as e:
        st.error(f"Gruplama aşamasında hata: {e}"); return {}

# GÜNCELLEME: Bu prompt, AI'ı aktif araştırmaya zorlar.
@st.cache_data(ttl=86400)
def analyze_event_details(_client, headlines_list, group_key):
    prompt = f"""
    Sen elit bir sigorta istihbarat analistisin.
    ANA GÖREVİN: Aşağıdaki URL listesini kullanarak web'i aktif olarak tara ve haber metinlerini OKU.
    URL LİSTESİ: {json.dumps(headlines_list, ensure_ascii=False)}

    İKİNCİL GÖREVİN: Haberde adı geçen ana tesisin adını ve olay hakkındaki ilk bilgileri teyit etmek için X (Twitter) üzerinde bir arama yap.

    NİHAİ HEDEF: Topladığın TÜM bilgileri (web metinleri ve X) birleştirerek, '{group_key}' olayı için tek ve kapsamlı bir JSON raporu oluştur. Raporun tüm alanlarını doldurmak için elinden geleni yap. Özellikle 'latitude', 'longitude' ve kaynaklı 'hasar_tahmini' alanları kritiktir. Eğer bir bilgiyi bulamazsan, o alanı boş bırakmak yerine "Tespit Edilemedi" yaz.
    
    JSON ANAHTARLARI: olay_tarihi_saati, guncel_durum, tesis_adi_ticari_unvan, sehir_ilce, olay_tipi_ozet, hasar_tahmini (nesne: tutar_araligi_tl, kaynak, aciklama), can_kaybi_ve_yaralilar (nesne: durum, detaylar), kaynak_linkleri (dizi), gorsel_linkleri (dizi), latitude, longitude
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Detaylı analiz aşamasında hata: {e}"); return None

@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=300):
    if not api_key: return []
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
    try:
        response = requests.get(url)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "konum": p.get('vicinity')} for p in results[:5]]
    except Exception as e:
        st.warning(f"Google Places API hatası: {e}"); return []

# ------------------------------------------------------------------------------
# 3. VERİTABANI İŞLEMLERİ
# ------------------------------------------------------------------------------
def check_event_exists(event_group_key):
    df = conn.query("SELECT id FROM events WHERE event_group_key = :key;", params={"key": event_group_key})
    return not df.empty

def save_report_to_db(event_group_key, report_json):
    with conn.session as s:
        s.execute(text("INSERT INTO events (event_group_key, first_seen_date) VALUES (:key, :date);"),
                  params={"key": event_group_key, "date": datetime.now().isoformat()})
        result = s.execute(text("SELECT id FROM events WHERE event_group_key = :key;"), params={"key": event_group_key})
        event_id = result.fetchone()[0]
        s.execute(text("INSERT INTO reports (event_id, report_json, created_date) VALUES (:id, :json, :date);"),
                  params={"id": event_id, "json": json.dumps(report_json, ensure_ascii=False), "date": datetime.now().isoformat()})
        s.commit()

def get_all_reports_from_db():
    df = conn.query("SELECT e.event_group_key, r.report_json, r.created_date FROM reports r JOIN events e ON r.event_id = e.id ORDER BY r.created_date DESC;", ttl=600)
    reports = []
    for index, row in df.iterrows():
        try:
            report_data = json.loads(row['report_json'])
            report_data['event_group_key'] = row['event_group_key']
            report_data['created_date'] = row['created_date']
            reports.append(report_data)
        except json.JSONDecodeError: continue
    return reports

# ------------------------------------------------------------------------------
# 4. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
st.sidebar.header("Otomatik Tarama")
run_auto_search = st.sidebar.button("Son Olayları Bul ve Analiz Et", type="primary", use_container_width=True)
st.sidebar.caption("Son 7 güne ait olayları tarar, tekilleştirir, analiz eder ve onayınıza sunar.")

tab1, tab2 = st.tabs(["🆕 Yeni Analiz Sonuçları", "🗃️ Geçmiş Raporlar Veritabanı"])

if run_auto_search:
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()
    
    st.session_state.draft_reports = {} # Her yeni aramada taslakları temizle
    
    with st.spinner("Aşama 1/3: Potansiyel olaylar web'den taranıyor..."):
        headlines = discover_events(client)
    if not headlines: st.warning("Keşif aşamasında yeni bir olay başlığı bulunamadı."); st.stop()

    with st.spinner(f"Aşama 2/3: {len(headlines)} başlık AI ile gruplanıyor ve tekilleştiriliyor..."):
        event_groups = group_similar_events(client, headlines)
    
    st.info(f"{len(event_groups)} adet benzersiz olay grubu tespit edildi. Veritabanı kontrol ediliyor ve yeni olanlar analiz ediliyor...")

    new_events_to_process = {}
    for group_key, group_headlines in event_groups.items():
        if not check_event_exists(group_key):
            new_events_to_process[group_key] = group_headlines

    if not new_events_to_process:
        st.success("Tüm tespit edilen olaylar daha önce işlenmiş. Yeni bir olay bulunamadı.")
        st.balloons()
    else:
        st.success(f"Analiz edilecek {len(new_events_to_process)} yeni olay grubu bulundu.")
        
        analysis_placeholder = st.empty()
        for group_key, group_headlines in new_events_to_process.items():
            with analysis_placeholder.status(f"Aşama 3/3: '{group_key}' için derin analiz yapılıyor...", expanded=True):
                original_articles = [h for h in headlines if h['headline'] in group_headlines]
                details = analyze_event_details(client, original_articles, group_key)
                if not details: 
                    st.error(f"'{group_key}' için detaylı rapor oluşturulamadı."); continue

                lat, lon = details.get('latitude'), details.get('longitude')
                real_neighbors = find_neighboring_facilities(google_api_key, lat, lon) if lat and lon else []
                details['real_neighbors'] = real_neighbors
                
                # Raporu veritabanına değil, geçici "taslak" listesine ekle
                st.session_state.draft_reports[group_key] = details
                st.success(f"'{group_key}' için rapor taslağı oluşturuldu. Onayınızı bekliyor.")
        analysis_placeholder.empty()

# --- YENİ ANALİZLERİ GÖSTERME VE ONAYLAMA BÖLÜMÜ ---
with tab1:
    st.header("Onay Bekleyen Yeni Rapor Taslakları")
    if not st.session_state.draft_reports:
        st.info("Henüz onay bekleyen yeni bir rapor bulunmamaktadır. Lütfen yeni bir tarama başlatın.")
    else:
        for group_key, details in list(st.session_state.draft_reports.items()):
            st.subheader(f"Rapor: {details.get('tesis_adi_ticari_unvan', group_key)}")
            
            # Rapor önizlemesi
            col1, col2 = st.columns(2)
            # ... (Rapor gösterme kodu)
            with col1:
                st.info(f"**Özet:** {details.get('olay_tipi_ozet', 'N/A')}")
                hasar = details.get('hasar_tahmini', {})
                st.metric(label="Hasar Tahmini", value=hasar.get('tutar_araligi_tl', 'Tespit Edilemedi'), delta=hasar.get('kaynak', ''), delta_color="off")
            with col2:
                st.info(f"**Güncel Durum:** {details.get('guncel_durum', 'N/A')}")
            
            if st.button("✔️ Onayla ve Veritabanına Kaydet", key=f"onay_{group_key}", type="primary"):
                try:
                    save_report_to_db(group_key, details)
                    st.success(f"'{group_key}' başarıyla veritabanına kaydedildi!")
                    # Onaylanan raporu taslaklardan kaldır
                    del st.session_state.draft_reports[group_key]
                    st.experimental_rerun()
                except Exception as e:
                    st.error(f"Rapor kaydedilirken bir hata oluştu: {e}")

            with st.expander("Tüm Rapor Detayını, Komşuları ve Kaynakları Görüntüle"):
                # Harita
                lat, lon = details.get('latitude'), details.get('longitude')
                if lat and lon:
                    try:
                        m = folium.Map(location=[float(lat), float(lon)], zoom_start=16)
                        folium.Marker([float(lat), float(lon)], popup=f"<b>{details.get('tesis_adi_ticari_unvan')}</b>", tooltip="Ana Tesis", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                        folium_static(m, height=300)
                    except (ValueError, TypeError): st.warning("Geçersiz koordinat formatı, harita çizilemiyor.")
                
                # Detaylar
                st.markdown("##### Gerçek Komşu Tesisler (Google Maps Verisi)")
                st.table(pd.DataFrame(details.get('real_neighbors', []))) if details.get('real_neighbors') else st.write("Komşu tesis bilgisi yok.")
                st.markdown("##### Kaynak Linkler")
                for link in details.get('kaynak_linkleri', []): st.markdown(f"- {link}") if isinstance(link, str) else st.write(link)
            st.markdown("---")

# --- GEÇMİŞ RAPORLAR SEKMESİ ---
with tab2:
    st.header("🗃️ Veritabanında Kayıtlı Onaylanmış Raporlar")
    if st.button("Raporları Yenile"):
        st.cache_data.clear() # Cache'i temizle
    all_reports = get_all_reports_from_db()
    if not all_reports:
        st.info("Veritabanında henüz kaydedilmiş bir rapor bulunmamaktadır.")
    else:
        st.success(f"Veritabanında toplam {len(all_reports)} adet onaylanmış rapor bulundu.")
        for report in all_reports:
            tarih = pd.to_datetime(report['created_date']).strftime('%d %b %Y, %H:%M')
            with st.expander(f"**{report.get('tesis_adi_ticari_unvan', 'İsimsiz Tesis')}** - {report.get('sehir_ilce', 'Konum Yok')} (Kayıt: {tarih})"):
                col1, col2 = st.columns(2)
                # ... (Rapor gösterme kodu)
                with col1:
                    st.info(f"**Özet:** {report.get('olay_tipi_ozet', 'N/A')}")
                    hasar = report.get('hasar_tahmini', {})
                    st.metric(label="Hasar Tahmini", value=hasar.get('tutar_araligi_tl', 'Tespit Edilemedi'), delta=hasar.get('kaynak', ''), delta_color="off")
                with col2:
                    st.info(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")
                st.markdown("##### Gerçek Komşu Tesisler (Google Maps Verisi)")
                st.table(pd.DataFrame(report.get('real_neighbors', []))) if report.get('real_neighbors') else st.write("Komşu tesis bilgisi yok.")
