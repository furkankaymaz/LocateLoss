# ==============================================================================
#  NİHAİ KOD (v62.0): Rafine Otonom Ajan
#  MİMARİ: LangChain Agent (Beyin: Grok, Araç: Tavily)
#  AMAÇ: v57.0'ın başarılı otonom mantığını, daha akıllı ve kapsamlı bir
#  görev tanımı ile en iyi hale getirmek.
# ==============================================================================
import streamlit as st
import os
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.prompts import ChatPromptTemplate
import io
from contextlib import redirect_stdout
from datetime import datetime, timedelta

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE API ANAHTARLARI
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Otonom İstihbarat Ajanı")
st.title("🛰️ Otonom İstihbarat Ajanı")
st.info("Bu ajan, verilen genel hedef doğrultusunda, otonom olarak en iyi araştırma stratejisini belirler, kanıt toplar ve nihai raporu oluşturur.")


# --- API Anahtarlarını Streamlit Secrets'tan güvenli bir şekilde al
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY")
GROK_API_KEY = st.secrets.get("GROK_API_KEY")

# ------------------------------------------------------------------------------
# 2. OTONOM AJANIN KURULUMU VE ÇALIŞTIRILMASI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600) # Aynı görev için sonucu 1 saat hafızada tut
def run_autonomous_agent(user_objective):
    """
    Verilen hedef doğrultusunda, LangChain ile inşa edilmiş otonom bir ajanı çalıştırır.
    Ajanın düşünce sürecini ve nihai çıktısını döndürür.
    """
    if not TAVILY_API_KEY or not GROK_API_KEY:
        st.error("Lütfen hem Grok hem de Tavily API anahtarlarını Streamlit Secrets'a ekleyin.")
        return None, None

    # 1. Adım: Ajanın Araçlarını Tanımla (Tavily Arama Motoru)
    # Daha fazla sonuç alarak kapsamı artırıyoruz.
    tools = [TavilySearchResults(max_results=10)]

    # 2. Adım: Ajanın Beynini Tanımla (Grok API - Doğru Model Adı ile)
    llm = ChatOpenAI(
        model_name="mixtral-8x7b-32768", # Çalışan ve güçlü bir model
        openai_api_key=GROK_API_KEY,
        openai_api_base="https://api.x.ai/v1",
        temperature=0,
        streaming=False # Streamlit ile daha stabil çalışması için
    )

    # 3. Adım: Ajanın Karakterini ve Görevini Tanımlayan Prompt'u Oluştur
    prompt = ChatPromptTemplate.from_messages([
        ("system", """Sen, Türkiye'deki güncel endüstriyel hasarlar konusunda uzman, sıfır halüsinasyon ilkesiyle çalışan bir istihbarat analistisin.

        ANA GÖREVİN (MİSYON): Sana verilen zaman aralığı içinde Türkiye'de gerçekleşmiş, sigortacılık açısından önemli tüm endüstriyel hasarları (fabrika, depo, OSB, liman, maden vb.) bulmak ve raporlamak.

        YOL GÖSTERİCİ İLKELERİN:
        1.  **Kapsamlı Ol:** Sadece bir iki olay bulup durma. Görevin, mümkün olan en fazla sayıda anlamlı olayı ortaya çıkarmak. Bunun için farklı anahtar kelimelerle, farklı şehir ve sektörleri hedefleyerek birden çok arama yapmaktan çekinme. Amacın hiçbir önemli olayı kaçırmamak.
        2.  **Tesis Adı Önceliği:** Raporunun en değerli kısmı tesis adıdır. Teyit edilmiş bir ticari unvan bulmak için tüm kanıtları dikkatle incele.
        3.  **Güncelliği Koru:** Sadece sana belirtilen tarih aralığına odaklan.
        4.  **Kanıta Daya:** Her bir bilgiyi, arama sonuçlarından bulduğun bir kaynağa dayandır.
        5.  **Standartlara Uy:** Nihai çıktın, SADECE istenen formatta bir Markdown tablosu olmalıdır.

        İSTENEN ÇIKTI FORMATI:
        | Sıra | Tarih | Şirket Adı | Açıklama ve Teyit | Hasarın Etkisi | Referans URL |
        |------|-------|------------|-------------------|----------------|--------------|
        """),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    # 4. Adım: Ajanı İnşa Et
    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True)

    # 5. Adım: Ajanı Görevlendir ve Düşünce Sürecini Yakala
    thought_process_stream = io.StringIO()
    try:
        with redirect_stdout(thought_process_stream):
            result = agent_executor.invoke({"input": user_objective})
        
        thought_process = thought_process_stream.getvalue()
        final_output = result.get("output", "Bir çıktı üretilemedi.")
        return final_output, thought_process
        
    except Exception as e:
        st.error(f"Ajan çalışırken bir hata oluştu: {e}")
        return None, thought_process_stream.getvalue()

# ------------------------------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------

# Tarih aralığını dinamik olarak hesapla
today = datetime.now()
start_date = today - timedelta(days=45)
date_range_str = f"{start_date.strftime('%d %B %Y')} - {today.strftime('%d %B %Y')}"

st.subheader("1. Adım: Ajanın Ana Görevini Onaylayın")
# Ajanın ana hedefi artık sabit, net ve optimize edilmiş.
user_objective = st.text_area(
    "Ajanın araştırmasını istediğiniz ana hedef:",
    f"Türkiye'de {date_range_str} tarihleri arasında gerçekleşmiş, basına yansımış (X dahil), sigortacılık açısından önemli ve hiçbir önemli olayı atlamayan kapsamlı bir endüstriyel hasar listesi oluştur. Her olay için tesis adını, tarihini, olayın özetini, etkilerini ve en güvenilir referans URL'ini içeren bir Markdown tablosu hazırla.",
    height=150
)

st.subheader("2. Adım: Ajanı Başlatın")
if st.button("Otonom Araştırmayı Başlat", type="primary", use_container_width=True):
    with st.spinner("Otonom Ajan çalışıyor... Bu işlem, araştırmanın derinliğine göre birkaç dakika sürebilir. Ajan, en iyi sonuçları bulmak için arka planda birden çok arama yapmaktadır."):
        final_report, thought_process = run_autonomous_agent(user_objective)
        st.session_state.final_report = final_report
        st.session_state.thought_process = thought_process

# --- SONUÇLARI GÖSTER ---
if 'final_report' in st.session_state and st.session_state.final_report:
    st.markdown("---")
    st.subheader("Ajanın Nihai Raporu")
    st.markdown(st.session_state.final_report)

    with st.expander("Ajanın Düşünce Sürecini Göster (Şeffaf Rapor)"):
        st.text_area("Ajanın Adım Adım Düşünceleri ve Yaptığı Aramalar:", 
                     st.session_state.get('thought_process', 'Düşünce süreci kaydedilemedi.'), 
                     height=400)
