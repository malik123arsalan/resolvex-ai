import chromadb

client = chromadb.Client()

collection = client.create_collection(name="incidents")

collection.add(
    documents=[
        "Database connection timeout error causing slow queries",
        "Memory leak in application causing server crash",
        "High CPU usage due to inefficient loop in code",
        "Cache file error"
    ],
    ids=["incident_1", "incident_2", "incident_3","incident_4"]
)

results = collection.query(
    query_texts=["Small files are corrupted"],
    n_results=1
)

print(results)