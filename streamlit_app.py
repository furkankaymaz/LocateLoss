# ==============================================================================
#  NİHAİ KOD (v61.0): Bilgilendirilmiş Otonom Ajan
#  MİMARİ: Önce RSS ile hızlıca güncel olaylar toplanır, sonra bu "ipuçları"
#  ile beslenen otonom ajan derinlemesine araştırma yapar.
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
import feedparser
from rapidfuzz import fuzz
from urllib.parse import quote
import re
import time

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Bilgilendirilmiş Ajan")
st.title("🛰️ Bilgilendirilmiş Otonom İstihbarat Ajanı")
st.info("Bu ajan, önce Google News'ten en güncel hasar ipuçlarını toplar, ardından bu ipuçlarını kullanarak otonom bir şekilde derinlemesine araştırma yapar ve nihai raporu oluşturur.")

# --- API Anahtarları
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY")
GROK_API_KEY = st.secrets.get("GROK_API_KEY")

# ------------------------------------------------------------------------------
# 2. AJANIN DESTEK FONKSİYONLARI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner="En güncel hasar başlıkları Google News'ten toplanıyor...")
def get_rss_leads():
    """Google News RSS'ten en son olayları çeker ve ajanın görevi için ipucu listesi oluşturur."""
    locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo"'
    events = '"yangın" OR "patlama" OR "kaza" OR "sızıntı" OR "göçük"'
    q = f'({locations}) AND ({events})'
    # Son 7 günü tara
    rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return "Google News'te güncel bir olay bulunamadı."
        
        sorted_entries = sorted(feed.entries, key=lambda e: getattr(e, 'published_parsed', time.gmtime(0)), reverse=True)
        unique_articles, seen_headlines = [], []
        
        for entry in sorted_entries:
            headline = entry.title.split(" - ")[0].strip()
            if not any(fuzz.ratio(headline, seen) > 85 for seen in seen_headlines):
                unique_articles.append(f"- {headline}")
                seen_headlines.append(headline)
        
        return "\n".join(unique_articles[:20]) # En güncel 20 başlığı ipucu olarak al
    except Exception as e:
        return f"RSS akışı okunurken hata oluştu: {e}"

# ------------------------------------------------------------------------------
# 3. OTONOM AJANIN KURULUMU VE ÇALIŞTIRILMASI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def run_informed_agent(user_objective):
    """
    Önceden toplanmış ipuçları ile beslenen otonom ajanı çalıştırır.
    """
    if not TAVILY_API_KEY or not GROK_API_KEY:
        st.error("Lütfen hem Grok hem de Tavily API anahtarlarını Streamlit Secrets'a ekleyin.")
        return None, None

    tools = [TavilySearchResults(max_results=7)]
    llm = ChatOpenAI(model_name="grock-4-fast-reasoning", openai_api_key=GROK_API_KEY, openai_api_base="https://api.x.ai/v1", temperature=0, streaming=False)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """Sen, Türkiye'deki güncel endüstriyel hasarlar konusunda uzman bir OSINT analistisin.
        ANA GÖREVİN: Sana verilen zaman aralığındaki ve ön istihbarat listesindeki TÜM olayları derinlemesine araştırarak kapsamlı bir rapor oluşturmak.
        YOL GÖSTERİCİ İLKELERİN:
        1. KAPSAMLI OL: Sana verilen "Ön İstihbarat" listesindeki her bir başlığı araştır. Ayrıca bu listenin kaçırmış olabileceği başka olaylar olup olmadığını da kontrol et.
        2. TESİS ADI ÖNCELİĞİ: Raporunun en değerli kısmı tesis adıdır. Teyit edilmiş bir ticari unvan bulmak için tüm kanıtları dikkatle incele.
        3. GÜNCELLİĞİ KORU: Sadece belirtilen tarih aralığına odaklan.
        4. KANITA DAYA: Her bilgiyi, arama sonuçlarından bulduğun bir kaynağa dayandır.
        5. STANDARTLARA UY: Nihai çıktın, SADECE istenen formatta bir Markdown tablosu olmalıdır.
        İSTENEN ÇIKTI FORMATI:
        | Sıra | Tarih | Şirket Adı | Açıklama ve Teyit | Hasarın Etkisi | Etkilenen Çevre Tesisleri | Referans URL |
        |------|-------|------------|-------------------|----------------|---------------------------|--------------|
        """),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True)

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
# 4. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------

# Tarih aralığını dinamik olarak hesapla
today = datetime.now()
start_date = today - timedelta(days=45)
date_range_str = f"{start_date.strftime('%d %B %Y')} - {today.strftime('%d %B %Y')}"

st.subheader("Görev: Son 45 Günlük Endüstriyel Hasar Raporu")

if st.button("Güncel Hasar Raporunu Oluştur", type="primary", use_container_width=True):
    # 1. Adım: Hızlıca RSS'ten ipuçlarını topla
    rss_leads = get_rss_leads()
    st.session_state.rss_leads = rss_leads

    # 2. Adım: Ajan için ana görevi ve ipuçlarını birleştirerek oluştur
    user_objective = f"""
    Türkiye'de {date_range_str} tarihleri arasında gerçekleşmiş, basına yansımış (X dahil), sigortacılık açısından önemli tüm endüstriyel hasarları bul ve raporla.

    Sana yardımcı olmak için, yaptığım hızlı ön taramada bulduğum güncel olay başlıkları şunlar (bunları araştır ve eksik kalanları da sen bul):
    ---
    {rss_leads}
    ---
    """
    
    # 3. Adım: Bilgilendirilmiş Ajanı Çalıştır
    with st.spinner("Ajan, ön istihbaratı analiz ediyor ve derinlemesine araştırma yapıyor... Bu işlem birkaç dakika sürebilir."):
        final_report, thought_process = run_informed_agent(user_objective)
        st.session_state.final_report = final_report
        st.session_state.thought_process = thought_process

# --- SONUÇLARI GÖSTER ---
if 'final_report' in st.session_state and st.session_state.final_report:
    st.markdown("---")
    st.subheader("Ajanın Nihai Raporu")
    st.markdown(st.session_state.final_report)

    with st.expander("Ajanın Çalışma Detayları (Şeffaflık Raporu)"):
        st.write("**Ajan'a Verilen Görev ve Ön İstihbarat (İpuçları):**")
        st.text_area("RSS'ten Gelen İpuçları", st.session_state.get('rss_leads', ''), height=200)
        st.write("**Ajanın Düşünce Süreci:**")
        st.text_area("Ajanın Adım Adım Düşünceleri ve Yaptığı Aramalar:", 
                     st.session_state.get('thought_process', ''), 
                     height=400)
