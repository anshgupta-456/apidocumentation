import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

class AIExplanationService:
    client = Groq(api_key=os.getenv(GROQ_API_KEY))

    @staticmethod
    def explain_drift(endpoint, method, drift_report):
        prompt = f"""
        You are an expert API analyst.
        Analyze the following schema drift report for the 
        Endpoint: {endpoint} 
        Method: {method} 
        Drift Report: {drift_report}
        Provide a JSON response with EXACT keys:
        - Summary
        -cause
        -impact
        -doc_fix
        -code_fix
        -openapi_patch
        -severity
        keep it short, accurate, and actionable.
        """

        response = AIExplanationService.client.chat.completions.create(
            model="mixtral-8x7b-32768",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content
