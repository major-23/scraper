#!/usr/bin/env python3
"""
Simple browser-use agent script for the scraper project.

This uses the browser-use module to run a simple task: open a web page using
natural language input.

To run this script, paste `python scraper-browser-use.py` in the terminal.
"""

import asyncio
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Add the src directory to the path
sys.path.append(str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
from src.agent.computer_use_agent import ComputerUseAgent, ComputerUseConfig

# Load environment variables from .env file
load_dotenv()


async def run_browser_task(**kwargs):
    """Run a natural language browser task using the ComputerUseAgent"""

    print("Starting browser-use agent")
    print("=" * 60)

    files_path = kwargs.get("files_path", [])

    # Configuration
    config = ComputerUseConfig(
        headless=False,  # Keep browser visible to see what's happening
        window_width=1280,
        window_height=1100,
        max_steps=50,
        save_agent_history_path="./tmp/browser_use_task",
        available_file_paths=files_path,
    )

    # Create agent
    if not kwargs.get("agent"):
        agent = ComputerUseAgent(config)
        print("Initializing agent...")
        await agent.initialize()
    else:
        agent = kwargs.get("agent")
        print("Agent initialized")

    try:

        if agent.browser_context:
            print("Browser context initialized successfully")

            # Run the natural language task
            print("Running browser task...")
            tasks = kwargs.get("tasks")
            task = "/n/n".join(tasks)

            # Define a step callback to monitor progress
            async def step_callback(state, output, step_num):
                try:
                    url = getattr(state, 'url', None)
                    if url:
                        print(f"Step {step_num}: current URL: {url}")
                    else:
                        print(f"Step {step_num} completed")
                except Exception as e:
                    print(f"Step {step_num}: Error in callback - {e}")

            # Define a done callback
            def done_callback(history):
                try:
                    print(f"Task completed! Final result: {history.final_result()}")
                except Exception as e:
                    print(f"Task completed! Error getting result - {e}")

            # Run the task
            history = await agent.run_task(task, step_callback, done_callback)

            print(f"Task completed with {len(history.history)} history entries")

            # Take a screenshot after the task
            print("Taking final screenshot...")
            screenshot_path = await agent.take_screenshot("final_screenshot.png")

            if screenshot_path:
                print(f"Final screenshot saved to: {screenshot_path}")
                if os.path.exists(screenshot_path):
                    file_size = os.path.getsize(screenshot_path)
                    print(f"File size: {file_size} bytes")
            else:
                print("Failed to take final screenshot")

            return agent, history, screenshot_path
        else:
            print("Browser context not available")
            return None, None, None

    except Exception as e:
        print(f"Task failed: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None

    finally:
        print('Task completed')


async def main():
    """Main function - open a web page using natural language input"""

    # Check if OpenAI API key is set
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Warning: OPENAI_API_KEY environment variable not set!")
        print("   Set it in your .env file or environment:")
        print("   OPENAI_API_KEY=your-api-key-here")
        print("   The task will fail.\n")
        return

    agent = None

    # Natural language instructions for the task
    url = "https://www.scrapethissite.com/pages/forms/"
    instructions = [
        f"Open the web page {url}.",
        "Wait for the page to load completely.",
        "Exit the task. Do not click on any other button/perform any action.",
    ]

    agent, _, _ = await run_browser_task(tasks=instructions, agent=agent)

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    if agent:
        await agent.close()

    print("Task completed!")


if __name__ == "__main__":
    # Run the task
    asyncio.run(main())
