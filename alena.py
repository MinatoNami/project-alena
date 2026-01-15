import asyncio
from modules.core.controller.agent import run_agent

def main():
    while True:
        try:
            user_input = input("🧠 ALENA > ")
            asyncio.run(run_agent(user_input))
        except KeyboardInterrupt:
            print("\n👋 Bye")
            break

if __name__ == "__main__":
    main()
