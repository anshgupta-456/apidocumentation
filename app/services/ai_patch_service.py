import os
import json
from groq import Groq

class AIPatchService:
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    @staticmethod
    def generate_patches(endpoint: str, method:str, drift_json: dict) -> dict:
        prompt = f"""
        You are an expert API developer.
        Given the following schema drift report for the 
        Endpoint: {endpoint} 
        Method: {method} 
        Drift: {json.dumps(drift_json, indent=2)}
        Generate actionable patches to fix the drift in both OpenAPI spec and backend code.
        Provide a JSON response with EXACT keys:
        - openapi_patch: "..."
        - backend_patch: "..."
        Keep it concise, accurate, and directly addressing the drift issues.
        """

        response = AIPatchService.client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }],
            temperature=0.1,
        )
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except:
            return{"openapi_patch": content, "backend_patch":""}