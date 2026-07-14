import os
from google import genai
from google.genai import types

client = genai.Client(api_key=os.env.get("GOOGLE_GENAI_API_KEY"))

EXCLUDE_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build'}
ALLOWED_EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.json', '.html', '.css', '.md', '.go', '.rs'}

def build_workspace_context(root_dir="."):
    """Traverses local directories to build an integrated text payload of your codebase."""
    context_blocks = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()  #  Extracts index 1 (the extension string) first
            if ext in ALLOWED_EXTENSIONS:
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, root_dir)
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    context_blocks.append(f"### FILE: {rel_path}\n```\n{content}\n```\n")
                except Exception as e:
                    pass
    return "\n".join(context_blocks)

def interactive_engineer():
    print("🤖 Scanning local files and mapping workspace...")
    workspace_context = build_workspace_context()
    
    system_instruction = (
        "You are an expert Principal Software Engineer. You have full visibility into "
        "the user's local project files. Always reference accurate file paths."
    )
    
    print("✨ System ready! (Type 'exit' or 'quit' to stop)")
    print("-" * 50)
    
    # Starting an explicit chat session to preserve multi-turn history memory
    chat = client.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2
        )
    )
    
    # Inject workspace data transparently into the very first internal message exchange
    first_run = True

    while True:
        user_prompt = input("\n💻 Ask Gemini about your code > ")
        
        if user_prompt.strip().lower() in ['exit', 'quit']:
            print("👋 Session ended.")
            break
            
        if not user_prompt.strip():
            continue
            
        # Bundle the code context explicitly with only the first turn to optimize token traffic
        if first_run:
            payload = f"--- LOCAL WORKSPACE FILES ---\n{workspace_context}\n\n--- TASK ---\n{user_prompt}"
            first_run = False
        else:
            payload = user_prompt
            
        print("🚀 Gemini thinking...\n")
        response_stream = chat.send_message_stream(payload)
        
        for chunk in response_stream:
            print(chunk.text, end="", flush=True)
        print("\n" + "-" * 50)

if __name__ == "__main__":
    interactive_engineer()
