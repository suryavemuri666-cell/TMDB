import os
import sqlite3
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="TMDB Reel Insights", page_icon="🎬", layout="wide")

DB_PATH = os.path.join("data", "tmdb.db")

if not os.path.exists(DB_PATH):
    st.error("Database not found. Run `01_data_cleaning.py` first to create `data/tmdb.db`.")
    st.stop()

@st.cache_data
def load_data():
    conn = sqlite3.connect(DB_PATH)
    movies = pd.read_sql("SELECT * FROM movies", conn)
    genres = pd.read_sql("SELECT * FROM genres", conn)
    mg     = pd.read_sql("SELECT * FROM movie_genres", conn)
    cast   = pd.read_sql("SELECT * FROM cast", conn)
    conn.close()
    movies["release_date"] = pd.to_datetime(movies["release_date"], errors="coerce")
    movies["release_year"] = movies["release_date"].dt.year
    return movies, genres, mg, cast

movies, genres, mg, cast = load_data()

min_year = int(movies.release_year.min()) if movies.release_year.notna().any() else 1900
max_year = int(movies.release_year.max()) if movies.release_year.notna().any() else 2025

if "filters" not in st.session_state:
    st.session_state.filters = {
        "genres": [],
        "year_range": (min_year, max_year),
        "min_rating": 0.0,
        "language": "All",
    }

def apply_filters():
    f  = st.session_state.filters
    df = movies.copy()
    if f["genres"]:
        gids = genres[genres.genre_name.isin(f["genres"])].genre_id.tolist()
        mids = mg[mg.genre_id.isin(gids)].movie_id.unique()
        df   = df[df.movie_id.isin(mids)]
    df = df[(df.release_year >= f["year_range"][0]) & (df.release_year <= f["year_range"][1])]
    df = df[df.vote_average.fillna(0) >= f["min_rating"]]
    if f["language"] != "All":
        df = df[df.original_language == f["language"]]
    return df

page = st.sidebar.radio("Navigate", ["Filters", "Dashboard", "Query Explorer"])

# ---------------- FILTERS ----------------
if page == "Filters":
    st.title("🎛️ Filters")
    st.caption("Selections persist across all pages (stored in `st.session_state.filters`).")

    genre_options = sorted(genres.genre_name.dropna().unique().tolist())
    lang_options  = ["All"] + sorted(movies.original_language.dropna().unique().tolist())

    f = st.session_state.filters
    sel_genres = st.multiselect("Genres", genre_options, default=f["genres"])
    yr         = st.slider("Release year range", min_year, max_year, f["year_range"])
    rating     = st.slider("Minimum rating", 0.0, 10.0, float(f["min_rating"]), 0.1)
    lang       = st.selectbox("Language", lang_options,
                              index=lang_options.index(f["language"]) if f["language"] in lang_options else 0)

    st.session_state.filters = {"genres": sel_genres, "year_range": yr,
                                "min_rating": rating, "language": lang}

    filtered = apply_filters()
    st.metric("🎬 Movies matching current filters", len(filtered))

# ---------------- DASHBOARD ----------------
elif page == "Dashboard":
    st.title("📊 Dashboard")
    filtered = apply_filters()

    if filtered.empty:
        st.warning("No movies match the current filters. Adjust them on the Filters page.")
        st.stop()

    n_genres  = mg[mg.movie_id.isin(filtered.movie_id)].genre_id.nunique()
    n_actors  = cast[cast.movie_id.isin(filtered.movie_id)].person_id.nunique()
    avg_rating = filtered.vote_average.mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total movies", len(filtered))
    c2.metric("Genres represented", n_genres)
    c3.metric("Actors", n_actors)
    c4.metric("Average rating", f"{avg_rating:.2f}" if pd.notna(avg_rating) else "N/A")

    top_rev = filtered.dropna(subset=["revenue"]).sort_values("revenue", ascending=False).head(10)
    st.subheader("🏆 Top 10 movies by revenue")
    if not top_rev.empty:
        fig = px.bar(top_rev, x="revenue", y="title", orientation="h", color="revenue")
        fig.update_layout(yaxis=dict(autorange="reversed"), height=400, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("🎭 Genre distribution")
    gdist = (mg[mg.movie_id.isin(filtered.movie_id)]
             .merge(genres, on="genre_id")
             .groupby("genre_name").size()
             .sort_values(ascending=False).reset_index(name="count"))
    if not gdist.empty:
        fig = px.pie(gdist, names="genre_name", values="count", hole=0.4)
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("💰 Budget vs Revenue")
    sub = filtered[(filtered.budget > 0) & (filtered.revenue > 0)]
    if not sub.empty:
        fig = px.scatter(sub, x="budget", y="revenue", hover_name="title", opacity=0.6)
        fig.update_layout(height=450)
        st.plotly_chart(fig, use_container_width=True)

    if not gdist.empty:
        top_genre = gdist.iloc[0]["genre_name"]
        avg_rev = (sub.merge(mg, on="movie_id").merge(genres, on="genre_id")
                   .groupby("genre_name").revenue.mean().sort_values(ascending=False))
        best_genre = avg_rev.index[0] if not avg_rev.empty else "N/A"
        best_movie = top_rev.iloc[0]["title"] if not top_rev.empty else "N/A"
        st.info(
            f"**Insight:** In this selection, **{top_genre}** is the most common genre. "
            f"**{best_genre}** has the highest average revenue. "
            f"Top-grossing film: **{best_movie}**."
        )

# ---------------- QUERY EXPLORER ----------------
elif page == "Query Explorer":
    st.title("🔎 Query Explorer")
    st.caption("Every SQL question from `02_sql_analysis.py`, executed live against the DB.")

    QUERIES = {
        "1. Action movies after 2015": """
            SELECT m.title, m.release_date FROM movies m
            JOIN movie_genres mg ON m.movie_id = mg.movie_id
            JOIN genres g ON mg.genre_id = g.genre_id
            WHERE g.genre_name = 'Action' AND m.release_date >= '2016-01-01'
            ORDER BY m.release_date
        """,
        "2. Top 10 highest grossing + genres": """
            SELECT m.title, m.revenue, GROUP_CONCAT(g.genre_name, ', ') AS genres
            FROM movies m
            LEFT JOIN movie_genres mg ON m.movie_id = mg.movie_id
            LEFT JOIN genres g ON mg.genre_id = g.genre_id
            GROUP BY m.movie_id, m.title, m.revenue
            ORDER BY m.revenue DESC LIMIT 10
        """,
        "3. Avg budget & revenue by genre": """
            SELECT g.genre_name, AVG(m.budget) AS avg_budget, AVG(m.revenue) AS avg_revenue
            FROM movies m
            JOIN movie_genres mg ON m.movie_id = mg.movie_id
            JOIN genres g ON mg.genre_id = g.genre_id
            GROUP BY g.genre_name
            ORDER BY avg_revenue DESC
        """,
        "4. Top 10 actors by movie count": """
            SELECT actor_name, COUNT(DISTINCT movie_id) AS movie_count
            FROM cast GROUP BY actor_name
            ORDER BY movie_count DESC LIMIT 10
        """,
        "5. Directors with > 3 movies": """
            SELECT person_name, COUNT(DISTINCT movie_id) AS movie_count
            FROM crew WHERE job = 'Director'
            GROUP BY person_name HAVING COUNT(DISTINCT movie_id) > 3
            ORDER BY movie_count DESC
        """,
        "6. Top 10 keywords": """
            SELECT keyword_id, COUNT(*) AS usage_count
            FROM movie_keywords GROUP BY keyword_id
            ORDER BY usage_count DESC LIMIT 10
        """,
        "7. High budget / low revenue": """
            SELECT m.title, m.budget, m.revenue FROM movies m
            WHERE m.budget > (SELECT AVG(budget) FROM movies)
              AND m.revenue < (SELECT AVG(revenue) FROM movies)
            ORDER BY m.budget DESC
        """,
        "8. Actors in Christopher Nolan films": """
            SELECT DISTINCT c.actor_name
            FROM cast c JOIN crew cr ON c.movie_id = cr.movie_id
            WHERE cr.person_name = 'Christopher Nolan' AND cr.job = 'Director'
            ORDER BY c.actor_name
        """,
        "9. Genre with highest avg rating (≥20 movies)": """
            SELECT g.genre_name, AVG(m.vote_average) AS avg_rating, COUNT(*) AS movies
            FROM movies m
            JOIN movie_genres mg ON m.movie_id = mg.movie_id
            JOIN genres g ON mg.genre_id = g.genre_id
            GROUP BY g.genre_name
            HAVING COUNT(*) >= 20
            ORDER BY avg_rating DESC LIMIT 1
        """,
        "10. Top 10 movies by keyword count": """
            SELECT m.title, COUNT(mk.keyword_id) AS keyword_count
            FROM movies m JOIN movie_keywords mk ON m.movie_id = mk.movie_id
            GROUP BY m.movie_id, m.title
            ORDER BY keyword_count DESC LIMIT 10
        """,
    }

    choice = st.selectbox("Choose a query", list(QUERIES.keys()))
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(QUERIES[choice], conn)
    conn.close()

    st.dataframe(df, use_container_width=True)

    num_cols = df.select_dtypes(include=np.number).columns.tolist()
    cat_cols = df.select_dtypes(exclude=np.number).columns.tolist()
    if num_cols and cat_cols:
        st.plotly_chart(px.bar(df, x=cat_cols[0], y=num_cols[0], title=choice),
                        use_container_width=True)
    elif num_cols:
        st.plotly_chart(px.bar(df, y=num_cols[0], title=choice),
                        use_container_width=True)

    st.info("💡 Auto-chart: first text column → x-axis, first numeric column → y-axis. "
            "Use the dataframe above for exact values.")