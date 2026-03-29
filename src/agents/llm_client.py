"""
llm_client.py
Encapsulates OpenAI API interaction with the DeepSeek backend.
"""
import os
import json
import re
from openai import OpenAI

# The API key provided by the user for testing
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-c4b0df80744b4f2899479959b645bdf0")

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

def query_llm(system_prompt: str, user_prompt: str) -> dict:
    """
    Sends a prompt to DeepSeek and parses the JSON response.
    """
    print(f"[LLM Client] Sending query...")
    try:
        completion = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt + "\nYou must respond natively in valid JSON format."},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}
        )
        res_text = completion.choices[0].message.content
        
        # Sometime LLMs output markdown json blocks even with json_object format
        match = re.search(r'```json\s*(.*?)\s*```', res_text, re.DOTALL)
        if match:
            res_text = match.group(1)
            
        return json.loads(res_text)
    except Exception as e:
        print(f"[LLM Client] Error querying or parsing JSON: {e}")
        return {}
