# ==============================================================================
#  NİHAİ KOD (v49.0): Odaklanmış X Tarayıcısı
#  AMAÇ: Sadece X (Twitter) üzerinde maliyetsiz arama yaparak tesis adı bulmak.
# ==============================================================================
import streamlit as st
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from urllib.parse import quote
import re

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Odaklanmış X Tarayıcısı")
st.title("🛰️ Odaklanmış X (Twitter) Tarayıcısı")
st.info("Bu araç, API kullanmadan doğrudan X üzerinde arama yaparak endüstriyel hasar olaylarındaki tesis adlarını bulmaya odaklanmıştır.")

# --- API Bağlantısı
grok_api_key = st.secrets.get("GROK_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner="X arama sonuçları taranıyor...")
def scrape_x_search(search_query):
    """
    Verilen arama sorgusu ile X'in web arayüzünü tarar ve sayfanın ham metin içeriğini döndürür.
    Bu yöntem kırılgandır ve X'in güncellemeleriyle bozulabilir.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    # Gelişmiş arama URL'si kullanarak daha isabetli sonuçlar hedeflenir
    url = f"https://twitter.com/search?q={quote(search_query)}&src=typed_query&f=live"
    
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        # Sayfadaki tüm görünür metinleri temiz bir şekilde al
        return soup.get_text(separator='\n', strip=True)
    except requests.exceptions.RequestException as e:
        st.error(f"X'e bağlanırken bir ağ hatası oluştu. Engellenmiş olabiliriz. Hata: {e}")
        return None
    except Exception as e:
        st.error(f"Sayfa işlenirken beklenmedik bir hata oluştu: {e}")
        return None

@st.cache_data(ttl=3600, show_spinner="AI, taranan metinleri analiz ediyor...")
def extract_facility_tweets_from_text(_client, raw_text):
    """
    Ham metin içerisinden, şirket/tesis adı içeren ilgili tweet'leri AI ile ayıklar.
    """
    if not raw_text or len(raw_text) < 100:
        return "Taranan metin çok kısa veya boş, analiz yapılamadı."

    prompt = f"""
    Sen, yapısal olmayan metinlerden bilgi çıkarma konusunda uzman bir OSINT analistisin.
    Sana, bir X (Twitter) arama sayfasından taranmış ham metin veriyorum.

    GÖREVİN:
    1.  Bu metin yığını içindeki bireysel tweet'leri bul.
    2.  Sadece ve sadece bir endüstriyel tesisin (fabrika, depo, sanayi tesisi vb.) **ticari unvanını** veya **spesifik adını** içeren tweet'leri ayıkla. Genel ifadeleri ("bir fabrikada yangın") görmezden gel.
    3.  Bulduğun her bir anlamlı tweet'i tam metin olarak, başına tire (-) koyarak listele.

    Eğer metin içinde spesifik bir şirket adı geçen ilgili bir tweet bulamazsan, sadece "Spesifik bir şirket adı içeren tweet bulunamadı." yaz.

    HAM METİN:
    ---
    {raw_text[:15000]} 
    ---
    """
    try:
        response = _client.chat.completions.create(
            model="grok-4-fast-reasoning",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.0,
            timeout=90.0
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI analizi sırasında bir hata oluştu: {e}"

# ------------------------------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------

st.subheader("1. Adım: Arama Sorgusu Girin")
search_query = st.text_input(
    "Aramak istediğiniz olayın anahtar kelimelerini girin (örn: Gebze OSB patlama)",
    placeholder="örn: Dilovası kimya fabrikası yangın"
)

if st.button("X'te Tara ve Analiz Et", type="primary", use_container_width=True):
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin.")
    elif not search_query:
        st.warning("Lütfen arama yapmak için anahtar kelimeler girin.")
    else:
        st.session_state.search_query = search_query
        
        # Önceki sonuçları temizle
        st.session_state.raw_text = None
        st.session_state.final_report = None
        
        st.session_state.raw_text = scrape_x_search(search_query)
        if st.session_state.raw_text:
            st.session_state.final_report = extract_facility_tweets_from_text(client, st.session_state.raw_text)

if 'final_report' in st.session_state and st.session_state.final_report:
    st.markdown("---")
    st.subheader("2. Adım: Analiz Sonuçları")
    
    st.success("**AI Tarafından Ayıklanan ve Tesis Adı İçeren Tweetler:**")
    st.markdown(st.session_state.final_report)
    
    with st.expander("Taranan Ham Metni Görüntüle (Teknik İnceleme İçin)"):
        st.text_area("Scraper'ın X'ten Çektiği Ham Veri", st.session_state.get('raw_text', 'Veri bulunamadı.'), height=300)
