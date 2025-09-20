import streamlit as st
import requests
import json
import folium
from streamlit_folium import folium_static
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter  # Rate limit için
import googlemaps
import pandas as pd
import re  # Parse için

# Grok API ayarları
GROK_API_URL = "https://api.grok.x.ai/v1/chat/completions"
GROK_API_KEY = st.secrets.get("GROK_API_KEY", "")

# Google Maps API anahtarı
GMAPS_API_KEY = st.secrets.get("GMAPS_API_KEY", "")

# Geocoder (rate limited)
geolocator = Nominatim(user_agent="impact_map_app")
geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)

def call_grok_api(query):
    if not GROK_API_KEY:
        st.error("GROK_API_KEY secrets'ta tanımlanmamış!")
        return None
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "grok-beta",  # Veya "grok-2" dene
        "messages": [{"role": "user", "content": query}],
        "max_tokens": 1500
    }
    response = requests.post(GROK_API_URL, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        st.error(f"Grok API hatası: {response.status_code} - {response.text}")
        return None

def parse_grok_response(response):
    facilities = []
    # Regex ile "Fabrika Adı: X", "Adres: Y", "Hasar: Z" pattern'leri yakala
    name_pattern = r"Fabrika Adı[:\s]+(.+?)(?=\n|$)"
    addr_pattern = r"Adres[:\s]+(.+?)(?=\n|$)"
    damage_pattern = r"Hasar Etkisi[:\s]+(.+?)(?=\n|$)"
    
    names = re.findall(name_pattern, response, re.IGNORECASE | re.DOTALL)
    addrs = re.findall(addr_pattern, response, re.IGNORECASE | re.DOTALL)
    damages = re.findall(damage_pattern, response, re.IGNORECASE | re.DOTALL)
    
    # Eşleştir (basitçe zip'le, gerçekte daha akıllı yap)
    max_len = max(len(names), len(addrs), len(damages))
    for i in range(max_len):
        fac = {
            "name": names[i].strip() if i < len(names) else "Bilinmeyen",
            "address": (addrs[i].strip() if i < len(addrs) else "Bilinmeyen") + ", Türkiye",
            "damage": damages[i].strip() if i < len(damages) else "Bilinmeyen"
        }
        if fac["name"] != "Bilinmeyen":  # Boşları filtrele
            facilities.append(fac)
    return facilities

def get_coordinates(address):
    try:
        location = geocode(address)
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        st.warning(f"Koordinat hatası ({address}): {e}")
    return None

def find_neighbor_facilities(gmaps, lat, lng, radius=5000):
    if not GMAPS_API_KEY:
        st.warning("GMAPS_API_KEY yok, komşu tesisler atlanıyor.")
        return []
    try:
        places = gmaps.places_nearby(
            location=(lat, lng),
            radius=radius,
            keyword="fabrika OR tesis OR sanayi OR enerji"
        )
        neighbors = []
        for place in places.get("results", [])[:10]:  # Limit 10'a indir, quota için
            neighbors.append({
                "name": place["name"],
                "address": place.get("vicinity", "Bilinmeyen"),
                "lat": place["geometry"]["location"]["lat"],
                "lng": place["geometry"]["location"]["lng"]
            })
        return neighbors
    except Exception as e:
        st.warning(f"Komşu arama hatası: {e}")
        return []

def create_impact_map(facilities):
    if not facilities:
        return None
    m = folium.Map(location=[39.0, 35.0], zoom_start=6)
    gmaps = googlemaps.Client(key=GMAPS_API_KEY)
    
    for fac in facilities:
        coords = get_coordinates(fac["address"])
        if coords:
            folium.Marker(
                coords,
                popup=f"{fac['name']}<br>Hasar: {fac['damage']}",
                icon=folium.Icon(color="red", icon="info-sign")
            ).add_to(m)
            # Komşuları ekle (her tesis için 1 kez, quota için)
            neighbors = find_neighbor_facilities(gmaps, coords[0], coords[1])
            for neigh in neighbors:
                folium.Marker(
                    (neigh["lat"], neigh["lng"]),
                    popup=f"Komşu: {neigh['name']}<br>{neigh['address']}",
                    icon=folium.Icon(color="blue", icon="cloud")
                ).add_to(m)
    
    return m

# Streamlit App
st.title("Sigorta Risk Etki Haritası App")
st.write("Sorgu girin, Grok API ile analiz edin, harita oluşturun.")

query = st.text_area("Sorgu (örneğin: Türkiye'de son 30 günde yangın/deprem etkilenen tesisler)", height=100, value="Türkiyede son 30 günde yangından depremden patlamadan yani sigortaya konu risklerden etkilenen endüstriyel ve enerji tesislerini doğruluk oranlarıyla tespit edebilir misin fabrika adı adres hasar etkisini belirtmen yeterli")

if st.button("Analiz Et ve Harita Oluştur"):
    if not query.strip():
        st.warning("Sorgu boş olamaz!")
    else:
        with st.spinner("Grok API çağrılıyor..."):
            response = call_grok_api(query)
            if response:
                st.subheader("Grok Yanıtı")
                st.write(response)
                
                facilities = parse_grok_response(response)
                if facilities:
                    st.subheader("Tespit Edilen Tesisler")
                    df = pd.DataFrame(facilities)
                    st.dataframe(df)  # Table yerine dataframe, daha güzel
                    
                    st.subheader("Etki Haritası (Kırmızı: Etkilenen, Mavi: Komşu Tesisler)")
                    impact_map = create_impact_map(facilities)
                    if impact_map:
                        folium_static(impact_map, width=700, height=500)
                    else:
                        st.warning("Harita için koordinat veya API anahtarı sorunu.")
                else:
                    st.warning("Yanıtta tesis tespit edilemedi. Parse'i iyileştirin.")
