# ==============================================================================
#  NİHAİ KOD (v54.0): Maksimum Kapsama Ajanı
#  AMAÇ: Tek, güçlü ve hedefli bir sorgu ile en güvenilir kaynaklardan
#  maksimum kanıt toplayarak nihai raporu oluşturmak.
# ==============================================================================
import streamlit as st
import requests
from openai import OpenAI

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Maksimum Kapsama Ajanı")
st.title("🛰️ Maksimum Kapsama İstihbarat Ajanı")
st.info("Bu ajan, tek ve güçlü bir sorguyu, hedeflenmiş güvenilir kaynaklarda (X, AA, DHA vb.) çalıştırarak en kapsamlı sonuçları elde etmeyi hedefler.")

# --- API Anahtarları
GROK_API_KEY = st.secrets.get("GROK_API_KEY")
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY")
grok_client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1") if GROK_API_KEY else None

# --- ARAMA PARAMETRELERİ (Stratejinin Kalbi)
TARGET_DOMAINS = [
    "twitter.com", "aa.com.tr", "dha.com.tr", "iha.com.tr",
    "hurriyet.com.tr", "milliyet.com.tr", "sozcu.com.tr", "ntv.com.tr",
    "cnnturk.com", "haberturk.com"
]
SEARCH_KEYWORDS = ["fabrika", "sanayi", "OSB", "liman", "depo", "tesis", "maden", "rafineri"]
RISK_KEYWORDS = ["yangın", "patlama", "kaza", "sızıntı", "göçük", "hasar"]

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner="Maksimum Kapsama Taraması başlatıldı. Güvenilir kaynaklar (X, AA, DHA vb.) taranıyor...")
def run_max_coverage_search(date_option):
    """Tavily'nin gelişmiş özelliklerini kullanarak tek ve güçlü bir arama yapar."""
    if not TAVILY_API_KEY:
        st.error("Tavily API anahtarı bulunamadı.")
        return None
    
    # 1. Tek ve En Güçlü Sorguyu Oluştur
    location_query = " OR ".join(f'"{k}"' for k in SEARCH_KEYWORDS)
    risk_query = " OR ".join(f'"{k}"' for k in RISK_KEYWORDS)
    full_query = f"Türkiye ({location_query}) ({risk_query}) son {date_option.lower()}"
    
    try:
        # 2. Tavily'nin Tüm Gücünü Kullan
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": full_query,
                "search_depth": "advanced",      # En derin arama
                "include_domains": TARGET_DOMAINS, # Sadece bu sitelerde ara (En Kritik İyileştirme)
                "max_results": 25                # Maksimum kanıt için sonuç sayısını artır
            }
        )
        response.raise_for_status()
        results = response.json()
        
        context = "KANIT DOSYASI:\n\n"
        for i, result in enumerate(results.get('results', [])):
            context += f"Kaynak {i+1}:\nBaşlık: {result['title']}\nURL: {result['url']}\nÖzet: {result['content']}\n\n"
        return context
    except Exception as e:
        st.error(f"Tavily Arama API'si hatası: {e}")
        return None

@st.cache_data(ttl=3600, show_spinner="Grok AI, toplanan kapsamlı kanıtları sentezleyip nihai raporu oluşturuyor...")
def generate_final_report(_client, evidence_context, date_option):
    """Toplanan kanıtlardan nihai raporu oluşturur."""
    if not _client:
        st.error("Grok API anahtarı bulunamadı."); return None
        
    user_objective = f"Türkiye'de son {date_option.lower()} içinde gerçekleşmiş, KANIT DOSYASI içinde bulunan tüm endüstriyel hasarları listele."
    prompt = f"""
    Sen, kanıta dayalı çalışan bir Baş İstihbarat Analistisin. Halüsinasyona sıfır toleransın var. Sadece sana sunulan KANIT DOSYASI'ndaki bilgileri kullanacaksın.

    KULLANICININ ANA HEDEFİ: "{user_objective}"
    SANA SUNULAN KANIT DOSYASI (X ve Güvenilir Haber Ajanslarından Gelen Sonuçlar):
    ---
    {evidence_context}
    ---
    GÖREVİN: Kanıt dosyasını analiz et ve kullanıcının hedefine uygun, bulduğun TÜM olayları içeren, duplikeleri birleştirilmiş tek bir Markdown tablosu oluştur.
    Şirket adını bulmaya ve teyit etmeye özel olarak odaklan. Eğer bir bilgi kanıtlarda yoksa "Belirtilmemiş" yaz. ASLA TAHMİN YÜRÜTME.

    İSTENEN ÇIKTI FORMATI:
    | Sıra | Tarih | Şirket Adı | Açıklama ve Teyit | Hasarın Etkisi | Etkilenen Çevre Tesisleri (Detaylı Etki) | Referans URL |
    |------|-------|------------|-------------------|----------------|-------------------------------------------|--------------|
    """
    try:
        response = _client.chat.completions.create(
            model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}],
            max_tokens=4096, temperature=0.0, timeout=300.0
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Grok AI rapor oluştururken hata: {e}"); return None

# ------------------------------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------

st.subheader("1. Adım: Arama Parametresini Seçin")
date_option = st.selectbox(
    "Hangi Zaman Aralığı İçin Kapsamlı Tarama Yapılsın?",
    ("45 gün", "3 ay", "6 ay", "1 yıl")
)

st.subheader("2. Adım: Ajanı Başlatın")
if st.button("Maksimum Kapsama Taraması Yap ve Rapor Oluştur", type="primary", use_container_width=True):
    if not TAVILY_API_KEY or not GROK_API_KEY:
        st.error("Lütfen hem Grok hem de Tavily API anahtarlarını eklediğinizden emin olun.")
    else:
        evidence = run_max_coverage_search(date_option)
        if evidence and len(evidence) > 50:
            st.session_state.evidence_context = evidence
            final_report = generate_final_report(grok_client, evidence, date_option)
            st.session_state.final_report = final_report
        else:
            st.warning("Yapılan kapsamlı arama sonucunda analiz edilecek yeterli kanıt bulunamadı. Lütfen daha geniş bir tarih aralığı deneyin.")

# --- SONUÇLARI GÖSTER ---
if 'final_report' in st.session_state and st.session_state.final_report:
    st.markdown("---")
    st.subheader("Nihai İstihbarat Raporu")
    st.markdown(st.session_state.final_report)

    with st.expander("Ajanın Analiz Ettiği Ham Kanıtları Gör (Şeffaflık Raporu)"):
        st.text_area("Tavily'den Gelen Kanıt Dosyası", st.session_state.get('evidence_context', ''), height=400)
