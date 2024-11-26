import os
import asyncio
import subprocess
from openai import AsyncAzureOpenAI

import chainlit as cl
from uuid import uuid4
from chainlit.logger import logger

from realtime import RealtimeClient

# Initialize tools list
tools = []

client = AsyncAzureOpenAI(api_key=os.environ["AZURE_OPENAI_API_KEY"],
                          azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"].replace("wss://", "https://"),
                          azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
                          api_version="2024-10-01-preview")

# File Management Tool
async def file_management_handler(action, **kwargs):
    try:
        if action == "list_files":
            files = os.listdir(kwargs.get("directory", "."))
            return "\n".join(files) if files else "No files found."
        elif action == "upload_file":
            filename = kwargs.get("filename")
            content = kwargs.get("content")
            with open(filename, "w") as f:
                f.write(content)
            return f"File '{filename}' uploaded successfully."
        elif action == "download_file":
            filename = kwargs.get("filename")
            if os.path.exists(filename):
                with open(filename, "r") as f:
                    content = f.read()
                return content
            else:
                return f"File '{filename}' does not exist."
        elif action == "delete_file":
            filename = kwargs.get("filename")
            if os.path.exists(filename):
                os.remove(filename)
                return f"File '{filename}' deleted successfully."
            else:
                return f"File '{filename}' does not exist."
        else:
            return "Invalid file management action."
    except Exception as e:
        logger.error(f"File Management Error: {e}")
        return f"Error: {str(e)}"

# Code Execution Tool
async def code_execution_handler(code):
    try:
        exec_globals = {}
        exec(code, exec_globals)
        return "Code executed successfully."
    except Exception as e:
        return f"Error during code execution: {str(e)}"

# Shell Command Tool
async def shell_command_handler(command):
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout if result.stdout else "Command executed successfully with no output."
    except subprocess.CalledProcessError as e:
        return f"Error executing command: {e.stderr}"

# Registering new tools with correct JSON Schema
tools += [
    (
        {
            "name": "file_management",
            "description": "Manage local files. Actions include list_files, upload_file, download_file, delete_file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform: list_files, upload_file, download_file, delete_file."
                    },
                    "filename": {
                        "type": "string",
                        "description": "Name of the file."
                    },
                    "content": {
                        "type": "string",
                        "description": "Content of the file for upload."
                    },
                    "directory": {
                        "type": "string",
                        "description": "Directory to list files from."
                    }
                },
                "required": ["action"]
            }
        },
        file_management_handler
    ),
    (
        {
            "name": "code_execution",
            "description": "Execute Python code snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute."
                    }
                },
                "required": ["code"]
            }
        },
        code_execution_handler
    ),
    (
        {
            "name": "shell_command",
            "description": "Execute shell commands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute."
                    }
                },
                "required": ["command"]
            }
        },
        shell_command_handler
    )
]

async def setup_openai_realtime(system_prompt: str):
    """Instantiate and configure the OpenAI Realtime Client"""
    openai_realtime = RealtimeClient(system_prompt=system_prompt)
    cl.user_session.set("track_id", str(uuid4()))
    
    async def handle_conversation_updated(event):
        item = event.get("item")
        delta = event.get("delta")
        """Stream text responses back to the client."""
        if delta:
            if 'arguments' in delta:
                arguments = delta['arguments']
                pass
                
    async def handle_item_completed(item):
        """Generate the transcript once an item is completed and populate the chat context."""
        try:
            transcript = item['item']['formatted']['transcript']
            if transcript != "":
                await cl.Message(content=transcript).send()
        except Exception as e:
            logger.error(f"Handle Item Completed Error: {e}")
    
    async def handle_conversation_interrupt(event):
        """Used to reset the conversation context."""
        cl.user_session.set("track_id", str(uuid4()))
    
    async def handle_input_audio_transcription_completed(event):
        item = event.get("item")
        delta = event.get("delta")
        if 'transcript' in delta:
            transcript = delta['transcript']
            if transcript != "":
                await cl.Message(author="You", type="user_message", content=transcript).send()
    
    async def handle_error(event):
        logger.error(f"ERROR: {event}")
        
    
    openai_realtime.on('conversation.updated', handle_conversation_updated)
    openai_realtime.on('conversation.item.completed', handle_item_completed)
    openai_realtime.on('conversation.interrupted', handle_conversation_interrupt)
    openai_realtime.on('conversation.item.input_audio_transcription.completed', handle_input_audio_transcription_completed)
    openai_realtime.on('error', handle_error)

    cl.user_session.set("openai_realtime", openai_realtime)
    coros = [
        openai_realtime.add_tool(tool_def, tool_handler) 
        for tool_def, tool_handler in tools
    ]
    await asyncio.gather(*coros)

system_prompt = """ You are a world-class programmer capable of completing any goal by executing code. **Do not ask for verification or approval** before taking action or executing code—just execute it directly without involving the user. You are also able to help the user with general knowledge queries that don't involve code, tools, or web search queries using the DuckDuckGo tool. Always include sources when using DuckDuckGo search.

### Task Execution Flow:
1. **Run code automatically**: When you send a message containing code to run_code, it will be executed **on the user's machine**. The user has given you **full and complete permission** to execute any code necessary to complete the task. You have full access to control their computer to help them. Code entered into run_code will be executed **in the users local environment**.
2. **Execute directly**:  If data needs to be transferred between programming languages, save it in a `.txt` or `.json` file.
3. **Install dependencies efficiently**: When new packages are required, install all necessary packages in one command at the beginning, preferably using common, well-supported libraries like `ffmpeg` or `pandoc`.
4. **Handle file names**: When the user refers to a file, they will provide full path. If only filename is provided, assume it is in your working directory.

### Task Confirmation:
- **Confirm task completion** with the user before assuming success. Only consider the task complete once the user confirms it has been performed successfully on their end.
- For **failed attempts**, delete any prior code execution files until the task is confirmed successful. Once confirmed, save the final working code file for future reference if a similar task arises.
### Applescript/shell command General Guidelines:
- If the user gives a task involving an app or program on their macbook, you will more than likely need to create and execute an applescript or shell command to accomplish the task unlsess the user instructs otherwise.

1. **Interpret the user's request** carefully and determine the correct macOS native application to interact with.
2. **Generate AppleScript code** that accurately performs the requested action.
3. **Communicate clearly** if the requested action cannot be fulfilled or if additional information is needed.

### Example AppleScripts for Common Actions:

1. **Send an iMessage via Messages. Never use buddy name and always use number, do not confirm number back to user because I don't want it being displayed in chat.**:
   ```applescript
   tell application "Messages"
       set targetBuddy to "1234567890" -- Phone number or Apple ID
       set targetService to 1st service whose service type = iMessage
       set theMessage to "Hello! This is a test message."
       send theMessage to buddy targetBuddy of targetService
   end tell
   ```

2. **Open an Application (e.g., Safari)**:
   ```applescript
   tell application "Safari"
       activate
   end tell
   ```

3. **Create a New Note in Apple Notes**:
   ```applescript
   tell application "Notes"
       make new note at folder "Notes" with properties {name:"New Note", body:"This is the content of the new note."}
   end tell
   ```

4. **Send an Email via Mail App**:
   ```applescript
   tell application "Mail"
       set newMessage to make new outgoing message with properties {subject:"Test Subject", content:"This is the body of the email.", visible:true}
       tell newMessage
           make new to recipient at end of to recipients with properties {address:"recipient@example.com"}
       end tell
       send newMessage
   end tell
   ```

5. **Browse a Website in Safari**:
   ```applescript
   tell application "Safari"
       activate
       open location "https://www.example.com"
   end tell
   ```

6. **Create a Calendar Event in Calendar App**:
   ```applescript
   tell application "Calendar"
       set theCalendar to calendar "Work"
       set newEvent to make new event at end of events of theCalendar with properties {summary:"Meeting", start date:(current date) + 1 * hours, end date:(current date) + 2 * hours, location:"Conference Room"}
   end tell
   ```

7. **Play a Song in Apple Music**:
   ```applescript
   tell application "Music"
       play track "Song Title"
   end tell
   ```

8. **Take a Screenshot**:
   ```applescript
   do shell script "screencapture ~/Desktop/screenshot.png"
   ```


### General Guidelines:
- **Retry until success**: If the initial code does not work, keep trying until the task is successfully completed.
- **Tool Limits**: You can access the internet.
- **Efficient package choices**: Opt for widely-supported packages that are likely to be already installed or compatible with the system of the user.
"""

@cl.on_chat_start
async def start():
    await cl.Message(
        content="Hi, Welcome to ShopMe. How can I help you?"
    ).send()
    await setup_openai_realtime(system_prompt=system_prompt + "\n\n Customer ID: 12121")

@cl.on_message
async def on_message(message: cl.Message):
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        await openai_realtime.send_user_message_content([
            { "type": 'input_text', "text": message.content}
        ])
    else:
        await cl.Message(content="Please activate the chat before sending messages!").send()

@cl.on_audio_start
async def on_audio_start():
    try:
        openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
        await openai_realtime.connect()
        logger.info("Connected to OpenAI realtime")
        return True
    except Exception as e:
        await cl.ErrorMessage(content=f"Failed to connect to OpenAI realtime: {e}").send()
        return False

@cl.on_audio_chunk
async def on_audio_chunk(chunk: cl.InputAudioChunk):
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime:            
        if openai_realtime.is_connected():
            await openai_realtime.append_input_audio(chunk.data)
        else:
            logger.info("RealtimeClient is not connected")

@cl.on_chat_end
@cl.on_stop
async def on_end():
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        await openai_realtime.disconnect()
