from openai import OpenAI

# Connect to your local llama-server running on port 8000
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"  # llama-server doesn't require a real key
)

def test_connection():
    print("Testing connection to local llama-server (Qwen 35B)...")
    
    response = client.chat.completions.create(
        model="qwen3.6-35b", # Model name string doesn't strictly matter for local llama-server
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Respond with the word 'READY'."}
        ],
        temperature=0.1
    )
    
    print("Model Output:", response.choices[0].message.content)

if __name__ == "__main__":
    test_connection()