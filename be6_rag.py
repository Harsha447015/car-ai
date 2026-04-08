import fitz  # PyMuPDF
import chromadb
from chromadb.utils import embedding_functions
import requests
import os

# ── Settings ──────────────────────────────────────────────────────
PDF_PATH = r"C:\car_ai\Vehicle Manual_BE6_compressed.pdf"
DB_PATH = r"C:\car_ai\be6_database"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3:8b"

SYSTEM_PROMPT = """You are an intelligent assistant for the Mahindra BE6 electric vehicle.
You have access to the official BE6 vehicle manual.
Answer questions accurately using the manual information provided.
If the information is not in the manual, say so honestly.
Keep answers clear and concise."""

# ── Step 1: Read PDF and split into chunks ─────────────────────────
def read_pdf(pdf_path):
    print("📖 Reading BE6 manual...")
    doc = fitz.open(pdf_path)
    chunks = []
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()
        
        # Only keep pages with actual content
        if len(text.strip()) > 100:
            chunks.append({
                "text": text,
                "page": page_num + 1
            })
    
    print(f"✅ Read {len(chunks)} pages with content")
    return chunks

# ── Step 2: Store chunks in ChromaDB ──────────────────────────────
def build_database(chunks):
    print("🗄️  Building searchable database...")
    
    # Use a simple embedding function
    embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    
    client = chromadb.PersistentClient(path=DB_PATH)
    
    # Delete existing collection if it exists
    try:
        client.delete_collection("be6_manual")
    except:
        pass
    
    collection = client.create_collection(
        name="be6_manual",
        embedding_function=embedding_fn
    )
    
    # Add chunks to database
    texts = [c["text"] for c in chunks]
    ids = [f"page_{c['page']}" for c in chunks]
    metadatas = [{"page": c["page"]} for c in chunks]
    
    collection.add(
        documents=texts,
        ids=ids,
        metadatas=metadatas
    )
    
    print(f"✅ Database built with {len(chunks)} pages")
    return collection

# ── Step 3: Search database for relevant content ───────────────────
def search_manual(collection, question, n_results=3):
    results = collection.query(
        query_texts=[question],
        n_results=n_results
    )
    
    relevant_text = ""
    pages_used = []
    
    for i, doc in enumerate(results["documents"][0]):
        page = results["metadatas"][0][i]["page"]
        pages_used.append(page)
        relevant_text += f"\n[Page {page}]\n{doc}\n"
    
    return relevant_text, pages_used

# ── Step 4: Ask LLM with manual context ───────────────────────────
def ask_with_context(question, context):
    prompt = f"""Based on the following sections from the Mahindra BE6 manual, answer this question:

Question: {question}

Relevant manual sections:
{context}

Answer:"""

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "system": SYSTEM_PROMPT,
        "stream": False
    }
    
    response = requests.post(OLLAMA_URL, json=payload, timeout=120)
    
    if response.status_code == 200:
        return response.json()["response"].strip()
    else:
        return "Could not get response from AI."

# ── Main ───────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("   Mahindra BE6 — AI Manual Assistant")
    print("=" * 55)
    
    # Check if database already exists
    if os.path.exists(DB_PATH):
        print("📂 Loading existing database...")
        embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        client = chromadb.PersistentClient(path=DB_PATH)
        collection = client.get_collection(
            name="be6_manual",
            embedding_function=embedding_fn
        )
        print("✅ Database loaded!")
    else:
        # First time — build the database
        chunks = read_pdf(PDF_PATH)
        collection = build_database(chunks)
    
    print("\nYou can now ask anything about your BE6!")
    print("Examples:")
    print("  - What is the maximum charging speed?")
    print("  - How do I turn off the sunroof?")
    print("  - What does the ADAS system do?")
    print("  - How many airbags does the BE6 have?")
    print("\nType 'quit' to exit\n")
    
    while True:
        question = input("❓ Your question: ").strip()
        
        if question.lower() == 'quit':
            break
            
        if not question:
            continue
        
        print("🔍 Searching manual...")
        context, pages = search_manual(collection, question)
        print(f"📄 Found relevant info on pages: {pages}")
        
        print("🧠 Thinking...")
        answer = ask_with_context(question, context)
        
        print(f"\n💡 Answer:\n{answer}\n")
        print("-" * 55)

if __name__ == "__main__":
    main()