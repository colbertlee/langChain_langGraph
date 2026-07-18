from agent import AIAgent

def main():
    print("AI Agent started")
    agent = AIAgent()
    print(f"Tools: {len(agent.get_tools_list())}")
    while True:
        try:
            user_input = input("\nYou: ").strip()
            if user_input.lower() in ["exit", "quit"]:
                print("Goodbye!")
                break
            if not user_input:
                continue
            print("\nAI: ", end="", flush=True)
            for chunk in agent.run_stream(user_input):
                print(chunk, end="", flush=True)
            print()
        except KeyboardInterrupt:
            print("\nInterrupted")
            break

if __name__ == "__main__":
    main()