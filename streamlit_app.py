import streamlit as st
import requests
import json
import folium
from streamlit_folium import folium_static
from geopy.geocoders import Nominatim
import googlemaps
import pandas as pd

# Grok API ayarları (kullanıcının entegrasyonu mevcut)
GROK_API_URL = "https://api.grok.x.ai/v1/chat/completions"  # Grok API endpoint'i (doğru URL'yi kullanın)
GROK_API_KEY = st.secrets["GROK_API_KEY"]  # Streamlit secrets'ta saklayın veya environment variable

# Google Maps API anahtarı
GMAPS_API_KEY = st.secrets["GMAPS_API_KEY"]  # Secrets'ta saklayın

# Geocoder
geolocator = Nominatim(user_agent="impact_map_app")

def call_grok_api(query):
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "grok-beta",  # Veya uygun model (Grok 4 için ayarlayın)
        "messages": [{"role": "user", "content": query}],
        "max_tokens": 1500
    }
    response = requests.post(GROK_API_URL, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        st.error("Grok API hatası: " + response.text)
        return None

def parse_grok_response(response):
    # Basit parse: Tesisleri liste olarak çıkar (gerçekte NLP ile iyileştirin)
    facilities = []
    lines = response.split("\n")
    for line in lines:
        if "Fabrika Adı" in line or "Adres" in line:
            # Örnek parse; gerçekte regex veya AI kullanın
            name = line.split(":")[1].strip() if "Fabrika Adı" in line else "Bilinmeyen"
            address = line.split(":")[1].strip() if "Adres" in line else "Bilinmeyen"
            damage = line.split(":")[1].strip() if "Hasar" in line else "Bilinmeyen"
            facilities.append({"name": name, "address": address, "damage": damage})
    return facilities

def get_coordinates(address):
    location = geolocator.geocode(address + ", Türkiye")
    if location:
        return (location.latitude, location.longitude)
    return None

def find_neighbor_facilities(gmaps, lat, lng, radius=5000):
    # Places API ile endüstriyel/enerji tesisleri ara
    places = gmaps.places_nearby(
        location=(lat, lng),
        radius=radius,
        keyword="fabrika OR tesis OR sanayi OR enerji"  # Türkçe filtre
    )
    neighbors = []
    for place in places.get("results", []):
        neighbors.append({
            "name": place["name"],
            "address": place.get("vicinity", "Bilinmeyen"),
            "lat": place["geometry"]["location"]["lat"],
            "lng": place["geometry"]["location"]["lng"]
        })
    return neighbors

def create_impact_map(facilities):
    if not facilities:
        return None
    m = folium.Map(location=[39.0, 35.0], zoom_start=6)  # Türkiye merkezi
    gmaps = googlemaps.Client(key=GMAPS_API_KEY)
    
    for fac in facilities:
        coords = get_coordinates(fac["address"])
        if coords:
            folium.Marker(
                coords,
                popup=f"{fac['name']} - Hasar: {fac['damage']}",
                icon=folium.Icon(color="red")
            ).add_to(m)
            # Komşuları ekle
            neighbors = find_neighbor_facilities(gmaps, coords[0], coords[1])
            for neigh in neighbors:
                folium.Marker(
                    (neigh["lat"], neigh["lng"]),
                    popup=f"Komşu: {neigh['name']} - {neigh['address']}",
                    icon=folium.Icon(color="blue")
                ).add_to(m)
    
    return m

# Streamlit App
st.title("Sigorta Risk Etki Haritası App")
st.write("Sorgu girin, Grok API ile analiz edin, harita oluşturun.")

query = st.text_area("Sorgu (örneğin: Türkiye'de son 30 günde yangın/deprem etkilenen tesisler)", height=100)
if st.button("Analiz Et ve Harita Oluştur"):
    with st.spinner("Grok API çağrılıyor..."):
        response = call_grok_api(query)
        if response:
            st.subheader("Grok Yanıtı")
            st.write(response)
            
            facilities = parse_grok_response(response)
            if facilities:
                st.subheader("Tespit Edilen Tesisler")
                df = pd.DataFrame(facilities)
                st.table(df)
                
                st.subheader("Etki Haritası (Kırmızı: Etkilenen, Mavi: Komşu Tesisler)")
                impact_map = create_impact_map(facilities)
                if impact_map:
                    folium_static(impact_map)
                else:
                    st.warning("Harita için koordinat bulunamadı.")
            else:
                st.warning("Yanıtta tesis tespit edilemedi.")
