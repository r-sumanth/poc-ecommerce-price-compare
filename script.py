import json
import psycopg2
import requests
from bs4 import BeautifulSoup
import gradio as gr
from datetime import datetime
import os
from dotenv import load_dotenv
from openai import OpenAI
import copy

load_dotenv(override=True)
apiKey = os.getenv('GEMINI_API_KEY')

# Configuration
DB_PARAMS = "dbname=ecommerce_db user=postgres password=password host=localhost port=5433"

gemini_client = OpenAI(api_key=apiKey, base_url='https://generativelanguage.googleapis.com/v1beta/openai/')
ollama_client = OpenAI(api_key='ollama', base_url="http://localhost:11434/v1")

def call_llm(html_text, query):
    response = gemini_client.chat.completions.create(
        model="gemini-2.5-pro", 
        messages=[
            {
                "role": "system", 
                "content": "You are a data extractor. Extract the PRICE for the specific product variant requested. Return ONLY a JSON object: {\"price\": float}. If not found, return {\"price\": 0.0}."
            },
            {
                "role": "user", 
                "content": f"Query: {query}\n\nSearch Results Text: {html_text[:5000]}"
            }
        ],
        response_format={ "type": "json_object" }, # Forces JSON output
        temperature=0
    )
    
    return json.loads(response.choices[0].message.content)

def scrape_site(query, site):
    url = f"https://www.amazon.in/s?k={query}" if site == "Amazon" else f"https://www.flipkart.com/search?q={query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')
    # 1. Clean out the noise immediately
    for junk in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        junk.decompose()

    # 2. Targeted Container for Flipkart/Amazon
    # Flipkart main content is usually in a div with id="container"
    main_container = soup.find(id="container") or soup.find('main') or soup.find('body')

    # 3. Aggressive "Featured/Suggested" removal
    # Flipkart uses specific text for recommendations
    container_copy = copy.copy(main_container)

    noise_keywords = ['featured items', 'recommended', 'related', 'similar products', 'bought together', 'you might be interested']
    for section in container_copy.find_all(['div', 'section']):
        text = section.get_text().lower()
        if any(word in text for word in noise_keywords):
            section.decompose()
    
    if container_copy.get_text(separator=' ')=='':
        container_copy = copy.copy(main_container)
    
    # 4. The "Space-Join" Clean (The solution to your \n problem)
    raw_text = container_copy.get_text(separator=' ')
    
    # This specifically kills literal '\n' strings and collapses all whitespace
    clean_text = " ".join(raw_text.replace('\\n', ' ').replace('\\t', ' ').split())
    product_name = query.replace('+', ' ')
    return call_llm(clean_text, product_name)

def get_best_match(user_query):
    """Checks DB for fuzzy matches using the LLM."""
    conn = psycopg2.connect(DB_PARAMS)
    cur = conn.cursor()
    cur.execute("SELECT product_name FROM price_matrix")
    existing_names = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    if not existing_names:
        return user_query
    
    products_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(existing_names)])
    
    # Ask LLM if the query matches anything existing
    prompt = f"""
                You are a strict product matcher.
                User Query: "{user_query}"
                Existing Products:
                {products_list}

                MATCHING RULES BY CATEGORY:

                Electronics (TVs, Monitors, Laptops):
                - Different screen sizes = DIFFERENT products (43" ≠ 55" ≠ 65")
                - Different storage/RAM = DIFFERENT products (128GB ≠ 256GB, 8GB RAM ≠ 16GB RAM)
                - Examples: "Sony 43 inch TV" ≠ "Sony 55 inch TV"

                Phones/Tablets:
                - Different storage/RAM = DIFFERENT products (iPhone 15 128GB ≠ iPhone 15 256GB)
                - Different colors = SAME product (iPhone 15 Black = iPhone 15 White)

                Clothing/Shoes:
                - Different sizes = DIFFERENT products (Size 8 ≠ Size 10)
                - Different colors = SAME product (Red Shoe = Blue Shoe of same model)

                General Rule:
                - Different MODEL NAMES = DIFFERENT products (Adidas Jauntza ≠ Adidas Supernova)
                - Only COSMETIC differences (color) = SAME product

                Return ONLY JSON: {{"match_index": number_or_0, "reasoning": "brief explanation"}}
            """
            
    response = ollama_client.chat.completions.create(
        model="gemma3:12b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={ "type": "json_object" }
    )
    
    result = json.loads(response.choices[0].message.content)
    match_idx = result.get("match_index", 0)
    
    if match_idx > 0 and match_idx <= len(existing_names):
        return existing_names[match_idx - 1]
    return user_query

def process_workflow(product_name):
    
    product_name = get_best_match(product_name)
    
    conn = psycopg2.connect(DB_PARAMS)
    cur = conn.cursor()
    
    # 1. Check if exists and is fresh (Today)
    cur.execute("""
        SELECT price_amazon, price_flipkart, last_updated 
        FROM price_matrix WHERE product_name = %s
    """, (product_name,))
    record = cur.fetchone()

    if record and record[2].date() == datetime.now().date():
        cur.close()
        conn.close()
        return {"Amazon": record[0], "Flipkart": record[1], "Status": "Fetched from DB (Today)"}

    # 2. Fresh Search (If missing or stale)
    print(f"Fetching fresh data for {product_name}...")
    query = product_name.replace(" ", "+")
    amz_data = scrape_site(query, "Amazon")
    fk_data = scrape_site(query, "Flipkart")

    # 3. Update or Insert
    cur.execute("""
        INSERT INTO price_matrix (product_name, price_amazon, price_flipkart, last_updated)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (product_name) DO UPDATE SET 
            price_amazon = EXCLUDED.price_amazon,
            price_flipkart = EXCLUDED.price_flipkart,
            last_updated = NOW();
    """, (product_name, amz_data['price'], fk_data['price']))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return {
        "Amazon": amz_data['price'], 
        "Flipkart": fk_data['price'], 
        "Status": "Updated via LLM Scrape"
    }

# Gradio UI
def ui_fn(name):
    res = process_workflow(name)
    return [[res['Amazon'], res['Flipkart']]], res['Status']

view = gr.Interface(
    fn=ui_fn,
    inputs=gr.Textbox(label="Product Name & Specs"),
    outputs=[gr.Dataframe(headers=["Price Amazon", "Price Flipkart"]), gr.Textbox(label="Result Source")],
    title="Price Tracker",
    allow_flagging="never"
)

if __name__ == "__main__":
    view.launch()