import os
from dotenv import load_dotenv
from groq import Groq
import chromadb

load_dotenv()

# Setup Groq client
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Setup ChromaDB client and collection
chroma_client = chromadb.Client()
collection = chroma_client.create_collection(name="incidents")

# Add sample past incidents to the collection
collection.add(
    documents=[
        "Database connection timeout error causing slow queries",
        "Memory leak in application causing server crash",
        "High CPU usage due to inefficient loop in code",
        "Cache file error"
    ],
    ids=["incident_1", "incident_2", "incident_3", "incident_4"]
)

# Step 1: Retrieval:- Retrieve the most similar past incident
retrieved = collection.query(
    query_texts=["Server response time increased to 3000ms"],
    n_results=1
)

past_incident = retrieved['documents'][0][0]

# Step 2: Augmented:- Combine the retrieved context with the new question
combined_prompt = f"""
Here is a similar past incident: {past_incident}

New incident: Server response time increased to 3000ms.

Based on the past incident, what is the likely root cause?
"""

# Step 3: Generation:- Send the combined prompt to the LLM
response = groq_client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[
        {"role": "system", "content": "You are an expert DevOps engineer."},
        {"role": "user", "content": combined_prompt}
    ]
)

print(response.choices[0].message.content)