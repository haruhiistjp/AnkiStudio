import os
from google import genai
key=open('/Users/adelina/.config/gcloud/gemini.key').read().strip()
client=genai.Client(api_key=key)
resp=client.models.generate_content(model='gemini-3.8-flash', contents='Say hello in Swedish and English.')
print(resp.text)
