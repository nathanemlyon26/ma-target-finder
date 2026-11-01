from datetime import datetime
import io
import json
import os
import groq
import pandas as pd
import requests
import streamlit as st

# 1. Configuration de la page Streamlit
st.set_page_config(
    page_title="M&A Target Finder",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 M&A Target Finder — Open Data")
st.caption(
    "Détection de cibles d'acquisition via l'API publique de l'État (data.gouv.fr) et Llama 3."
)

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    st.error(
        "Clé API Groq introuvable. Ajoutez `GROQ_API_KEY` dans `.streamlit/secrets.toml`."
    )
    st.stop()

client = groq.Groq(api_key=GROQ_API_KEY)

# 2. Fonction d'interrogation de l'API data.gouv.fr
API_URL = "https://recherche-entreprises.api.gouv.fr/search"


def chercher_cibles_ma(
    ca_min: int = 2000000,
    ca_max: int = 15000000,
    age_min_dirigeant: int = 58,
    departement: str = None,
    max_pages: int = 3,
) -> pd.DataFrame:
    cibles = []
    annee_actuelle = datetime.now().year

    for page in range(1, max_pages + 1):
        params = {
            "ca_min": ca_min,
            "ca_max": ca_max,
            "est_entrepreneur_individuel": False,
            "page": page,
            "per_page": 25,
        }
        if departement:
            params["departement"] = str(departement).zfill(2)

        try:
            res = requests.get(API_URL, params=params, timeout=10)
            if res.status_code != 200:
                break
            data = res.json()
        except Exception:
            break

        resultats = data.get("results", [])
        if not resultats:
            break

        for ent in resultats:
            dirigeants = ent.get("dirigeants", [])
            finances = ent.get("finances", {})

            dirigeant_cible = None
            age_calcule = None

            for d in dirigeants:
                annee_naiss = d.get("annee_de_naissance")
                if annee_naiss:
                    try:
                        age = annee_actuelle - int(annee_naiss)
                        if age >= age_min_dirigeant:
                            dirigeant_cible = d
                            age_calcule = age
                            break
                    except ValueError:
                        continue

            if dirigeant_cible and age_calcule:
                derniere_annee = max(finances.keys()) if finances else None
                donnees_fin = (
                    finances.get(derniere_annee, {})
                    if derniere_annee
                    else {}
                )

                cibles.append({
                    "SIREN": ent.get("siren"),
                    "Entreprise": ent.get("nom_complet"),
                    "Code NAF": ent.get("activite_principale"),
                    "Ville": ent.get("libelle_commune"),
                    "Code Postal": ent.get("code_postal"),
                    "Effectifs": ent.get("tranche_effectif_salarie"),
                    "CA (€)": donnees_fin.get("ca"),
                    "Résultat Net (€)": donnees_fin.get("resultat_net"),
                    "Année Bilan": derniere_annee,
                    "Dirigeant": f"{dirigeant_cible.get('prenoms', '')} {dirigeant_cible.get('nom', '')}".strip(),
                    "Âge Dirigeant": age_calcule,
                    "Qualité": dirigeant_cible.get("qualite"),
                })

    return pd.DataFrame(cibles)


# 3. Définition de l'outil pour Groq (Tool Calling)
TOOLS = [{
    "type": "function",
    "function": {
        "name": "chercher_cibles_ma",
        "description": "Recherche des cibles M&A sur data.gouv.fr selon le Chiffre d'Affaires, l'âge du dirigeant et le département.",
        "parameters": {
            "type": "object",
            "properties": {
                "ca_min": {
                    "type": "integer",
                    "description": "Chiffre d'affaires minimum en euros (ex: 2000000)",
                },
                "ca_max": {
                    "type": "integer",
                    "description": "Chiffre d'affaires maximum en euros (ex: 15000000)",
                },
                "age_min_dirigeant": {
                    "type": "integer",
                    "description": "Âge minimum du dirigeant (ex: 58)",
                },
                "departement": {
                    "type": "string",
                    "description": "Numéro du département sur 2 chiffres (ex: '69', '75', '13')",
                },
            },
            "required": ["ca_min"],
        },
    },
}]

# 4. Interface Chat
if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "system",
        "content": (
            "Vous êtes un assistant spécialisé en Fusions-Acquisitions (M&A). "
            "Lorsque l'utilisateur demande de rechercher des entreprises ou des cibles, "
            "utilisez l'outil `chercher_cibles_ma` pour extraire les données réelles."
        ),
    }]

for msg in st.session_state.messages:
    if msg["role"] != "system":
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

if prompt := st.chat_input(
    "Ex: Trouve des PME dans le 69 avec un CA de +2M€ et un dirigeant > 60 ans"
):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyse des critères et interrogation d'API..."):
            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=st.session_state.messages,
                tools=TOOLS,
                tool_choice="auto",
            )

            response_message = response.choices[0].message

            if response_message.tool_calls:
                tool_call = response_message.tool_calls[0]
                args = json.loads(tool_call.function.arguments)

                df_resultats = chercher_cibles_ma(**args)

                if df_resultats.empty:
                    texte_reponse = "Aucune entreprise ne correspond à ces critères exacts sur les premières pages d'analyse."
                    st.markdown(texte_reponse)
                else:
                    texte_reponse = f"**{len(df_resultats)} cibles qualifiées** identifiées selon vos critères :"
                    st.markdown(texte_reponse)
                    st.dataframe(df_resultats, use_container_width=True)

                    output = io.BytesIO()
                    with pd.ExcelWriter(
                        output, engine="openpyxl"
                    ) as writer:
                        df_resultats.to_excel(
                            writer, index=False, sheet_name="Cibles_MA"
                        )
                    excel_data = output.getvalue()

                    st.download_button(
                        label="📥 Télécharger la sélection au format Excel (.xlsx)",
                        data=excel_data,
                        file_name=f"cibles_ma_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": texte_reponse,
                })

            else:
                texte_reponse = response_message.content
                st.markdown(texte_reponse)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": texte_reponse,
                })