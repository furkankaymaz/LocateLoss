# ==============================================================================
#  NİHAİ KOD (v51.0): Oto-İstihbarat Ajanı (Tavily Search + Grok API)
#  AMAÇ: Kullanıcının genel sorgusunu otomatik olarak araştırıp, kanıta dayalı
#  nihai bir rapor oluşturmak.
# ==============================================================================
import streamlit as st
import requests
from openai import OpenAI
import os

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE GİZLİ ANAHTARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Oto-İstihbarat Ajanı")
st.title("🛰️ Oto-İstihbarat Ajanı")
st.info("Bu araç, girilen genel sorguyu profesyonel bir arama motoru (Tavily) ile araştırır ve toplanan kanıtları Grok AI ile analiz ederek nihai bir rapor oluşturur.")

# --- API Anahtarlarını Streamlit Secrets'tan güvenli bir şekilde al
GROK_API_KEY = st.secrets.get("GROK_API_KEY")
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY")

# --- API İstemcilerini Başlat
grok_client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1") if GROK_API_KEY else None

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR: ARAŞTIRMA VE ANALİZ
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner="Profesyonel Arama Motoru (Tavily) kanıtları topluyor...")
def run_professional_search(query):
    """
    Tavily Arama API'sini kullanarak interneti tarar ve analiz için bir kanıt listesi oluşturur.
    """
    if not TAVILY_API_KEY:
        st.error("Tavily API anahtarı bulunamadı. Lütfen Streamlit Secrets'a ekleyin.")
        return None
    
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced", # Daha derinlemesine arama
                "include_answer": False,
                "max_results": 10 # Analiz için en iyi 10 sonucu al
            }
        )
        response.raise_for_status()
        results = response.json()
        
        # AI'nın analiz etmesi için kanıtları temiz bir formatta birleştir
        context = "KANIT DOSYASI:\n\n"
        for i, result in enumerate(results['results']):
            context += f"Kaynak {i+1}:\n"
            context += f"Başlık: {result['title']}\n"
            context += f"URL: {result['url']}\n"
            context += f"Özet: {result['content']}\n\n"
        return context
    except Exception as e:
        st.error(f"Tavily Arama API'si ile kanıt toplanırken hata oluştu: {e}")
        return None

@st.cache_data(ttl=3600, show_spinner="Grok AI, toplanan kanıtları analiz edip raporu oluşturuyor...")
def generate_final_report(_client, user_query, evidence_context):
    """
    Toplanan kanıtları ve kullanıcının orijinal sorgusunu kullanarak nihai raporu oluşturur.
    """
    if not _client:
        st.error("Grok API anahtarı bulunamadı. Lütfen Streamlit Secrets'a ekleyin.")
        return None
        
    prompt = f"""
    Sen, kanıta dayalı çalışan bir Baş İstihbarat Analistisin. Halüsinasyona sıfır toleransın var. Sadece sana sunulan KANIT DOSYASI'ndaki bilgileri kullanacaksın.

    KULLANICININ ANA HEDEFİ: "{user_query}"

    SANA SUNULAN KANIT DOSYASI (Gerçek zamanlı internet arama sonuçları):
    ---
    {evidence_context}
    ---

    GÖREVİN:
    1. Yukarıdaki KANIT DOSYASI'nı dikkatlice incele.
    2. Kullanıcının ana hedefini karşılayacak şekilde, bu kanıtlara dayanarak, aşağıdaki detaylı tablo formatında bir rapor oluştur.
    3. Eğer bir bilgi (örn: reasürans detayı) kanıtlarda mevcut değilse, o hücreye "Kanıtlarda Belirtilmemiş" yaz. ASLA TAHMİN YÜRÜTME veya bilgi uydurma.
    4. Tüm olayları, duplicate olmadan, tek bir Markdown tablosunda sun.
    5. Referans URL sütununa, bilgiyi aldığın kaynağın URL'ini ekle.

    İSTENEN ÇIKTI FORMATI:
    | Sıra | Tarih | Şirket Adı | Açıklama ve Teyit | Hasarın Etkisi | Etkilenen Çevre Tesisleri (Detaylı Etki) | Referans URL |
    |------|-------|------------|-------------------|----------------|-------------------------------------------|--------------|

    """
    try:
        response = _client.chat.completions.create(
            model="grok-4-fast-reasoning",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096, # Raporun uzun olabilmesi için
            temperature=0.0, # Maksimum tutarlılık ve kanıta bağlılık
            timeout=180.0 # Bu karmaşık işlem için daha uzun zaman aşımı
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Grok AI ile rapor oluşturulurken hata oluştu: {e}")
        return None

# ------------------------------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------

st.subheader("1. Adım: Otomatik Sorgu Oluşturun")

# Tarih aralığı seçimi
date_option = st.selectbox(
    "Hangi Zaman Aralığını Taramak İstersiniz?",
    ("Son 45 Gün", "Son 3 Ay", "Son 6 Ay", "Son 1 Yıl")
)

# Detay seviyesi seçimi
detail_level = st.selectbox(
    "Ne Kadar Detay İstiyorsunuz?",
    ("Tüm Detaylar (Sigorta, Çevre Etkisi vb.)", "Sadece Tesis Adı ve Olay Özeti")
)

# Seçimlere göre otomatik sorgu oluşturma
base_query = f"Türkiye'de {date_option.lower()} içinde gerçekleşmiş endüstriyel hasarları (fabrika, depo, OSB, liman, maden) bul."
if "Tüm Detaylar" in detail_level:
    full_query = f"{base_query} Bu olayları firma ismini net belirterek, farklı kaynaklardan teyit edip, sigortacılık açısından anlamlı detaylar (hasarın etkisi, etkilenen çevre tesisleri ve onlara olan etkiler) ile birlikte listeleyin. Hiçbir önemli olayı atlamayın."
else:
    full_query = f"{base_query} Bu olayları sadece tesis adını ve olayın kısa bir özetini içerecek şekilde listeleyin."

user_query = st.text_area("Oluşturulan Otomatik Sorgu (İsterseniz düzenleyebilirsiniz):", full_query, height=150)

st.subheader("2. Adım: Ajanı Başlatın")

if st.button("Araştır ve Rapor Oluştur", type="primary", use_container_width=True):
    if not TAVILY_API_KEY or not GROK_API_KEY:
        st.error("Lütfen hem Grok hem de Tavily API anahtarlarını Streamlit Secrets'a eklediğinizden emin olun.")
    else:
        # Önceki sonuçları temizle
        st.session_state.final_report = None
        st.session_state.evidence_context = None

        # Ajanı çalıştır
        evidence = run_professional_search(user_query)
        if evidence:
            st.session_state.evidence_context = evidence
            final_report = generate_final_report(grok_client, user_query, evidence)
            st.session_state.final_report = final_report

# --- SONUÇLARI GÖSTER ---
if 'final_report' in st.session_state and st.session_state.final_report:
    st.markdown("---")
    st.subheader("Nihai İstihbarat Raporu")
    st.markdown(st.session_state.final_report)

    with st.expander("Ajanın Analiz Ettiği Ham Kanıtları Gör (Şeffaflık Raporu)"):
        st.text_area("Tavily'den Gelen Kanıt Dosyası", st.session_state.get('evidence_context', 'Kanıt bulunamadı.'), height=400)
