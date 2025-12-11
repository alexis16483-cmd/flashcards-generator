import html
import io
import re

import pdfplumber
import streamlit as st
import yake

CONCEPT_QUESTION_TEMPLATES = [
    "À partir de ce passage « {snippet} », explique pourquoi « {keyword} » est un pivot de l'argumentation.",
    "Comment, selon le document, « {keyword} » fonctionne-t-il concrètement dans cet extrait : « {snippet} » ?",
    "Quelles conséquences majeures du concept « {keyword} » sont mises en évidence ici : « {snippet} » ?",
    "Quel problème « {keyword} » cherche-t-il à résoudre dans le passage suivant : « {snippet} » ?",
    "Quels éléments ou étapes composent « {keyword} » dans ce segment : « {snippet} », et comment interagissent-ils ?",
    "En quoi l'extrait « {snippet} » modifie ou nuance-t-il la compréhension habituelle de « {keyword} » ?",
    "Quels exemples précis illustrent « {keyword} » dans ce passage : « {snippet} » ?",
]

PASSAGE_QUESTION_TEMPLATES = [
    "Quelle idée principale retiens-tu du passage suivant : « {snippet} » ?",
    "Quelles hypothèses implicites semblent guider l'auteur lorsqu'il affirme : « {snippet} » ?",
    "Comment appliquerais-tu ce passage (« {snippet} ») à une situation réelle ou à un cas d'étude ?",
    "Quel lien fais-tu entre « {snippet} » et une notion plus large vue dans le cours ?",
    "Pourquoi l'auteur insiste-t-il sur ce raisonnement : « {snippet} » et quelles en sont les limites ?",
]

SENTENCE_QUESTION_TEMPLATES = [
    "Quels arguments clés composent l'idée suivante et comment les relier : « {snippet} » ?",
    "Quelles causes et conséquences ressortent de cette affirmation : « {snippet} » ?",
    "Comment reformuler de manière critique cette déclaration : « {snippet} » ?",
    "Quel contre-exemple ou quelle objection pourrait-on opposer à « {snippet} », et comment y répondre ?",
]

# --------------------------------------------------
# Configuration de la page
# --------------------------------------------------
st.set_page_config(
    page_title="Flashcards generator",
    page_icon="🃏",
    layout="centered",
)

# --------------------------------------------------
# State (navigation + face de la carte + flashcards + decks)
# --------------------------------------------------
if "card_index" not in st.session_state:
    st.session_state.card_index = 0

if "show_answer" not in st.session_state:
    st.session_state.show_answer = False

# decks = {nom_deck: [ {question, answer}, ... ]}
if "decks" not in st.session_state:
    st.session_state.decks = {}

if "current_deck" not in st.session_state:
    st.session_state.current_deck = None

if "flashcards" not in st.session_state:
    st.session_state.flashcards = []


def _flip_card():
    st.session_state.show_answer = not st.session_state.show_answer


def _prev_card():
    flashcards = st.session_state.flashcards
    if flashcards:
        n_cards = len(flashcards)
        st.session_state.card_index = (st.session_state.card_index - 1) % n_cards
        st.session_state.show_answer = False


def _next_card():
    flashcards = st.session_state.flashcards
    if flashcards:
        n_cards = len(flashcards)
        st.session_state.card_index = (st.session_state.card_index + 1) % n_cards
        st.session_state.show_answer = False


def _split_sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _summarize_context(text: str, keyword: str | None = None, max_sentences: int = 2):
    sentences = _split_sentences(text)
    if not sentences:
        return text.strip()

    selected = []
    if keyword:
        keyword_lower = keyword.lower()
        selected = [s for s in sentences if keyword_lower in s.lower()]

    if not selected:
        selected = sentences[:max_sentences]

    summary = " ".join(selected[:max_sentences])
    return _truncate_words(summary)

# --------------------------------------------------
# Fonctions utilitaires
# --------------------------------------------------
def extract_text_from_pdf(uploaded_file) -> str:
    """Extrait le texte d'un PDF uploadé."""
    data = uploaded_file.read()
    uploaded_file.seek(0)
    text_parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return "\n".join(text_parts)


def build_flashcards_from_text(text: str, n_cards: int):
    """
    Génère des flashcards qui poussent à une compréhension approfondie :
    - détecte les concepts clés et pose des questions analytiques
    - complète avec des questions critiques sur les passages importants
    - garantit toujours le nombre demandé de cartes
    """
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []

    paragraphs = _split_into_paragraphs(text)
    concepts = _extract_concepts(cleaned, paragraphs, target=n_cards * 3)

    cards = _concept_flashcards(concepts, limit=n_cards)
    if len(cards) < n_cards:
        remaining = n_cards - len(cards)
        cards.extend(_passage_flashcards(paragraphs, remaining))

    if len(cards) < n_cards:
        remaining = n_cards - len(cards)
        cards.extend(_sentence_flashcards(cleaned, remaining))

    return cards[:n_cards]


def _split_into_paragraphs(text: str):
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if len(p.strip()) > 0]
    if not paragraphs:
        paragraphs = [text.strip()]
    return paragraphs


def _extract_concepts(cleaned_text: str, paragraphs, target: int):
    """Retourne une liste de concepts avec leur paragraphe associé."""
    try:
        extractor = yake.KeywordExtractor(lan="fr", n=3, top=max(20, target))
        keywords = extractor.extract_keywords(cleaned_text)
    except Exception:
        keywords = []

    concepts = []
    for keyword, score in keywords:
        keyword = keyword.strip()
        if not keyword:
            continue
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        paragraph = next((p for p in paragraphs if pattern.search(p)), "")
        context = paragraph if paragraph else cleaned_text
        concepts.append({"keyword": keyword, "score": score, "context": context})
    return concepts


def _concept_flashcards(concepts, limit: int):
    if limit <= 0:
        return []

    cards = []
    templates = CONCEPT_QUESTION_TEMPLATES * ((limit // len(CONCEPT_QUESTION_TEMPLATES)) + 2)
    template_cycle = iter(templates)

    for concept in sorted(concepts, key=lambda c: c["score"]):
        snippet = _shorten(concept["context"])
        question = next(template_cycle, CONCEPT_QUESTION_TEMPLATES[0]).format(
            keyword=concept["keyword"], snippet=snippet
        )
        answer_text = _summarize_context(concept["context"], keyword=concept["keyword"])
        answer = f"{answer_text}\n\n🔑 Concept clé : {concept['keyword']}"
        cards.append({"question": question, "answer": answer})
        if len(cards) >= limit:
            break

    return cards


def _passage_flashcards(paragraphs, limit: int):
    if limit <= 0:
        return []

    cards = []
    templates = PASSAGE_QUESTION_TEMPLATES * ((limit // len(PASSAGE_QUESTION_TEMPLATES)) + 2)
    template_cycle = iter(templates)

    extended_paragraphs = paragraphs or [""]
    idx = 0
    while len(cards) < limit and idx < len(extended_paragraphs):
        paragraph = extended_paragraphs[idx]
        snippet = _shorten(paragraph, max_len=200)
        template = next(template_cycle, PASSAGE_QUESTION_TEMPLATES[0])
        question = template.format(snippet=snippet)
        cards.append(
            {
                "question": question,
                "answer": _summarize_context(paragraph or snippet),
            }
        )
        idx += 1

    # si on manque de paragraphes, on recycle avec d'autres angles
    idx = 0
    while len(cards) < limit and extended_paragraphs:
        paragraph = extended_paragraphs[idx % len(extended_paragraphs)]
        snippet = _shorten(paragraph, max_len=160)
        template = next(template_cycle, PASSAGE_QUESTION_TEMPLATES[0])
        question = template.format(snippet=snippet)
        cards.append({"question": question, "answer": _summarize_context(paragraph)})
        idx += 1

    return cards


def _sentence_flashcards(cleaned_text: str, limit: int):
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned_text) if len(s.strip()) > 0]
    if not sentences:
        return []

    cards = []
    templates = SENTENCE_QUESTION_TEMPLATES * ((limit // len(SENTENCE_QUESTION_TEMPLATES)) + 2)
    template_cycle = iter(templates)

    idx = 0
    while len(cards) < limit:
        sentence = sentences[idx % len(sentences)]
        snippet = _shorten(sentence, max_len=160)
        template = next(template_cycle, SENTENCE_QUESTION_TEMPLATES[0])
        question = template.format(snippet=snippet)
        cards.append({"question": question, "answer": _summarize_context(sentence)})
        idx += 1

    return cards


def _shorten(text: str, max_len: int = 220):
    trimmed = text.strip()
    if len(trimmed) <= max_len:
        return trimmed
    return trimmed[: max_len - 1].rstrip() + "…"


def _truncate_words(text: str, max_words: int = 75):
    words = text.strip().split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]) + "…"


# --------------------------------------------------
# Style custom (CSS)
# --------------------------------------------------
st.markdown(
    """
    <style>
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
                     system-ui, sans-serif;
    }

    .upload-header {
        background: linear-gradient(90deg, #a855f7, #6366f1);
        border-radius: 18px 18px 0 0;
        padding: 22px 28px;
        color: white;
    }

    .upload-header-title {
        font-size: 22px;
        font-weight: 700;
        margin: 0 0 4px 0;
    }

    .upload-header-subtitle {
        font-size: 14px;
        opacity: 0.9;
        margin: 0;
    }

    .upload-box {
        border: 2px dashed #c7d2fe;
        background: #f5f6ff;
        border-radius: 0 0 18px 18px;
        padding: 26px 24px 28px 24px;
        margin-bottom: 20px;
    }

    .upload-icon-circle {
        width: 60px;
        height: 60px;
        border-radius: 999px;
        background: #e0e7ff;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0 auto 14px auto;
        font-size: 28px;
    }

    .upload-main-text {
        text-align: center;
        font-size: 15px;
        color: #111827;
        margin-bottom: 4px;
        font-weight: 500;
    }

    .upload-secondary-text {
        text-align: center;
        font-size: 13px;
        color: #4b5563;
        margin-bottom: 2px;
    }

    .upload-types-text {
        text-align: center;
        font-size: 11px;
        color: #6b7280;
    }

    div[data-testid="stFileUploader"] {
        text-align: center;
        margin-top: 10px;
    }

    /* --------- Flashcard flip --------- */
    .flashcard-wrapper {
        display: flex;
        justify-content: center;
        margin-top: 30px;
        margin-bottom: 10px;
    }

    .flip-card {
        background-color: transparent;
        width: 420px;
        height: 240px;
        perspective: 1200px;
    }

    .flip-card-inner {
        position: relative;
        width: 100%;
        height: 100%;
        text-align: center;
        transition: transform 0.6s;
        transform-style: preserve-3d;
        border-radius: 26px;
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.25);
    }

    .flip-card.show-answer .flip-card-inner {
        transform: rotateY(180deg);
    }

    .flip-card-front,
    .flip-card-back {
        position: absolute;
        width: 100%;
        height: 100%;
        -webkit-backface-visibility: hidden;
        backface-visibility: hidden;
        border-radius: 26px;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 26px;
        box-sizing: border-box;
    }

    .flip-card-front {
        background: radial-gradient(circle at top left, #ede9fe, #eef2ff);
        color: #111827;
    }

    .flip-card-back {
        background: radial-gradient(circle at top left, #dcfce7, #e0f2fe);
        color: #022c22;
        transform: rotateY(180deg);
    }

    .flashcard-text {
        font-size: 17px;
        line-height: 1.4;
    }

    .flip-helper {
        text-align: center;
        font-size: 12px;
        color: #6b7280;
        margin-top: 6px;
    }

    .index-label {
        text-align: center;
        font-size: 12px;
        color: #4b5563;
        margin-bottom: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------
# UI principale
# --------------------------------------------------
st.title("Flashcards generator")

st.subheader("1. Nom du deck")

deck_name = st.text_input(
    "Nom du deck (ex.: Biologie, Histoire, Math...)",
    value=st.session_state.current_deck or "",
)

if st.button("Valider le deck"):
    if not deck_name.strip():
        st.warning("Tu dois entrer un nom de deck.")
    else:
        st.session_state.current_deck = deck_name
        # si le deck n’existe pas, on le crée
        if deck_name not in st.session_state.decks:
            st.session_state.decks[deck_name] = []
        # charger les cartes du deck
        st.session_state.flashcards = st.session_state.decks[deck_name]
        st.session_state.card_index = 0
        st.session_state.show_answer = False
        st.success(f"Deck « {deck_name} » sélectionné.")


existing_decks = ["(Nouveau deck)"] + list(st.session_state.decks.keys())
default_option = 0
if (
    st.session_state.current_deck
    and st.session_state.current_deck in st.session_state.decks
):
    default_option = existing_decks.index(st.session_state.current_deck)

selected = st.selectbox(
    "Choisis un deck existant ou crée un nouveau deck",
    options=existing_decks,
    index=default_option,
)

new_deck_name = ""
if selected == "(Nouveau deck)":
    new_deck_name = st.text_input(
        "Nom du nouveau deck (ex.: Biologie, Histoire, Math)",
        value="",
        placeholder="Biologie",
    )
    if st.button("Créer ce deck"):
        name = new_deck_name.strip()
        if not name:
            st.warning("Donne un nom à ton deck (ex.: Biologie, Histoire...).")
        else:
            if name not in st.session_state.decks:
                st.session_state.decks[name] = []
            st.session_state.current_deck = name
            st.session_state.flashcards = st.session_state.decks[name]
            st.session_state.card_index = 0
            st.session_state.show_answer = False
            st.success(f"Deck « {name} » prêt. Tu peux maintenant générer des cartes pour ce deck.")
else:
    if selected != st.session_state.current_deck:
        st.session_state.current_deck = selected
        st.session_state.flashcards = st.session_state.decks.get(selected, [])
        st.session_state.card_index = 0
        st.session_state.show_answer = False

current_deck = st.session_state.current_deck

if current_deck:
    st.caption(f"Deck actuel : **{current_deck}**")
else:
    st.info("Choisis ou crée un deck avant de générer des flashcards.")

# ---- Choix du nombre de cartes ----
st.subheader("2. Paramètres de génération")
nombre_cartes = st.selectbox(
    "Nombre de cartes",
    options=[5, 10, 15, 20],
    index=1,  # 10 par défaut
)

# ---- Bloc d’upload ----
st.subheader("3. Importer tes notes")
st.markdown(
    """
    <div class="upload-header">
        <p class="upload-header-title">Télécharger vos documents</p>
        <p class="upload-header-subtitle">
            Téléchargez n'importe quel document : PDF (notes de cours, diapos, etc.).
        </p>
    </div>
    <div class="upload-box">
        <div class="upload-icon-circle">⬆️</div>
        <p class="upload-main-text">
            Téléchargez un ou plusieurs PDF contenant vos notes.
        </p>
        <p class="upload-secondary-text">
            Cliquez pour télécharger ou glissez-déposez
        </p>
        <p class="upload-types-text">
            Pour l'instant, les PDF texte sont supportés (pas encore les scans uniquement images).
        </p>
    """,
    unsafe_allow_html=True,
)

uploaded_files = st.file_uploader(
    "",
    type=["pdf"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

st.markdown("</div>", unsafe_allow_html=True)

if uploaded_files:
    st.success(
        f"{len(uploaded_files)} fichier(s) importé(s). "
        f"Tu as demandé {nombre_cartes} carte(s)."
    )
else:
    st.caption(
        "Téléverse un PDF, choisis un deck (Biologie, Histoire, etc.) "
        "puis clique sur « Générer les flashcards »."
    )

# ---- Bouton pour générer les flashcards à partir des notes ----
st.subheader("4. Générer les flashcards pour ce deck")

if st.button("Générer les flashcards maintenant"):
    if not current_deck:
        st.warning("Choisis ou crée un deck avant de générer des flashcards.")
    elif not uploaded_files:
        st.warning("Téléverse au moins un PDF avec tes notes.")
    else:
        full_text = ""
        for f in uploaded_files:
            try:
                full_text += "\n" + extract_text_from_pdf(f)
            except Exception:
                pass

        cards = build_flashcards_from_text(full_text, nombre_cartes)

        if not cards:
            st.warning(
                "Je n’ai pas réussi à extraire assez de texte pour créer des flashcards. "
                "Vérifie que ton PDF contient du texte (et pas seulement une image scannée)."
            )
        else:
            # Sauvegarder dans le deck correspondant
            st.session_state.decks[current_deck] = cards
            st.session_state.flashcards = cards
            st.session_state.card_index = 0
            st.session_state.show_answer = False
            st.success(
                f"{len(cards)} flashcards générées pour le deck « {current_deck} » ✅"
            )

# --------------------------------------------------
# Affichage des flashcards du deck courant
# --------------------------------------------------
st.subheader("5. Révision des flashcards")

flashcards = st.session_state.flashcards

if not current_deck:
    st.info("Aucun deck sélectionné pour l’instant.")
elif not flashcards:
    st.info(f"Aucune flashcard dans le deck « {current_deck} » pour le moment.")
else:
    n_cards = len(flashcards)
    idx = st.session_state.card_index % n_cards
    current = flashcards[idx]

    card_placeholder = st.empty()
    helper_placeholder = st.empty()

    st.button("Retourner la carte 🔁", on_click=_flip_card)

    col_prev, col_next = st.columns(2)
    with col_prev:
        st.button("⬅️ Carte précédente", on_click=_prev_card)
    with col_next:
        st.button("Carte suivante ➡️", on_click=_next_card)

    question_html = html.escape(current["question"]).replace("\n", "<br>")
    answer_html = html.escape(current["answer"]).replace("\n", "<br>")

    card_placeholder.markdown(
        f"""
        <div class="flashcard-wrapper">
            <div class="flip-card {'show-answer' if st.session_state.show_answer else ''}">
              <div class="flip-card-inner">
                <div class="flip-card-front">
                  <div class="flashcard-text">
                    {question_html}
                  </div>
                </div>
                <div class="flip-card-back">
                  <div class="flashcard-text">
                    {answer_html}
                  </div>
                </div>
              </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    helper_placeholder.markdown(
        '<div class="flip-helper">'
        "Clique sur « Retourner la carte » pour voir la réponse. "
        "La carte se retourne avec une animation."
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div class="index-label">{idx + 1} / {n_cards} — Deck : {current_deck}</div>',
        unsafe_allow_html=True,
    )
