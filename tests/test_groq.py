import os
from dotenv import load_dotenv
from groq import Groq
import json
from pydantic import BaseModel

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

#Pydantic Validation
class RootCauseAnalysis(BaseModel):
    root_cause: str
    confidence: float
    explanation: str

response = client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[
        {"role": "system", "content": "You are an expert DevOps engineer. Always respond in valid JSON format with keys: root_cause, confidence, explanation."},
        {"role": "user", "content": "The server response time increased from 200ms to 3000ms in the last 10 minutes. What is the likely root cause?"}
    ],
    response_format={"type": "json_object"}
)

#Convert into dictionary from LLM response
raw_data = json.loads(response.choices[0].message.content)

#Validate this dictionary from pydantic model
validated_result = RootCauseAnalysis(**raw_data)

print(validated_result.root_cause)
print(validated_result.confidence)
print(validated_result.explanation)