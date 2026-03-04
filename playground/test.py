from google import genai

# The client gets the API key from the environment variable `GEMINI_API_KEY`.
client = genai.Client()

response = client.models.generate_content(
    model="from google import genai

# The client gets the API key from the environment variable `GEMINI_API_KEY`.
client = genai.Client()

response = client.models.generate_content(
    model="gemma-3-4b-it", contents="Give me a summary of the latest news."
)
print(response.text)
", contents="Give me a summary of the latest news."
)
print(response.text)
