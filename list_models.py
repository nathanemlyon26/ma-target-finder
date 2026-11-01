import groq
import streamlit as st

# Récupération de la clé depuis secrets.toml
api_key = st.secrets["GROQ_API_KEY"]
client = groq.Groq(api_key=api_key)

# Affichage des modèles
print("\n--- MODÈLES DISPONIBLES SUR TON COMPTE GROQ ---")
for m in client.models.list().data:
    print(f"- {m.id}")
print("------------------------------------------------\n")