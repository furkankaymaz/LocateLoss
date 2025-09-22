# ==============================================================================
#  NİHAİ KOD (v57.0) Otonom İstihbarat Ajanı Arayüzü
#  MİMARİ LangChain Agent (Beyin Grok, Araç Tavily)
#  AMAÇ Kullanıcının genel hedefini, otonom olarak araştırıp raporlayan bir
#  Streamlit uygulaması sunmak.
# ==============================================================================
import streamlit as st
import os
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.prompts import ChatPromptTemplate
import io
from contextlib import redirect_stdout

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE API ANAHTARLARI
# ------------------------------------------------------------------------------
st.set_page_config(layout=wide, page_title=Otonom İstihbarat Ajanı)
st.title(🛰️ Otonom İstihbarat Ajanı)

# --- API Anahtarlarını Streamlit Secrets'tan güvenli bir şekilde al
TAVILY_API_KEY = st.secrets.get(TAVILY_API_KEY)
GROK_API_KEY = st.secrets.get(GROK_API_KEY)

# ------------------------------------------------------------------------------
# 2. OTONOM AJANIN KURULUMU VE ÇALIŞTIRILMASI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600) # Aynı sorgu için 1 saat boyunca sonucu hafızada tut
def run_autonomous_agent(user_objective)
    
    Verilen hedef doğrultusunda, LangChain ile inşa edilmiş otonom bir ajanı çalıştırır.
    Ajanın düşünce sürecini ve nihai çıktısını döndürür.
    
    if not TAVILY_API_KEY or not GROK_API_KEY
        st.error(Lütfen hem Grok hem de Tavily API anahtarlarını Streamlit Secrets'a ekleyin.)
        return None, None

    # 1. Adım Ajanın Araçlarını Tanımla (Tavily Arama Motoru)
    tools = [TavilySearchResults(max_results=7)]

    # 2. Adım Ajanın Beynini Tanımla (Grok API)
    llm = ChatOpenAI(
        model_name=grok-4-fast-reasoning,
        openai_api_key=GROK_API_KEY,
        openai_api_base=httpsapi.x.aiv1,
        temperature=0,
        streaming=False # Streamlit ile daha stabil çalışması için
    )

    # 3. Adım Ajanın Karakterini ve Görevini Tanımlayan Prompt'u Oluştur
    prompt = ChatPromptTemplate.from_messages([
        (system, Sen, Türkiye'deki endüstriyel hasarlar konusunda uzman bir istihbarat analistisin. Görevin, sana verilen hedef doğrultusunda, arama aracını kullanarak en kapsamlı ve doğru bilgiyi bulmaktır. Bulduğun her bir olay için mutlaka bir referans URL'i belirt. Cevabını her zaman Türkçe ve tüm olayları içeren tek bir Markdown tablosu formatında ver.),
        (human, {input}),
        (placeholder, {agent_scratchpad}),
    ])

    # 4. Adım Ajanı İnşa Et
    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

    # 5. Adım Ajanı Görevlendir ve Düşünce Sürecini Yakala
    thought_process_stream = io.StringIO()
    try
        with redirect_stdout(thought_process_stream)
            result = agent_executor.invoke({input user_objective})
        
        thought_process = thought_process_stream.getvalue()
        final_output = result.get(output, Bir çıktı üretilemedi.)
        return final_output, thought_process
        
    except Exception as e
        st.error(fAjan çalışırken bir hata oluştu {e})
        return None, thought_process_stream.getvalue()

# ------------------------------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------

st.subheader(1. Adım Ajanın Ana Görevini Belirleyin)
default_objective = Türkiye'de son 45 günde (bugün 22 Eylül 2025) gerçekleşmiş, basına yansımış tüm endüstriyel hasarları (fabrika, depo, OSB, liman, maden, rafineri) bul. Her olay için tesis adını, olayın kısa özetini, biliniyorsa etkilerini ve en güvenilir referans URL'ini içeren, duplikeleri temizlenmiş bir Markdown tablosu oluştur.

user_objective = st.text_area(
    Ajanın araştırmasını istediğiniz ana hedefi girin,
    default_objective,
    height=150
)

st.subheader(2. Adım Ajanı Başlatın)
if st.button(Otonom Araştırmayı Başlat, type=primary, use_container_width=True)
    with st.spinner(Otonom Ajan çalışıyor... Bu işlem, araştırmanın derinliğine göre birkaç dakika sürebilir. Ajan, en iyi sonuçları bulmak için arka planda birden çok arama yapmaktadır.)
        final_report, thought_process = run_autonomous_agent(user_objective)
        st.session_state.final_report = final_report
        st.session_state.thought_process = thought_process

# --- SONUÇLARI GÖSTER ---
if 'final_report' in st.session_state and st.session_state.final_report
    st.markdown(---)
    st.subheader(Ajanın Nihai Raporu)
    st.markdown(st.session_state.final_report)

    with st.expander(Ajanın Düşünce Sürecini Göster (Şeffaflık Raporu))
        st.text_area(Ajanın Adım Adım Düşünceleri ve Yaptığı Aramalar, 
                     st.session_state.get('thought_process', 'Düşünce süreci kaydedilemedi.'), 
                     height=400)
