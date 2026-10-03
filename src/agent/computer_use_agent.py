import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, Optional, List, Callable, Awaitable
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from browser_use.browser.browser import BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.browser.views import BrowserState
from browser_use.agent.views import AgentHistoryList, AgentOutput

from src.browser.custom_browser import CustomBrowser
from src.controller.custom_controller import CustomController
from src.agent.browser_use.browser_use_agent import BrowserUseAgent
from src.utils import llm_provider

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class ComputerUseConfig:
    """Configuration for the Computer-Use Agent"""
    # OpenAI Configuration
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    model_name: str = "gpt-4.1"
    temperature: float = 0.7
    
    # Browser Configuration
    headless: bool = False
    window_width: int = 1280
    window_height: int = 1100
    browser_binary_path: Optional[str] = None
    browser_user_data_dir: Optional[str] = None
    use_own_browser: bool = False
    disable_security: bool = False
    cdp_url: Optional[str] = None
    wss_url: Optional[str] = None
    
    # Agent Configuration
    max_steps: int = 100
    max_actions_per_step: int = 10
    max_input_tokens: int = 128000
    use_vision: bool = True
    
    # System Prompt Configuration
    override_system_message: Optional[str] = None
    
    # Output Configuration
    save_recording_path: Optional[str] = None
    save_trace_path: Optional[str] = None
    save_agent_history_path: str = "./tmp/agent_history"
    save_download_path: str = "./tmp/downloads"
    
    # File Upload Configuration
    available_file_paths: Optional[List[str]] = None
    
    def __post_init__(self):
        """Post-initialization to set default values from environment variables"""
        # Set OpenAI API key from environment if not provided
        if self.openai_api_key is None:
            self.openai_api_key = os.getenv("OPENAI_API_KEY")
            if not self.openai_api_key:
                raise ValueError("OPENAI_API_KEY must be provided or set in environment variables")
        
        # Set browser path from environment if not provided
        if self.browser_binary_path is None:
            self.browser_binary_path = os.getenv("BROWSER_PATH")
        
        # Set browser user data from environment if not provided
        if self.browser_user_data_dir is None:
            self.browser_user_data_dir = os.getenv("BROWSER_USER_DATA")
        
        # Set agent configuration from environment if not provided
        if self.max_steps == 100:  # Only override if using default
            env_max_steps = os.getenv("MAX_STEPS")
            if env_max_steps:
                self.max_steps = int(env_max_steps)
        
        if self.max_actions_per_step == 10:  # Only override if using default
            env_max_actions = os.getenv("MAX_ACTIONS_PER_STEP")
            if env_max_actions:
                self.max_actions_per_step = int(env_max_actions)
        
        if not self.headless:  # Only override if using default
            env_headless = os.getenv("HEADLESS")
            if env_headless:
                self.headless = env_headless.lower() in ('true', '1', 'yes')


class ComputerUseAgent:
    """
    A scriptable agent that uses OpenAI's computer-use tool functionality
    to operate on browsers without requiring the web UI.
    """
    
    def __init__(self, config: ComputerUseConfig):
        self.config = config
        self.openai_client = OpenAI(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url or "https://api.openai.com/v1"
        )
        
        # Core components
        self.browser: Optional[CustomBrowser] = None
        self.browser_context: Optional[BrowserContext] = None
        self.controller: Optional[CustomController] = None
        self.agent: Optional[BrowserUseAgent] = None
        
        # State management
        self.task_id: Optional[str] = None
        self.is_running = False
        self.current_task: Optional[asyncio.Task] = None
        self.history_file_path: Optional[str] = None
        
        # Callbacks
        self.step_callback: Optional[Callable[[BrowserState, AgentOutput, int], Awaitable[None]]] = None
        self.done_callback: Optional[Callable[[AgentHistoryList], None]] = None
        
        # Create output directories
        os.makedirs(config.save_agent_history_path, exist_ok=True)
        if config.save_recording_path:
            os.makedirs(config.save_recording_path, exist_ok=True)
        if config.save_trace_path:
            os.makedirs(config.save_trace_path, exist_ok=True)
        if config.save_download_path:
            os.makedirs(config.save_download_path, exist_ok=True)
    
    async def initialize(self):
        """Initialize the browser, context, and controller"""
        logger.info("Initializing Computer-Use Agent...")
        
        # Initialize browser
        extra_args = []
        if self.config.use_own_browser:
            browser_binary_path = os.getenv("BROWSER_PATH", None) or self.config.browser_binary_path
            if browser_binary_path == "":
                browser_binary_path = None
            browser_user_data = self.config.browser_user_data_dir or os.getenv("BROWSER_USER_DATA", None)
            if browser_user_data:
                extra_args += [f"--user-data-dir={browser_user_data}"]
        else:
            browser_binary_path = None

        self.browser = CustomBrowser(
            config=BrowserConfig(
                headless=self.config.headless,
                disable_security=self.config.disable_security,
                browser_binary_path=browser_binary_path,
                extra_browser_args=extra_args,
                wss_url=self.config.wss_url,
                cdp_url=self.config.cdp_url,
                new_context_config=BrowserContextConfig(
                    window_width=self.config.window_width,
                    window_height=self.config.window_height,
                )
            )
        )
        
        # Initialize browser context
        context_config = BrowserContextConfig(
            trace_path=self.config.save_trace_path,
            save_recording_path=self.config.save_recording_path,
            save_downloads_path=self.config.save_download_path,
            window_height=self.config.window_height,
            window_width=self.config.window_width,
        )
        self.browser_context = await self.browser.new_context(config=context_config)
        
        # Initialize controller
        self.controller = CustomController(available_file_paths=self.config.available_file_paths)
        
        logger.info("Computer-Use Agent initialized successfully")
    
    async def run_task(
        self, 
        task: str,
        step_callback: Optional[Callable[[BrowserState, AgentOutput, int], Awaitable[None]]] = None,
        done_callback: Optional[Callable[[AgentHistoryList], None]] = None
    ) -> AgentHistoryList:
        """
        Run a task using the BrowserUseAgent for actual browser interactions
        
        Args:
            task: The task description to execute
            step_callback: Optional callback for each step
            done_callback: Optional callback when task is complete
            
        Returns:
            AgentHistoryList containing the execution history
        """
        if self.is_running:
            raise RuntimeError("Agent is already running a task")
        
        if not self.browser or not self.browser_context:
            await self.initialize()
        
        self.is_running = True
        self.task_id = str(uuid.uuid4())
        self.step_callback = step_callback
        self.done_callback = done_callback
        
        try:
            logger.info(f"Starting task: {task}")
            
            # Create task directory
            task_dir = os.path.join(self.config.save_agent_history_path, self.task_id)
            os.makedirs(task_dir, exist_ok=True)
            
            # Initialize LLM
            llm = llm_provider.get_llm_model(
                provider="openai",
                model_name=self.config.model_name,
                temperature=self.config.temperature,
                api_key=self.config.openai_api_key,
                base_url=self.config.openai_base_url
            )
            
            # Create step callback wrapper
            async def step_callback_wrapper(state: BrowserState, output: AgentOutput, step_num: int):
                if self.step_callback:
                    await self.step_callback(state, output, step_num)
            
            # Create done callback wrapper
            def done_callback_wrapper(history: AgentHistoryList):
                if self.done_callback:
                    self.done_callback(history)
            
            # Create BrowserUseAgent
            self.agent = BrowserUseAgent(
                task=task,
                llm=llm,
                browser=self.browser,
                browser_context=self.browser_context,
                controller=self.controller,
                register_new_step_callback=step_callback_wrapper,
                register_done_callback=done_callback_wrapper,
                use_vision=self.config.use_vision,
                override_system_message=self.config.override_system_message,
                max_input_tokens=self.config.max_input_tokens,
                max_actions_per_step=self.config.max_actions_per_step,
                source="computer_use_agent",
            )
            
            # Set agent ID
            self.agent.state.agent_id = self.task_id
            
            # Run the agent (this actually performs browser interactions!)
            history = await self.agent.run(max_steps=self.config.max_steps)
            
            # Save history to file
            history_file = os.path.join(task_dir, f"{self.task_id}.json")
            self.history_file_path = history_file
            with open(history_file, 'w') as f:
                json.dump(history.model_dump(), f, indent=2)
            logger.info(f"Task completed. History saved to: {history_file}")
            
            return history
            
        except Exception as e:
            logger.error(f"Error during task execution: {e}", exc_info=True)
            raise
        finally:
            self.is_running = False
            self.current_task = None
    
    async def take_screenshot(self, filename: Optional[str] = None) -> Optional[str]:
        """
        Take a screenshot and save it to a file
        
        Args:
            filename: Optional filename for the screenshot. If not provided, 
                     will use timestamp-based name.
        
        Returns:
            Path to the saved screenshot file, or None if failed
        """
        if not self.browser_context:
            logger.warning("Browser context not available")
            return None
        
        try:
            screenshot = await self.browser_context.take_screenshot()
            if not screenshot:
                logger.warning("Screenshot capture returned empty data")
                return None
            
            # Generate filename if not provided
            if not filename:
                import datetime
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.png"
            
            # Ensure screenshot directory exists
            screenshot_dir = os.path.join(self.config.save_agent_history_path, "screenshots")
            
            # If filename contains subdirectories, create the full path
            if "/" in filename:
                full_screenshot_dir = os.path.join(screenshot_dir, os.path.dirname(filename))
                os.makedirs(full_screenshot_dir, exist_ok=True)
                screenshot_path = os.path.join(screenshot_dir, filename)
            else:
                os.makedirs(screenshot_dir, exist_ok=True)
                screenshot_path = os.path.join(screenshot_dir, filename)
            import base64
            screenshot_data = base64.b64decode(screenshot)
            with open(screenshot_path, 'wb') as f:
                f.write(screenshot_data)
            
            logger.info(f"Screenshot saved to: {screenshot_path}")
            return screenshot_path
            
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}", exc_info=True)
            return None
    
    async def stop(self):
        """Stop the current task"""
        if self.agent:
            self.agent.state.stopped = True
        self.is_running = False
    
    async def close(self):
        """Close the agent and clean up resources"""
        logger.info("Closing Computer-Use Agent...")
        
        if self.agent:
            try:
                await self.agent.close()
            except Exception as e:
                logger.warning(f"Error closing agent: {e}")
        
        if self.browser_context:
            try:
                await self.browser_context.close()
            except Exception as e:
                logger.warning(f"Error closing browser context: {e}")
        
        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
        
        logger.info("Computer-Use Agent closed")

    async def get_variable_from_session_storage(self, variable_name):
        """Get a JavaScript variable from the current page"""
        if self.browser_context and self.browser_context.agent_current_page:
            try:
                # Access the variable
                result = await self.browser_context.agent_current_page.evaluate(
                    f"() => sessionStorage.getItem('{variable_name}')"
                )
                return result
            except Exception as e:
                print(f"Error accessing JavaScript variable {variable_name}: {e}")
                return None
        return None

async def run_computer_use_task(
    task: str,
    config: Optional[ComputerUseConfig] = None,
    step_callback: Optional[Callable[[BrowserState, AgentOutput, int], Awaitable[None]]] = None,
    done_callback: Optional[Callable[[AgentHistoryList], None]] = None
) -> AgentHistoryList:
    """
    Convenience function to run a computer-use task
    
    Args:
        task: The task to execute
        config: Optional configuration (will use defaults if not provided)
        step_callback: Optional callback for each step
        done_callback: Optional callback when task is complete
        
    Returns:
        AgentHistoryList containing the execution history
    """
    if config is None:
        config = ComputerUseConfig()
    
    agent = ComputerUseAgent(config)
    
    try:
        return await agent.run_task(task, step_callback, done_callback)
    finally:
        await agent.close()


# Example usage and testing
async def example_usage():
    """Example of how to use the ComputerUseAgent"""
    
    # Configuration - will automatically load from environment variables
    config = ComputerUseConfig(
        headless=False,
        window_width=1280,
        window_height=1100,
        max_steps=50
    )
    
    # Create agent
    agent = ComputerUseAgent(config)
    
    try:
        # Define callbacks for monitoring
        async def step_callback(state: BrowserState, output: AgentOutput, step_num: int):
            print(f"Step {step_num}: {output}")
        
        def done_callback(history: AgentHistoryList):
            print(f"Task completed! Final result: {history.final_result()}")
        
        # Run a task
        task = "Go to Google and search for 'OpenAI computer-use tool'"
        history = await agent.run_task(
            task=task,
            step_callback=step_callback,
            done_callback=done_callback
        )
        
        print("Task execution completed!")
        return history
        
    finally:
        await agent.close()


if __name__ == "__main__":
    # Example usage
    import asyncio
    
    async def main():
        try:
            history = await example_usage()
            print("Example completed successfully!")
        except Exception as e:
            print(f"Example failed: {e}")
    
    asyncio.run(main()) 