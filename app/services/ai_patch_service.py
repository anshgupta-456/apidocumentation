# # # import os
# # # import json
# # # from groq import Groq

# # # class AIPatchService:
# # #     client = Groq(api_key=os.getenv("GROQ_API_KEY"))
# # #     PATCH_FILE: "patches.json"

# # #     @staticmethod
# # #     def generate_patches(endpoint: str, method:str, drift_json: dict) -> dict:
# # #         prompt = f"""
# # #         You are an expert API developer.
# # #         Given the following schema drift report for the 
# # #         Endpoint: {endpoint} 
# # #         Method: {method} 
# # #         Drift: {json.dumps(drift_json, indent=2)}
# # #         Generate actionable patches to fix the drift in both OpenAPI spec and backend code.
# # #         Provide a JSON response with EXACT keys:
# # #         - openapi_patch: "..."
# # #         - backend_patch: "..."
# # #         Keep it concise, accurate, and directly addressing the drift issues.
# # #         """

# # #         response = AIPatchService.client.chat.completions.create(
# # #             model="llama-3.1-8b-instant",
# # #             messages=[
# # #                 {
# # #                     "role": "user",
# # #                     "content": prompt
# # #                 }],
# # #             temperature=0.1,
# # #         )
# # #         content = response.choices[0].message.content
# # #         try:
# # #             return json.loads(content)
# # #         except:
# # #             return{"openapi_patch": content, "backend_patch":""}
# # #     @staticmethod
    
# # #     def save_patch(endpoint, method, patch_dict):
# # #         if os.path.exists(AIPatchService.PATCH_FILE):
# # #             with open(AIPatchService.PATCH_FILE, "r") as f:
# # #                 data = json.load(f)
# # #         else:
# # #             data = {}
# # #         key = f"{endpoint}:{method}"
# # #         data[key] = patch_dict

# # #         with open(AIPatchService.PATCH_FILE, "w") as f:
# # #             json.dump(data, f, indent=2)
# # #     @staticmethod
# # #     def get_saved_patch_for(endpoint, method):
# # #         if not os.path.exists(AIPatchService.PATCH_FILE):
# # #             return None
# # #         with open(AIPatchService.PATCH_FILE, "r") as f:
# # #             data = json.load(f)
# # #         key = f"{endpoint}:{method}"
# # #         return data.get(key)
# # import os
# # import json
# # from groq import Groq


# # class AIPatchService:
# #     # ===== CLASS VARIABLES MUST BE INSIDE CLASS (Indented) =====
# #     client = Groq(api_key=os.getenv("GROQ_API_KEY"))
# #     PATCH_FILE = "patches.json"

# #     @staticmethod
# #     def generate_patches(endpoint: str, method: str, drift_json: dict) -> dict:
# #         """Generate OpenAPI + Backend patches using AI."""

# #         prompt = f"""
# #         You are an expert API engineer.
# #         Given this schema drift:

# #         Endpoint: {endpoint}
# #         Method: {method}

# #         Drift Report:
# #         {json.dumps(drift_json, indent=2)}

# #         Generate a JSON output with EXACT keys:
# #         - openapi_patch
# #         - backend_patch

# #         Ensure the JSON is valid and machine-parseable.
# #         """

# #         response = AIPatchService.client.chat.completions.create(
# #             model="llama-3.1-8b-instant",
# #             messages=[{"role": "user", "content": prompt}],
# #             temperature=0.1,
# #         )

# #         content = response.choices[0].message.content.strip()

# #         # Try parsing as JSON
# #         try:
# #             return json.loads(content)
# #         except Exception:
# #             return {
# #                 "openapi_patch": content,
# #                 "backend_patch": ""
# #             }

# #     @staticmethod
# #     def save_patch(endpoint: str, method: str, patch_dict: dict):
# #         """Save generated patches to patches.json"""

# #         if os.path.exists(AIPatchService.PATCH_FILE):
# #             with open(AIPatchService.PATCH_FILE, "r") as f:
# #                 data = json.load(f)
# #         else:
# #             data = {}

# #         key = f"{endpoint}:{method}"
# #         data[key] = patch_dict

# #         with open(AIPatchService.PATCH_FILE, "w") as f:
# #             json.dump(data, f, indent=2)

# #     @staticmethod
# #     def get_saved_patch_for(endpoint: str, method: str):
# #         """Retrieve saved patch for given endpoint & method"""

# #         if not os.path.exists(AIPatchService.PATCH_FILE):
# #             return None

# #         with open(AIPatchService.PATCH_FILE, "r") as f:
# #             data = json.load(f)

# #         key = f"{endpoint}:{method}"
# #         return data.get(key)

# import os
# import json
# from groq import Groq


# class AIPatchService:
#     client = Groq(api_key=os.getenv("GROQ_API_KEY"))
#     PATCH_FILE = "patches.json"       # <-- FIXED


#     @staticmethod
#     def generate_patches(endpoint: str, method: str, drift_json: dict) -> dict:
#         prompt = f"""
#         You are an expert API developer.
#         Given the following schema drift report:
#         Endpoint: {endpoint}
#         Method: {method}
#         Drift: {json.dumps(drift_json, indent=2)}

#         Generate actionable patches to fix the drift in:
#         - OpenAPI spec
#         - Backend code

#         Return ONLY valid JSON:
#         {{
#             "openapi_patch": "...",
#             "backend_patch": "..."
#         }}
#         """

#         response = AIPatchService.client.chat.completions.create(
#             model="llama-3.1-8b-instant",
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0.1,
#         )

#         content = response.choices[0].message.content

#         try:
#             return json.loads(content)
#         except:
#             return {"openapi_patch": content, "backend_patch": ""}


#     @staticmethod
#     def save_patch(endpoint, method, patch_dict):
#         if os.path.exists(AIPatchService.PATCH_FILE):
#             with open(AIPatchService.PATCH_FILE, "r") as f:
#                 data = json.load(f)
#         else:
#             data = {}

#         key = f"{endpoint}:{method}"
#         data[key] = patch_dict

#         with open(AIPatchService.PATCH_FILE, "w") as f:
#             json.dump(data, f, indent=2)


#     @staticmethod
#     def get_saved_patch_for(endpoint, method):
#         if not os.path.exists(AIPatchService.PATCH_FILE):
#             return None

#         with open(AIPatchService.PATCH_FILE, "r") as f:
#             data = json.load(f)

#         key = f"{endpoint}:{method}"
#         return data.get(key)
import os
import json
from groq import Groq

class AIPatchService:
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    PATCH_FILE = "patches.json"

    @staticmethod
    def generate_patches(endpoint: str, method: str, drift_json: dict) -> dict:
        prompt = f"""
        You are an API expert.
        Fix schema drift.

        Endpoint: {endpoint}
        Method: {method}
        Drift Report:
        {json.dumps(drift_json, indent=2)}

        Return ONLY valid JSON:
        {{
            "openapi_patch": {{ }},
            "backend_patch": "..."
        }}
        """

        response = AIPatchService.client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )

        content = response.choices[0].message.content

        try:
            return json.loads(content)
        except:
            return {"openapi_patch": content, "backend_patch": ""}

    @staticmethod
    def save_patch(endpoint, method, patch_dict):
        if os.path.exists(AIPatchService.PATCH_FILE):
            with open(AIPatchService.PATCH_FILE, "r") as f:
                data = json.load(f)
        else:
            data = {}

        key = f"{endpoint}:{method}"
        data[key] = patch_dict

        with open(AIPatchService.PATCH_FILE, "w") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def get_saved_patch_for(endpoint, method):
        if not os.path.exists(AIPatchService.PATCH_FILE):
            return None

        with open(AIPatchService.PATCH_FILE, "r") as f:
            data = json.load(f)

        key = f"{endpoint}:{method}"
        return data.get(key)