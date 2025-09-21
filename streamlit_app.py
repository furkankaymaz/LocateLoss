import streamlit as st
import pandas as pd
from openai import OpenAI
import json
import re

# API ayarları
API_SERVICE = "Grok_XAI" 
API_CONFIGS = {
    "Grok_XAI": {
        "base_url": "https://api.x.ai/v1",
        "model": "grok-beta",  # Alternatif model deneyelim
    }
}
SELECTED_CONFIG = API_CONFIGS[API_SERVICE]
API_KEY_NAME = "GROK_API_KEY"
api_key = st.secrets.get(API_KEY_NAME)

# Basitleştirilmiş sorgu fonksiyonu
def get_industrial_events():
    client = OpenAI(api_key=api_key, base_url=SELECTED_CONFIG["base_url"])
    
    prompt = """
    Türkiye'de 2024 yılı içinde meydana gelmiş büyük endüstriyel kaza, yangın veya patlama olaylarını listele.
    Sadece medyada yer almış, doğrulanmış olayları seç.
    Küçük ölçekli olayları dahil etme.
    
    Yanıtı JSON formatında ver:
    [{
      "tarih": "YYYY-MM-DD",
      "olay_tipi": "yangın/patlama/diğer",
      "yer": "Şehir, İlçe",
      "tesis": "Tesis adı veya tipi",
      "aciklama": "Kısa açıklama"
    }]
    """
    
    try:
        response = client.chat.completions.create(
            model=SELECTED_CONFIG["model"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3
        )
        content = response.choices[0].message.content.strip()
        
        # JSON veriyi ayıklama
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return []
        
    except Exception as e:
        st.error(f"Hata oluştu: {e}")
        return []

# Arayüz
st.title("Endüstriyel Hasar Sorgulama")
st.write("Basit sorgu denemesi")

if st.button("Olayları Sorgula"):
    with st.spinner("Sorgulanıyor..."):
        events = get_industrial_events()
    
    if events:
        st.success(f"{len(events)} olay bulundu!")
        df = pd.DataFrame(events)
        st.dataframe(df)
    else:
        st.warning("Hiç olay bulunamadı. Lütfen farklı parametrelerle deneyin.")
        st.info("""
        **Olası Sebepler:**
        1. Model bu tür spesifik sorgular için eğitilmemiş olabilir
        2. API kısıtlamaları olabilir
        3. Gerçekten bu dönemde kayda değer olay olmamış olabilir
        """)
