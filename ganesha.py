#!/usr/bin/env python3
# ganesha_crossplatform.py

import argparse
import sys
import os
import json
import subprocess
import platform
import psutil
import shutil
import pkg_resources
import logging
import tempfile
import threading
from datetime import datetime
import openai
import colorama
from colorama import Fore, Style
import time
import shlex
import requests
import zipfile
import re  # Import the re module for regular expressions
from pathlib import Path

# OpenAI API Key (Ensure this environment variable is set or add yours below and uncomment)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
#OPENAI_API_KEY = ""

if not OPENAI_API_KEY:
    print(f"{Fore.RED}Error: OPENAI_API_KEY environment variable is not set.{Style.RESET_ALL}")
    sys.exit(1)


def install_dependencies():
    """Install required dependencies with specific versions if missing."""
    dependencies = {
        "openai": "0.28",
        "colorama": None,  # No specific version
        "psutil": None,
        "requests": None,
        #"pkg_resources": None,
        "pathlib" : None
    }

    installed_packages = {pkg.key: pkg.version for pkg in pkg_resources.working_set}
    missing_packages = []

    # Check for missing or incorrect versions
    for pkg, version in dependencies.items():
        if pkg not in installed_packages or (version and installed_packages[pkg] != version):
            if version:
                missing_packages.append(f"{pkg}=={version}")
            else:
                missing_packages.append(pkg)

    if missing_packages:
        print(f"Missing or outdated packages detected: {missing_packages}")
        print("Installing necessary dependencies...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing_packages])
            print("Dependencies installed successfully.")
        except subprocess.CalledProcessError:
            print("Failed to install dependencies. Please check your internet connection and try again.")
            sys.exit(1)
    else:
        print("All dependencies are installed and up to date.")
def setup_ganesha_command():
    # Install dependencies
    install_dependencies()

    # Detect platform
    current_platform = platform.system()
    python_path = sys.executable
    script_path = Path(__file__).resolve()

    if current_platform == "Windows":
        # 1. Windows batch file setup
        batch_file_content = f"""@echo off
"{python_path}" "{script_path}" %*
"""
        batch_file_path = Path("C:/Windows/ganesha.bat")
        with open(batch_file_path, 'w') as bat_file:
            bat_file.write(batch_file_content)
        print(f"Batch file created at: {batch_file_path}")

        # 2. Add C:/Windows to PATH if not present
        path_dirs = os.environ["PATH"].split(os.pathsep)
        if "C:/Windows" not in path_dirs:
            subprocess.run(f'setx PATH "%PATH%;C:\\Windows"', shell=True)
            print("Added C:\\Windows to PATH successfully.")

    elif current_platform in ["Linux", "Darwin"]:
        # 1. Create a symbolic link for Linux/macOS
        link_path = Path("/usr/local/bin/ganesha")
        if not link_path.exists():
            try:
                link_path.symlink_to(script_path)
                link_path.chmod(0o755)  # Make it executable
                print(f"Symbolic link created at: {link_path}")
            except PermissionError:
                print("Error: Permission denied. Try running the script with sudo.")
                sys.exit(1)
        else:
            print("Symbolic link already exists at /usr/local/bin/ganesha")

    else:
        print("Unsupported platform. Only Windows, Linux, and macOS are supported.")
        sys.exit(1)

    print("Setup complete. You can now run `ganesha` from any terminal.")


# Initialize colorama
colorama.init(autoreset=True)

# ------------------------------ Configuration ------------------------------

# OpenAI Configuration
GPT_MODEL = "gpt-4o-mini"  # Updated to use gpt-4o-mini
MAX_TOKENS = 2000  # Adjust as needed
TEMPERATURE = 0.3
TIMEOUT_SECONDS = 300  # Timeout for long-running commands

# Retry Configuration
MAX_RETRIES = 3
RETRY_DELAY = 5  # Seconds

# Logging Configuration
LOG_DIR_PATH = os.path.expanduser("~/ganesha_logs")

# Known GUI-Based Commands for Different OSes
GUI_COMMANDS = {
    "Linux": ['gnome-terminal', 'firefox', 'xeyes', 'xclock'],
    "Windows": ['notepad.exe', 'calc.exe', 'mspaint.exe', 'explorer.exe', 'virtmgmt.msc', 'control.exe'],
    "Darwin": ['Terminal.app', 'Safari.app', 'TextEdit.app']
}

# Built-in Commands per OS
BUILTIN_COMMANDS = {
    "Windows": ['move', 'copy', 'del', 'dir', 'echo', 'cls', 'cd', 'type', 'mkdir', 'rmdir'],
    "Linux": ['mv', 'cp', 'rm', 'ls', 'echo', 'clear', 'cd', 'cat', 'mkdir', 'rmdir'],
    "Darwin": ['mv', 'cp', 'rm', 'ls', 'echo', 'clear', 'cd', 'cat', 'mkdir', 'rmdir']
}


# Ensure LOG_DIR_PATH exists
os.makedirs(LOG_DIR_PATH, exist_ok=True)

# Set OpenAI API Key
openai.api_key = OPENAI_API_KEY

# ------------------------------ Logger Setup ------------------------------

def setup_logger(run_id, log_file_path):
    import logging
    logger = logging.getLogger(run_id)
    logger.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(message)s')
    file_handler.setFormatter(formatter)
    if not logger.handlers:
        logger.addHandler(file_handler)
    return logging.LoggerAdapter(logger, {'run_id': run_id})

# ------------------------------ Spinner Class ------------------------------

class Spinner:
    """
    A simple spinner to indicate processing.
    """
    spinner_cycle = ['|', '/', '-', '\\']

    def __init__(self, message="Processing"):
        self.spinner = self.spinner_cycle
        self.idx = 0
        self.running = False
        self.thread = None
        self.message = message

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._spin)
        self.thread.start()

    def _spin(self):
        while self.running:
            print(f"\r{self.message}... {self.spinner[self.idx % len(self.spinner)]}", end='', flush=True)
            self.idx += 1
            time.sleep(0.1)

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        print("\r" + " " * (len(self.message) + 5) + "\r", end='', flush=True)

# ------------------------------ Utilities ------------------------------

def gather_system_info():
    """
    Gathers detailed system information, using systeminfo on Windows for enhanced OS data accuracy.
    """
    # Basic info for all OS
    system_info = {
        'OS': platform.system(),
        'OS_Version': platform.version(),
        'Distribution': platform.platform(),
        'Architecture': platform.machine(),
        'Hostname': platform.node(),
        'Python_Version': platform.python_version(),
        'Processor': platform.processor(),
        'RAM_Total_GB': round(psutil.virtual_memory().total / (1024**3), 2),
        'RAM_Used_GB': round(psutil.virtual_memory().used / (1024**3), 2),
        'RAM_Free_GB': round(psutil.virtual_memory().available / (1024**3), 2),
        'Disk_Total_GB': round(shutil.disk_usage('/').total / (1024**3), 2),
        'Disk_Free_GB': round(shutil.disk_usage('/').free / (1024**3), 2)
    }

    # Windows-specific detailed systeminfo parsing
    if platform.system() == "Windows":
        try:
            result = subprocess.run(['systeminfo'], capture_output=True, text=True, shell=True)
            if result.returncode == 0:
                sysinfo_output = result.stdout
                # Extract key fields from systeminfo
                fields = [
                    ("OS Name", "OS_Name"),
                    ("OS Version", "OS_Version"),
                    ("System Manufacturer", "System_Manufacturer"),
                    ("System Model", "System_Model"),
                    ("System Type", "System_Type"),
                    ("BIOS Version", "BIOS_Version"),
                    ("Windows Directory", "Windows_Directory"),
                    ("System Directory", "System_Directory"),
                    ("Boot Device", "Boot_Device"),
                    ("System Locale", "System_Locale"),
                    ("Input Locale", "Input_Locale"),
                    ("Time Zone", "Time_Zone"),
                    ("Total Physical Memory", "Total_Physical_Memory"),
                    ("Available Physical Memory", "Available_Physical_Memory"),
                    ("Virtual Memory: Max Size", "Virtual_Memory_Max_Size"),
                    ("Virtual Memory: Available", "Virtual_Memory_Available"),
                    ("Virtual Memory: In Use", "Virtual_Memory_In_Use"),
                    ("Domain", "Domain"),
                    ("Logon Server", "Logon_Server"),
                    ("Hotfix(s)", "Hotfixes")
                ]
                
                for label, key in fields:
                    match = re.search(rf"{label}:\s+(.*)", sysinfo_output)
                    if match:
                        system_info[key] = match.group(1).strip()

                # Hotfix extraction
                hotfix_matches = re.findall(r"Hotfix\(s\):\s+(.*)", sysinfo_output)
                if hotfix_matches:
                    system_info["Hotfixes"] = hotfix_matches
                else:
                    system_info["Hotfixes"] = ["No hotfixes found"]
        except Exception as e:
            system_info['OS_Name'] = f"Unknown (error: {e})"
            system_info['OS_Version'] = "Unknown"

    return system_info

def get_installed_software():
    """
    Retrieves a list of installed software based on the operating system.

    Returns:
        list: List of installed software names.
    """
    os_type = platform.system()
    installed_software = []
    try:
        if os_type == "Windows":
            uninstall_keys = [
                r"HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
                r"HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
            ]
            for key in uninstall_keys:
                cmd = f"Get-ItemProperty {key} | Where-Object {{ $_.DisplayName }} | Select-Object -ExpandProperty DisplayName"
                result = subprocess.run(
                    ["powershell", "-Command", cmd],
                    capture_output=True,
                    text=True,
                    shell=False
                )
                if result.returncode == 0:
                    software = result.stdout.strip().split('\n')
                    software = [s.strip() for s in software if s.strip()]
                    installed_software.extend(software)
                else:
                    logging.error(f"Error retrieving installed software from {key}: {result.stderr.strip()}")
        elif os_type == "Linux":
            # Example for Debian-based systems
            cmd = "dpkg -l | grep '^ii' | awk '{print $2}'"
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=True
            )
            if result.returncode == 0:
                software = result.stdout.strip().split('\n')
                software = [s.strip() for s in software if s.strip()]
                installed_software.extend(software)
            else:
                logging.error(f"Error retrieving installed software: {result.stderr.strip()}")
        elif os_type == "Darwin":
            # Example for macOS using Homebrew
            cmd = "brew list"
            result = subprocess.run(
                ["brew", "list"],
                capture_output=True,
                text=True,
                shell=False
            )
            if result.returncode == 0:
                software = result.stdout.strip().split('\n')
                software = [s.strip() for s in software if s.strip()]
                installed_software.extend(software)
            else:
                logging.error(f"Error retrieving installed software: {result.stderr.strip()}")
        else:
            installed_software = ["Unsupported OS"]
    except Exception as e:
        installed_software = ["Error retrieving software"]
        logging.error(f"Exception in get_installed_software: {e}")
    return installed_software

def get_installed_modules():
    """
    Retrieves a list of installed Python modules.

    Returns:
        list: List of installed Python modules with their versions.
    """
    installed_packages = sorted(
        ["%s==%s" % (i.key, i.version) for i in pkg_resources.working_set])
    return installed_packages

# ------------------------------ GPT Interface ------------------------------

def extract_json(text):
    """
    Extracts JSON content from a given text.

    Args:
        text (str): Text containing JSON.

    Returns:
        str or None: Extracted JSON string or None if not found.
    """
    try:
        json_start = text.index('{')
        json_end = text.rindex('}') + 1
        json_str = text[json_start:json_end]
        return json_str
    except ValueError:
        return None

def gpt_generate_command(prompt, logger, expect_feedback=False,
                         system_info=None, conversation_history=None, debug=False):
    """
    Sends a prompt to GPT-4o-mini and expects a JSON response containing 'command' or 'commands' and optionally 'feedback'.
    Includes system information and conversation history in the prompt.

    Args:
        prompt (str): The user prompt describing the desired command.
        logger (logging.LoggerAdapter): Logger for logging messages.
        expect_feedback (bool): Whether to expect 'feedback' in the response.
        system_info (dict): System information to include in the hidden prompt.
        conversation_history (list): List of previous conversation messages.
        debug (bool): Flag to indicate if debug information should be printed.

    Returns:
        dict or None: Parsed JSON response from GPT-4o-mini or None if parsing fails.
    """
    try:
        # Construct system prompt with system info
        system_prompt = (
            "You are a cross-platform system expert and data analyst. Your tasks include executing commands, troubleshooting, generating detailed reports, and answering user questions."
            " Provide your responses strictly in JSON format."
            " Do not include any explanations or additional text."
            " If providing multiple commands, use a list under the key 'commands'."
            " Each command should be a dictionary with 'command' and 'explanation' keys."
            " If the task is complete, include a key 'task_complete' with the value true."
            " If generating a report, include a key 'report' with the formatted report content."
            " Use precise and appropriate commands for the user's operating system."
            " Ensure that any dependencies required for the commands are handled appropriately."
            " Here is the system information:\n"
        )
        system_info_json = json.dumps(system_info, indent=2)
        system_prompt += f"```json\n{system_info_json}\n```"

        # Modify the prompt based on whether feedback is expected
        if expect_feedback:
            user_prompt = (
                f"{prompt}\n\n"
                "Please provide a JSON response with 'feedback' explaining the error and 'command' or 'commands' to fix it."
                "\n\nEnsure that all backslashes in your JSON are properly escaped (e.g., use \\n for newlines)."
                "\n\nUse double quotes for strings to comply with JSON standards."
                "\n\nExample for a single command with feedback:\n```json\n{{\n  \"feedback\": \"Explanation of the error.\",\n  \"command\": \"proposed_command\"\n}}\n```"
                "\n\nExample for multiple commands with feedback:\n```json\n{{\n  \"feedback\": \"Explanation of the error.\",\n  \"commands\": [\n    {\"command\": \"first_command\", \"explanation\": \"First command explanation.\"},\n    {\"command\": \"second_command\", \"explanation\": \"Second command explanation.\"}\n  ]\n}}\n```"
            )
        else:
            user_prompt = (
                f"{prompt}\n\n"
                "Please provide a JSON response with the key 'command' or 'commands' containing the command(s) to perform the requested action."
                " If the task is to generate a report, include a key 'report' with the formatted report content."
                " If the task is complete, include a key 'task_complete' with the value true."
                " Ensure that any dependencies required for the commands are handled appropriately."
                "\n\nEnsure that all backslashes in your JSON are properly escaped (e.g., use \\n for newlines)."
                "\n\nUse double quotes for strings to comply with JSON standards."
                "\n\nExample for a single command with explanation:\n```json\n{{\n  \"command\": \"your_command_here\",\n  \"explanation\": \"Description of what this command does.\"\n}}\n```"
                "\n\nExample for multiple commands with explanations:\n```json\n{{\n  \"commands\": [\n    {\"command\": \"first_command\", \"explanation\": \"Description of first command.\"},\n    {\"command\": \"second_command\", \"explanation\": \"Description of second command.\"}\n  ]\n}}\n```"
                "\n\nExample for a report:\n```json\n{{\n  \"report\": \"Your well-formatted report here.\"\n}}\n```"
            )

        # Prepare messages
        messages = [{"role": "system", "content": system_prompt}]

        # Include conversation history if provided
        if conversation_history:
            messages += conversation_history

        # Append user prompt
        messages.append({"role": "user", "content": user_prompt})

        # Start spinner
        spinner = Spinner("GPT-4o-mini is processing")
        spinner.start()

        try:
            # Make the API call
            response = openai.ChatCompletion.create(
                model=GPT_MODEL,
                messages=messages,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE
            )
        except Exception as e:
            spinner.stop()
            logger.error(f"OpenAI API request failed: {e}")
            if debug:
                print(f"{Fore.RED}Error: OpenAI API request failed: {e}{Style.RESET_ALL}")
            return None

        # Stop spinner
        spinner.stop()

        content = response['choices'][0]['message']['content'].strip()
        logger.debug(f"Raw GPT-4o-mini response: {content}")

        # Conditionally print the raw GPT-4o-mini response based on debug flag
        if debug:
            print(f"{Style.BRIGHT}*** Raw GPT-4o-mini Response ***{Style.RESET_ALL}")
            print(f"{Style.BRIGHT}{content}{Style.RESET_ALL}\n")

        # Extract JSON using the extract_json function
        json_str = extract_json(content)

        if not json_str:
            logger.error("No JSON found in GPT-4o-mini response.")
            if debug:
                print(f"{Fore.RED}Error: No JSON found in GPT-4o-mini response.{Style.RESET_ALL}")
                print(f"GPT-4o-mini Response Content:\n{content}\n")
            return None

        # Safely parse the JSON response
        try:
            parsed_json = json.loads(json_str)
            # Validate presence of required keys
            if not (
                    'command' in parsed_json or 'commands' in parsed_json or 'report' in parsed_json or 'feedback' in parsed_json):
                logger.error(
                    "GPT-4o-mini response does not contain 'command', 'commands', 'report', or 'feedback'.")
                if debug:
                    print(f"{Fore.RED}Error: GPT-4o-mini response does not contain 'command', 'commands', 'report', or 'feedback'.{Style.RESET_ALL}")
                return None

            # Ensure explanations are present and handle both dict and string commands
            if 'commands' in parsed_json:
                for idx, cmd in enumerate(parsed_json['commands']):
                    if isinstance(cmd, dict):
                        if 'explanation' not in cmd:
                            parsed_json['commands'][idx]['explanation'] = "No explanation provided."
                    elif isinstance(cmd, str):
                        # Convert string command to dict with default explanation
                        parsed_json['commands'][idx] = {
                            'command': cmd,
                            'explanation': "No explanation provided."
                        }
                    else:
                        logger.warning(f"Unsupported command format: {cmd}")

            logger.debug(f"Parsed JSON response: {parsed_json}")
            return parsed_json

        except json.JSONDecodeError:
            logger.error("Failed to decode JSON from GPT-4o-mini response.")
            if debug:
                print(f"{Fore.RED}Error: Failed to decode JSON from GPT-4o-mini response.{Style.RESET_ALL}")
            return None
    finally:
        pass  # Ensures that finally block is present

# ------------------------------ Additional Functions ------------------------------

def check_dependency(command):
    """
    Checks if the executable required by the command is available in the system PATH or is a built-in command.

    Args:
        command (str): The command string to check.

    Returns:
        tuple: (bool, str) indicating if dependency is found and the name of the missing dependency.
    """
    try:
        tokens = shlex.split(command, posix=(platform.system() != "Windows"))
        if not tokens:
            return False, ""
        executable = tokens[0].lower()

        os_type = platform.system()
        # Check if the command is a built-in command
        if executable in [cmd.lower() for cmd in BUILTIN_COMMANDS.get(os_type, [])]:
            return True, ""
        
        # For Windows, some commands might need to be checked differently
        if os_type == "Windows":
            executable = executable if executable.endswith('.exe') else f"{executable}.exe"

        executable_path = shutil.which(executable)
        if executable_path:
            return True, ""
        else:
            return False, tokens[0]
    except Exception as e:
        return False, ""

def download_file(url, dest_path, logger, debug=False):
    """
    Downloads a file from a URL to the destination path.

    Args:
        url (str): The URL to download the file from.
        dest_path (str): The destination file path.
        logger (logging.LoggerAdapter): Logger for logging messages.
        debug (bool): Flag to indicate if debug information should be printed.

    Returns:
        bool: True if download is successful, False otherwise.
    """
    try:
        response = requests.get(url, stream=True, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"Downloaded file from {url} to {dest_path}")
        if debug:
            print(f"{Fore.GREEN}Downloaded file from {url} to {dest_path}{Style.RESET_ALL}")
        return True
    except Exception as e:
        logger.error(f"Failed to download file from {url}: {e}")
        if debug:
            print(f"{Fore.RED}Failed to download file from {url}: {e}{Style.RESET_ALL}")
        return False

def execute_powershell_script(script, logger, debug=False):
    """
    Executes a PowerShell script.

    Args:
        script (str): The PowerShell script content.
        logger (logging.LoggerAdapter): Logger for logging messages.
        debug (bool): Flag to indicate if debug information should be printed.

    Returns:
        bool: True if execution is successful, False otherwise.
    """
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ps1") as tmp:
            tmp.write(script.encode('utf-8'))
            tmp_path = tmp.name

        cmd = f"powershell.exe -ExecutionPolicy Bypass -File {tmp_path}"
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=True
        )

        os.remove(tmp_path)

        if result.returncode == 0:
            logger.info(f"Executed PowerShell script: {cmd}")
            if debug:
                print(f"{Fore.GREEN}Executed PowerShell script: {cmd}{Style.RESET_ALL}")
            return True
        else:
            logger.error(f"Failed to execute PowerShell script '{cmd}': {result.stderr.strip()}")
            if debug:
                print(f"{Fore.RED}Failed to execute PowerShell script '{cmd}': {result.stderr.strip()}{Style.RESET_ALL}")
            return False
    except Exception as e:
        logger.error(f"Exception during PowerShell script execution '{script}': {e}")
        if debug:
            print(f"{Fore.RED}Exception during PowerShell script execution '{script}': {e}{Style.RESET_ALL}")
        return False
    finally:
        pass  # Ensures that finally block is present

# ------------------------------ GPT Commands Handling -----------------------

def get_inverse_commands(executed_commands, logger, system_info, debug=False):
    """
    Generates a list of inverse commands based on executed commands using GPT-4o-mini.
    """
    inverse_commands = []
    for cmd in reversed(executed_commands):
        inverse_prompt = f"Provide the inverse command for the following executed command on {system_info['OS']}:\n\nCommand: {cmd}"
        parsed_response = gpt_generate_command(
            prompt=inverse_prompt,
            logger=logger,
            expect_feedback=False,
            system_info=system_info,
            debug=debug
        )
        if parsed_response:
            if 'command' in parsed_response:
                inverse_commands.append(parsed_response['command'])
            elif 'commands' in parsed_response and isinstance(parsed_response['commands'], list):
                inverse_commands.extend(parsed_response['commands'])
            else:
                logger.warning(f"No inverse command provided for: {cmd}")
        else:
            logger.warning(f"Failed to get inverse command for: {cmd}")
    return inverse_commands

def rollback_session(session_id, log_dir, logger, debug=False):
    """
    Rolls back the specified session based on the SESSION_ID.
    If SESSION_ID is 'last', rolls back the most recent session.
    """
    # Identify the log file based on session_id
    if session_id == 'last':
        try:
            log_files = sorted([f for f in os.listdir(log_dir) if f.startswith('session_') and f.endswith('.log')])
            if not log_files:
                print(f"{Fore.RED}No log files found for rollback.{Style.RESET_ALL}")
                return
            target_log = log_files[-1]  # Latest session log
            print(f"{Fore.CYAN}Loading the latest session log file: {target_log}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Error accessing log directory: {str(e)}{Style.RESET_ALL}")
            return
    else:
        target_log = f"session_{session_id}.log"
        print(f"{Fore.CYAN}Loading specified session log file: {target_log}{Style.RESET_ALL}")

    # Construct the full path to the log file
    log_path = os.path.join(log_dir, target_log)
    if not os.path.exists(log_path):
        print(f"{Fore.RED}Log file {target_log} does not exist in {log_dir}.{Style.RESET_ALL}")
        return
    print(f"{Fore.GREEN}Log file located at: {log_path}{Style.RESET_ALL}")

    try:
        executed_commands = []
        rollback_commands = []

        # Open and read each line in the log file
        with open(log_path, 'r') as log_file:
            print(f"{Fore.GREEN}Reading lines from log file: {log_path}{Style.RESET_ALL}")
            for line_number, line in enumerate(log_file, start=1):
                line = line.strip()
                
                # Check if line is empty and report
                if not line:
                    print(f"{Fore.YELLOW}Skipping empty line {line_number}{Style.RESET_ALL}")
                    continue  # Ignore empty lines

                print(f"{Fore.YELLOW}Processing line {line_number}: {line}{Style.RESET_ALL}")

                # Try parsing JSON for each line and verify it has the required keys
                try:
                    log_entry = json.loads(line)
                    if 'executed_commands' in log_entry:
                        executed_commands = log_entry['executed_commands']
                        print(f"{Fore.GREEN}Found executed commands: {executed_commands}{Style.RESET_ALL}")
                    if 'rollback_commands' in log_entry:
                        rollback_commands = [cmd['command'] for cmd in log_entry['rollback_commands']]
                        print(f"{Fore.GREEN}Found rollback commands: {rollback_commands}{Style.RESET_ALL}")
                except json.JSONDecodeError as e:
                    print(f"{Fore.RED}Error parsing JSON on line {line_number}: {e}{Style.RESET_ALL}")
                    print(f"Content causing error: {line}")  # Display problematic content
                    continue  # Skip this line if it’s invalid JSON

        # Diagnostic output if no commands are found
        if not executed_commands:
            print(f"{Fore.RED}No executed commands found in the log file; rollback not possible.{Style.RESET_ALL}")
            return

        # If we have valid rollback commands, display them and prompt for execution
        if rollback_commands:
            print(f"{Style.BRIGHT}\nRollback Actions:{Style.RESET_ALL}")
            for cmd in rollback_commands:
                print(f"{Fore.CYAN}Rollback Command: {cmd}{Style.RESET_ALL}")
            execute_input = input("Execute rollback commands? (yes to execute): ").strip().lower()
            if execute_input.startswith("yes"):
                # Assuming `execute_commands` is a function to run commands
                execute_commands(
                    rollback_commands, 
                    explanations=["Rollback action" for _ in rollback_commands],
                    logger=logger,
                    allow_all=True, 
                    quiet_commands=False, 
                    debug=debug
                )
        else:
            print(f"{Fore.YELLOW}No inverse commands found in the log file for rollback.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}Error during rollback: {e}{Style.RESET_ALL}")

def rollback_sessions(session_ids, log_dir, logger, debug=False):
    """
    Rolls back multiple sessions based on the provided session IDs.

    Args:
        session_ids (list): List of session identifiers to rollback.
        log_dir (str): Directory where log files are stored.
        logger (logging.LoggerAdapter or None): Logger for logging messages.
        debug (bool): Flag to indicate if debug information should be printed.

    Returns:
        None
    """
    for session_id in session_ids:
        rollback_session(session_id, log_dir, logger, debug=debug)

import os
import json
from colorama import Fore, Style

def diagnose_rollback(session_id, log_dir):
    """
    Diagnoses the rollback process step-by-step to verify each stage in loading
    and processing the rollback commands for a specified session ID.
    """
    log_file = f"session_{session_id}.log" if session_id != 'last' else None
    if log_file is None:
        log_files = sorted(f for f in os.listdir(log_dir) if f.startswith('session_') and f.endswith('.log'))
        log_file = log_files[-1] if log_files else None
    
    if not log_file:
        print(f"{Fore.RED}No session log file found for rollback.{Style.RESET_ALL}")
        return
    
    log_path = os.path.join(log_dir, log_file)
    print(f"{Fore.GREEN}Using log file for rollback: {log_path}{Style.RESET_ALL}")

    if not os.path.exists(log_path):
        print(f"{Fore.RED}Log file {log_file} does not exist in {log_dir}.{Style.RESET_ALL}")
        return

    try:
        executed_commands = []
        with open(log_path, 'r') as log_file:
            for line_number, line in enumerate(log_file, start=1):
                line = line.strip()
                if not line:
                    print(f"{Fore.YELLOW}Skipping empty line {line_number}{Style.RESET_ALL}")
                    continue
                try:
                    log_entry = json.loads(line)
                    if 'executed_commands' in log_entry:
                        executed_commands = log_entry['executed_commands']
                        print(f"{Fore.GREEN}Found executed commands: {executed_commands}{Style.RESET_ALL}")
                    if 'rollback_commands' in log_entry:
                        print(f"{Fore.GREEN}Rollback commands recorded: {log_entry['rollback_commands']}{Style.RESET_ALL}")
                except json.JSONDecodeError as e:
                    print(f"{Fore.RED}JSON parse error on line {line_number}: {e}{Style.RESET_ALL}")
                    continue
        if not executed_commands:
            print(f"{Fore.RED}No executed commands found in {log_file}; rollback not possible.{Style.RESET_ALL}")
            return

    except Exception as e:
        print(f"{Fore.RED}Failed to read or parse log file {log_path}: {e}{Style.RESET_ALL}")
        return

    inverse_commands = []
    for cmd in reversed(executed_commands):
        inverse_command = f"undo_{cmd}"
        inverse_commands.append(inverse_command)
        print(f"{Fore.CYAN}Generated inverse command: {inverse_command}{Style.RESET_ALL}")

    if inverse_commands:
        print(f"{Fore.CYAN}--- Rollback Actions ---{Style.RESET_ALL}")
        for command in inverse_commands:
            print(f"{Fore.CYAN}Rollback Command: {command}{Style.RESET_ALL}")
        
        execute_input = input("Execute rollback commands? (yes to execute): ").strip().lower()
        if execute_input.startswith("yes"):
            print(f"{Fore.CYAN}Executing rollback commands...{Style.RESET_ALL}")
            for cmd in inverse_commands:
                try:
                    print(f"{Fore.GREEN}Executed: {cmd}{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}Error executing {cmd}: {e}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}No rollback actions were generated from the executed commands.{Style.RESET_ALL}")

def analyze_and_propose_rollback(executed_commands, system_info, debug=False):
    """
    Analyzes executed commands and proposes rollback actions using GPT.

    Args:
        executed_commands (list): List of executed commands.
        system_info (dict): System information.
        debug (bool): Flag to indicate if debug information should be printed.

    Returns:
        str: Rollback report.
    """
    try:
        prompt = (
            "Analyze the following executed commands and provide a detailed report on what actions were performed."
            " Based on this analysis, propose rollback actions to undo these changes."
            " If rolling back is not possible, clearly state so in the report."
            " Ensure that the rollback commands are compatible with a vanilla system without additional dependencies."
            "\n\nExecuted Commands:\n" +
            "\n".join(executed_commands)
        )

        parsed_response = gpt_generate_command(
            prompt=prompt,
            logger=None,  # No logging needed for rollback report
            expect_feedback=False,
            system_info=system_info,
            debug=debug
        )

        if parsed_response and 'report' in parsed_response:
            return parsed_response['report']
        else:
            return "Unable to generate a rollback report based on the executed commands."
    except Exception as e:
        return f"Error generating rollback report: {e}"
    finally:
        pass  # Ensures that finally block is present

# ------------------------------ Command Executor ------------------------

def execute_commands(commands, explanations, logger, allow_all, quiet_commands, debug=False):
    success = True
    error_message = ""
    executed_commands = []  # Collect executed commands

    for i, cmd in enumerate(commands, 1):
        expl = explanations[i-1] if i-1 < len(explanations) else ""
        print(f"{Fore.CYAN}Executing command {i}: {cmd}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}Explanation: {expl}{Style.RESET_ALL}")
        
        try:
            result = subprocess.run(cmd, shell=True, check=True)
            logger.info(f"Executed command: {cmd}")
            executed_commands.append(cmd)  # Append to executed commands list
        except subprocess.CalledProcessError as e:
            print(f"{Fore.RED}Error executing command: {cmd}{Style.RESET_ALL}")
            error_message = str(e)
            success = False
            break

    # Log executed commands if any were run
    if executed_commands:
        try:
            rollback_log = {
                'executed_commands': executed_commands
            }
            log_path = logger.logger.handlers[0].baseFilename
            with open(log_path, 'a') as log_file:
                log_file.write(json.dumps(rollback_log) + '\n')
            if debug:
                print(f"{Fore.GREEN}Successfully logged executed commands for rollback.{Style.RESET_ALL}")
        except Exception as log_error:
            print(f"{Fore.RED}Failed to log executed commands: {log_error}{Style.RESET_ALL}")

    return success, error_message

import os
import json
from colorama import Fore, Style

def rollback_session(session_id, log_dir, logger, debug=False):
    """
    Rolls back the specified session based on the SESSION_ID.
    """
    # If 'last', find the most recent non-empty session log with executed commands
    if session_id == 'last':
        log_files = sorted(
            [f for f in os.listdir(log_dir) if f.startswith('session_') and f.endswith('.log')],
            reverse=True
        )
        target_log = None
        for log_file in log_files:
            log_path = os.path.join(log_dir, log_file)
            if os.path.getsize(log_path) > 0:
                with open(log_path, 'r') as log:
                    for line in log:
                        if '"executed_commands"' in line:
                            target_log = log_file
                            break
            if target_log:
                break
        if not target_log:
            print(f"{Fore.RED}No valid log files with executed commands found for rollback.{Style.RESET_ALL}")
            return
        print(f"{Fore.CYAN}Loading the latest session log file with executed commands: {target_log}{Style.RESET_ALL}")
    else:
        target_log = f"session_{session_id}.log"
        print(f"{Fore.CYAN}Loading specified session log file: {target_log}{Style.RESET_ALL}")

    # Construct the full path to the log file
    log_path = os.path.join(log_dir, target_log)
    if not os.path.exists(log_path):
        print(f"{Fore.RED}Log file {target_log} does not exist in {log_dir}.{Style.RESET_ALL}")
        return

    try:
        executed_commands = []
        rollback_commands = []

        with open(log_path, 'r') as log_file:
            for line_number, line in enumerate(log_file, start=1):
                line = line.strip()
                if not line:
                    continue  # Skip empty lines
                try:
                    log_entry = json.loads(line)
                    if 'executed_commands' in log_entry:
                        executed_commands = log_entry['executed_commands']
                    if 'rollback_commands' in log_entry:
                        rollback_commands = [cmd['command'] for cmd in log_entry['rollback_commands']]
                except json.JSONDecodeError:
                    continue  # Skip any lines that aren't JSON

        if not executed_commands:
            print(f"{Fore.RED}No executed commands found in {target_log}; rollback not possible.{Style.RESET_ALL}")
            return

        if rollback_commands:
            print(f"{Style.BRIGHT}\nRollback Actions:{Style.RESET_ALL}")
            for cmd in rollback_commands:
                print(f"{Fore.CYAN}Rollback Command: {cmd}{Style.RESET_ALL}")
            execute_input = input("Execute rollback commands? (yes to execute): ").strip().lower()
            if execute_input.startswith("yes"):
                execute_commands(
                    rollback_commands, 
                    explanations=["Rollback action" for _ in rollback_commands],
                    logger=logger,
                    allow_all=True, 
                    quiet_commands=False, 
                    debug=debug
                )
        else:
            print(f"{Fore.YELLOW}No rollback commands found in the log file for rollback.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}Error during rollback: {e}{Style.RESET_ALL}")

# ------------------------------ Script Executor ------------------------

def execute_script(script, script_type, allow_all, quiet_commands, logger, debug=False):
    """
    Executes a script with the specified type.

    Args:
        script (str): The script content.
        script_type (str): Type of script ('python', 'bash', 'powershell').
        allow_all (bool): If True, execute without confirmation.
        quiet_commands (bool): If True, suppress script output.
        logger (logging.LoggerAdapter): Logger for logging messages.
        debug (bool): Flag to indicate if debug information should be printed.

    Returns:
        bool: True if script executed successfully, False otherwise.
    """
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{script_type}") as tmp:
            tmp.write(script.encode('utf-8'))
            tmp_path = tmp.name

        if not allow_all:
            print(f"{Fore.CYAN}Proposed Script Content ({script_type}):{Style.RESET_ALL}")
            print(f"{Fore.CYAN}{script}{Style.RESET_ALL}")
            confirm = input("Do you want to execute this script? (yes to execute): ").strip().lower()
            if confirm != "yes":
                print(f"{Fore.YELLOW}Skipping script execution.{Style.RESET_ALL}")
                os.remove(tmp_path)
                return False

        if script_type.lower() == "powershell":
            success = execute_powershell_script(script, logger, debug=debug)
            os.remove(tmp_path)
            return success
        elif script_type.lower() == "bash":
            cmd = f"bash {tmp_path}"
        elif script_type.lower() == "python":
            cmd = f"python {tmp_path}"
        else:
            print(f"{Fore.RED}Unsupported script type: {script_type}{Style.RESET_ALL}")
            logger.error(f"Unsupported script type: {script_type}")
            os.remove(tmp_path)
            return False

        # Determine if the script opens a GUI application
        os_type = platform.system()
        is_gui_command = False
        if script_type.lower() == "bash":
            for gui_cmd in GUI_COMMANDS.get(os_type, []):
                if gui_cmd.lower() in script.lower():
                    is_gui_command = True
                    break

        if is_gui_command:
            subprocess.Popen(cmd, shell=True)
        else:
            if quiet_commands:
                subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                subprocess.run(cmd, shell=True, check=True)
        logger.info(f"Executed script: {cmd}")
        os.remove(tmp_path)
        return True
    except subprocess.CalledProcessError as e:
        print(f"{Fore.RED}Error executing script: {e}{Style.RESET_ALL}")
        logger.error(f"Error executing script '{script}': {e.stderr.strip() if e.stderr else e}")
        os.remove(tmp_path)
        return False
    except Exception as e:
        print(f"{Fore.RED}Unexpected error executing script: {e}{Style.RESET_ALL}")
        logger.error(f"Unexpected error executing script '{script}': {e}")
        os.remove(tmp_path)
        return False
    finally:
        pass  # Ensures that finally block is present

# ------------------------------ Report Generation -----------------------

def generate_readable_report(report_dict):
    """
    Converts a dictionary report into a readable string format.

    Args:
        report_dict (dict): The report data.

    Returns:
        str: Readable report string.
    """
    report_lines = []
    for key, value in report_dict.items():
        if isinstance(value, list):
            value = ', '.join(value)
        report_lines.append(f"{key}: {value}")
    return "\n".join(report_lines)

def generate_report(criteria, logger, debug=False):
    """
    Generates a report based on the specified criteria.

    Args:
        criteria (str): The criteria for the report.
        logger (logging.LoggerAdapter): Logger for logging messages.
        debug (bool): Flag to indicate if debug information should be printed.

    Returns:
        None
    """
    prompt = f"Generate a detailed report based on the following criteria: {criteria}"

    # Generate report using GPT-4o-mini
    parsed_response = gpt_generate_command(
        prompt=prompt,
        logger=logger,
        expect_feedback=False,
        system_info=gather_system_info(),
        debug=debug
    )

    if parsed_response:
        report = ""
        if 'report' in parsed_response:
            report = parsed_response['report']
            # Attempt to parse the report if it's JSON
            if isinstance(report, dict):
                readable_report = generate_readable_report(report)
            else:
                try:
                    report_dict = json.loads(report)
                    readable_report = generate_readable_report(report_dict)
                except json.JSONDecodeError:
                    # If not JSON, use the report as is
                    readable_report = report

            # Display the report in a formatted manner with bold styling
            print(f"{Style.BRIGHT}\n*** Generated Report ***\n{Style.RESET_ALL}")
            print(f"{Style.BRIGHT}{readable_report}{Style.RESET_ALL}")
            print(f"{Style.BRIGHT}\n*** End of Report ***\n{Style.RESET_ALL}")
            # Optionally, log the report
            report_log = {
                'report': report
            }
            with open(logger.logger.handlers[0].baseFilename, 'a') as log_file:
                log_file.write(json.dumps(report_log) + '\n')
        elif 'command' in parsed_response:
            # If GPT-4o-mini returns a command to generate the report
            report_cmd = parsed_response['command']
            success, error = execute_commands(
                [report_cmd],
                ["Command to generate report"],
                logger,
                allow_all=True,
                quiet_commands=False,
                debug=debug
            )
            if success:
                print(f"{Style.BRIGHT}\n*** Generated Report ***\n{Style.RESET_ALL}")
                # Assuming the command outputs the report
                print(f"{Style.BRIGHT}Report generated successfully.{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}Failed to generate the report using the provided command.{Style.RESET_ALL}")
                return
        elif 'commands' in parsed_response:
            # Execute multiple commands to generate the report
            commands = parsed_response['commands']
            total_commands = len(commands)
            print(f"{Style.BRIGHT}\n*** Generated Report Commands ***\n{Style.RESET_ALL}")
            for idx, cmd in enumerate(commands, 1):
                explanation = parsed_response['commands'][idx-1].get('explanation', "No explanation provided.") if isinstance(parsed_response['commands'][idx-1], dict) else "No explanation provided."
                cmd_text = cmd['command'] if isinstance(cmd, dict) else cmd
                print(f"{Fore.CYAN}Command {idx} of {total_commands}: {cmd_text}{Style.RESET_ALL}")
                print(f"{Fore.GREEN}Explanation: {explanation}{Style.RESET_ALL}")
            print()
            success, error = execute_commands(
                [cmd['command'] if isinstance(cmd, dict) else cmd for cmd in commands],
                [cmd['explanation'] if isinstance(cmd, dict) else "No explanation provided." for cmd in commands],
                logger,
                allow_all=True,
                quiet_commands=False,
                debug=debug
            )
            if success:
                print(f"{Style.BRIGHT}\n*** Generated Report ***\n{Style.RESET_ALL}")
                # Assuming the commands output the report
                print(f"{Style.BRIGHT}Report generated successfully.{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}Failed to generate the report using the provided commands.{Style.RESET_ALL}")
                return
        else:
            print(f"{Fore.RED}GPT-4o-mini response did not contain a report or commands to generate one.{Style.RESET_ALL}")
            return
    else:
        print(f"{Fore.RED}Failed to generate the report. Ensure that GPT-4o-mini returns a valid response.{Style.RESET_ALL}")

# ------------------------------ Feedback Handler -----------------------

def handle_feedback(original_prompt, user_feedback, system_info, conversation_history, logger, debug=False):
    """
    Handles user feedback by sending it to GPT-4o-mini to generate adjusted commands.

    Args:
        original_prompt (str): The original user prompt.
        user_feedback (str): The user's feedback.
        system_info (dict): System information to include in the prompt.
        conversation_history (list): Previous conversation messages.
        logger (logging.LoggerAdapter): Logger for logging messages.
        debug (bool): Flag to indicate if debug information should be printed.

    Returns:
        dict or None: Parsed JSON response from GPT-4o-mini or None if parsing fails.
    """
    combined_prompt = f"{original_prompt}\n\n{user_feedback}"
    conversation_history.append({"role": "user", "content": user_feedback})
    return gpt_generate_command(
        prompt=combined_prompt,
        logger=logger,
        expect_feedback=True,  # Now expecting feedback to refine commands
        system_info=system_info,
        conversation_history=conversation_history,
        debug=debug
    )

# ------------------------------ Summary Function ------------------------

def summarize_last_run(log_dir, logger=None):
    """
    Summarizes all activities performed during past runs by reading the log files.
    Allows users to select how far back to go.

    Args:
        log_dir (str): Directory where log files are stored.
        logger (logging.LoggerAdapter or None): Logger for logging messages.

    Returns:
        None
    """
    try:
        log_files = sorted([f for f in os.listdir(
            log_dir) if f.startswith('session_') and f.endswith('.log')])
        if not log_files:
            print(f"{Fore.RED}No log files found.{Style.RESET_ALL}")
            return

        print("\n*** Available Sessions ***\n")
        valid_sessions = []
        for idx, log_file in enumerate(log_files, 1):
            log_path = os.path.join(log_dir, log_file)
            with open(log_path, 'r') as lf:
                start_time = ""
                task = ""
                for line in lf:
                    try:
                        log_entry = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
                    if log_entry.get('action') == 'start':
                        start_time = log_entry.get('start_time', 'N/A')
                        task = log_entry.get('task', 'N/A')
                        break
            # Exclude sessions where task is "N/A" or missing (e.g., summaries or rollbacks)
            if task and task != "N/A":
                valid_sessions.append((idx, log_file, start_time, task))
                print(f"{idx}. Session ID: {log_file.replace('session_', '').replace('.log', '')}")
                print(f"   Start Time: {start_time}")
                # Truncate task description for brevity
                print(f"   Task: {task[:60]}...\n")

        if not valid_sessions:
            print(f"{Fore.YELLOW}No valid sessions with tasks found.{Style.RESET_ALL}")
            return

        selection = input(
            "Enter the session numbers you want to rollback (comma-separated), 'all' to rollback all, or 'C' to cancel: ").strip().lower()
        if selection == 'all':
            for _, log_file, _, _ in reversed(valid_sessions):
                session_id = log_file.replace('session_', '').replace('.log', '')
                rollback_session(session_id, log_dir, logger, debug=False)
        elif selection == 'c':
            print(f"{Fore.CYAN}Rollback canceled.{Style.RESET_ALL}")
            return
        else:
            try:
                session_numbers = [int(num.strip())
                                   for num in selection.split(',')]
                for num in session_numbers:
                    matching_sessions = [
                        s for s in valid_sessions if s[0] == num]
                    if matching_sessions:
                        _, log_file, _, _ = matching_sessions[0]
                        session_id = log_file.replace('session_', '').replace('.log', '')
                        rollback_session(
                            session_id, log_dir, logger, debug=False)
                    else:
                        print(f"{Fore.RED}Invalid session number: {num}{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Invalid input. Please enter valid session numbers, 'all', or 'C' to cancel.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}Error during summarization: {str(e)}{Style.RESET_ALL}")
        if logger:
            logger.error(f"Error during summarization: {str(e)}")
    finally:
        pass  # Ensures that finally block is present

# ------------------------------ Interactive Menu ------------------------

def interactive_menu(debug=False):
    """
    Provides an interactive menu for users to select actions like executing tasks, rolling back sessions, or generating reports.

    Args:
        debug (bool): Flag to indicate if debug information should be printed.

    Returns:
        None
    """
    # Initialize a separate logger for the interactive session
    run_id = f"interactive_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    log_file_path = os.path.join(LOG_DIR_PATH, f"session_interactive_{datetime.now().strftime('%Y%m%d%H%M%S')}.log")
    logger = setup_logger(run_id=run_id, log_file_path=log_file_path)

    while True:
        print("\n*** Ganesha Interactive Menu ***")
        print("1. Execute a Task")
        print("2. Summarize Sessions")
        print("3. Rollback a Session")
        print("4. Generate a Report")
        print("5. Exit")
        choice = input("Enter your choice (1-5): ").strip()

        if choice == '1':
            task = input("Enter the task: ").strip()
            if task:
                original_prompt = task
                system_info = gather_system_info()
                conversation_history = []
                commands = get_initial_commands(original_prompt, logger, debug=debug)
                if commands:
                    while True:
                        # Display all commands as a batch with explanations
                        total_commands = len(commands)
                        print(f"\nYou have {total_commands} command(s) to execute:")
                        for idx, cmd in enumerate(commands, 1):
                            explanation = "No explanation provided."  # Default explanation
                            if isinstance(cmd, dict):
                                cmd_text = cmd.get('command', '')
                                explanation = cmd.get('explanation', "No explanation provided.")
                            else:
                                cmd_text = cmd
                            print(f"{Fore.CYAN}Command {idx} of {total_commands}: {cmd_text}{Style.RESET_ALL}")
                            print(f"{Fore.GREEN}Explanation: {explanation}{Style.RESET_ALL}")
                        print()

                        # Prompt once for batch execution
                        confirm = input(f"Do you want to execute all {total_commands} command(s)? (yes to execute): ").strip().lower()
                        if confirm.startswith("yes"):
                            # Extract command texts
                            command_texts = [cmd['command'] if isinstance(cmd, dict) else cmd for cmd in commands]
                            explanations = [cmd['explanation'] if isinstance(cmd, dict) else "No explanation provided." for cmd in commands]
                            execute_success, error_message = execute_commands(
                                command_texts,
                                explanations,
                                logger,
                                allow_all=True,  # Execute all without individual prompts
                                quiet_commands=False,
                                debug=debug
                            )
                            if execute_success:
                                # Log the executed commands
                                executed_commands = command_texts
                                rollback_commands = get_inverse_commands(executed_commands, logger, system_info, debug=debug)
                                rollback_log = {
                                    'executed_commands': executed_commands,
                                    'rollback_commands': rollback_commands
                                }
                                with open(log_file_path, 'a') as log_file:
                                    log_file.write(json.dumps(rollback_log) + '\n')
                                logger.debug("Rollback commands have been logged.")
                                break
                            else:
                                if error_message:
                                    # Send the error back to GPT for new commands
                                    user_feedback = f"The last command failed with the following error:\n{error_message}\nPlease provide the correct command to {original_prompt}."
                                    new_response = handle_feedback(original_prompt, user_feedback, system_info, conversation_history, logger, debug=debug)
                                    if new_response:
                                        if 'commands' in new_response:
                                            commands = new_response['commands']
                                        elif 'command' in new_response:
                                            commands = [new_response['command']]
                                        elif 'report' in new_response:
                                            generate_report(new_response['report'], logger, debug=debug)
                                            break
                                        else:
                                            print(f"{Fore.RED}GPT-4o-mini did not provide new commands or a report. Exiting task execution.{Style.RESET_ALL}")
                                            break
                                    else:
                                        print(f"{Fore.RED}Failed to get a new response from GPT-4o-mini. Exiting task execution.{Style.RESET_ALL}")
                                        break
                                else:
                                    print(f"{Fore.RED}A command failed without an error message. Exiting task execution.{Style.RESET_ALL}")
                                    break
                else:
                    print(f"{Fore.RED}No commands to execute based on the provided task.{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}No task entered.{Style.RESET_ALL}")

        elif choice == '2':
            summarize_last_run(LOG_DIR_PATH, logger)

        elif choice == '3':
            session_id = input(
                "Enter the Session ID to rollback (or 'last' for the most recent): ").strip().lower()
            if session_id:
                rollback_session(session_id, LOG_DIR_PATH, logger, debug=debug)
            else:
                print(f"{Fore.RED}No Session ID entered.{Style.RESET_ALL}")

        elif choice == '4':
            criteria = input("Enter the criteria for the report: ").strip()
            if criteria:
                generate_report(criteria, logger, debug=debug)
            else:
                print(f"{Fore.RED}No criteria entered.{Style.RESET_ALL}")

        elif choice == '5':
            print(f"{Fore.CYAN}Exiting Ganesha Interactive Menu.{Style.RESET_ALL}")
            break

        else:
            print(f"{Fore.RED}Invalid choice. Please select a number between 1 and 5.{Style.RESET_ALL}")

# ------------------------------ Initial Commands Function ------------------------

def get_initial_commands(task, logger, debug=False):
    """
    Retrieves the initial command(s) from the user input.

    Args:
        task (str): Initial task description.
        logger (logging.LoggerAdapter): Logger for logging messages.
        debug (bool): Flag to indicate if debug information should be printed.

    Returns:
        list or None: The command(s) generated by GPT-4o-mini or None if generation fails.
    """
    if task:
        user_prompt = task
    else:
        user_prompt = input(
            "Enter the command prompt for GPT-4o-mini: ").strip()

    if not user_prompt:
        logger.error("Empty prompt provided. Exiting.")
        return None

    logger.info("Generating command from GPT-4o-mini...")
    system_info = gather_system_info()
    parsed_response = gpt_generate_command(
        prompt=user_prompt,
        logger=logger,
        system_info=system_info,
        debug=debug
    )

    if parsed_response:
        if 'report' in parsed_response:
            report = parsed_response['report']
            # Attempt to parse the report if it's JSON
            if isinstance(report, dict):
                readable_report = generate_readable_report(report)
            else:
                try:
                    report_dict = json.loads(report)
                    readable_report = generate_readable_report(report_dict)
                except json.JSONDecodeError:
                    # If not JSON, use the report as is
                    readable_report = report

            # Display the report in a formatted manner with bold styling
            print(f"{Style.BRIGHT}\n*** Generated Report ***\n{Style.RESET_ALL}")
            print(f"{Style.BRIGHT}{readable_report}{Style.RESET_ALL}")
            print(f"{Style.BRIGHT}\n*** End of Report ***\n{Style.RESET_ALL}")
            # Optionally, log the report
            report_log = {
                'report': report
            }
            with open(logger.logger.handlers[0].baseFilename, 'a') as log_file:
                log_file.write(json.dumps(report_log) + '\n')
            return None  # No commands to execute
        else:
            commands = []
            if 'command' in parsed_response:
                commands = [parsed_response['command']]
            elif 'commands' in parsed_response and isinstance(parsed_response['commands'], list):
                commands = parsed_response['commands']
            else:
                logger.error(
                    "GPT-4o-mini response does not contain 'command' or 'commands' fields.")
                return None

            # Log the start of the run with the initial task
            start_log = {
                'run_id': logger.extra['run_id'],
                'start_time': datetime.now().isoformat(),
                'action': 'start',
                'system_info': system_info,
                'task': task
            }
            with open(logger.logger.handlers[0].baseFilename, 'a') as log_file:
                log_file.write(json.dumps(start_log) + '\n')

            return commands
    else:
        logger.error(
            "Failed to generate the initial command. Ensure GPT-4o-mini returns a JSON with a 'command' or 'commands' field.")
        return None

# ------------------------------ Main Function ------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ganesha: GPT-4o-mini Powered Cross-Platform Command Executor"
    )
    
    # Define command-line arguments
    parser.add_argument('task', nargs='*', help='Task to execute in plain English, e.g., "install Docker"')
    parser.add_argument('--install', action='store_true', help='Install required dependencies')
    parser.add_argument('--setup', action='store_true', help="Setup 'ganesha' command in PATH for easy access")
    parser.add_argument('--summary', action='store_true', help="Summarize the last run's activities.")
    parser.add_argument('--rollback', nargs='*', help="Rollback specified session's changes; omit to rollback last session.")
    parser.add_argument('--report', type=str, help="Generate a report based on criteria.")
    parser.add_argument('--interactive', action='store_true', help="Launch the interactive menu.")
    parser.add_argument('--debug', action='store_true', help="Enable debug mode.")
    parser.add_argument('--A', action='store_true', help="Auto-confirm all commands without prompt.")

    args = parser.parse_args()

    # Initialize logging
    run_id = f"main_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    log_file_path = os.path.join(LOG_DIR_PATH, f"session_main_{datetime.now().strftime('%Y%m%d%H%M%S')}.log")
    logger = setup_logger(run_id=run_id, log_file_path=log_file_path)

    # Enable debug logging if specified
    debug = args.debug

    try:
        # Handle the --install option
        if args.setup:
            print("Setting up the 'ganesha' command...")
            setup_ganesha_command()
            print("Setup complete. You can now run 'ganesha' from any command prompt.")
            return
        if args.install:
            try:
                install_dependencies()
                print("Dependencies installed successfully.")
                logger.info("Dependencies installed successfully.")
            except Exception as e:
                logger.error(f"Dependency installation failed: {e}")
            return

        # Proceed only if a task is provided or in interactive mode
        if not args.task and not args.interactive:
            print("Error: No task provided. Please provide a task or use --interactive.")
            parser.print_help()
            logger.error("No task provided and not in interactive mode.")
            sys.exit(1)

        # Convert task list into a single string (command)
        initial_task = ' '.join(args.task) if args.task else None

        # Process other flags and run appropriate functions based on parsed args
        if args.summary:
            logger.info("Summarizing last run.")
            summarize_last_run(LOG_DIR_PATH, logger)

        elif args.rollback is not None:
            session_ids = args.rollback if args.rollback else ['last']
            logger.info(f"Rolling back sessions: {session_ids}")
            rollback_sessions(session_ids, LOG_DIR_PATH, logger, debug=debug)

        elif args.report:
            criteria = args.report
            logger.info(f"Generating report based on criteria: {criteria}")
            generate_report(criteria, logger, debug=debug)

        elif args.interactive:
            logger.info("Launching interactive menu.")
            interactive_menu(debug=debug)

        elif initial_task:
            # Run the task specified in plain English
            logger.info(f"Executing task: {initial_task}")
            commands = get_initial_commands(initial_task, logger, debug=debug)
            if commands:
                explanations = [cmd.get('explanation', "No explanation provided.") for cmd in commands]
                command_texts = [cmd.get('command') if isinstance(cmd, dict) else cmd for cmd in commands]
                execute_commands(command_texts, explanations, logger, allow_all=args.A, quiet_commands=not debug, debug=debug)
            else:
                print("No commands generated for the provided task.")
                logger.error("Failed to generate commands for the provided task.")

        else:
            print("Invalid command usage.")
            parser.print_help()
            logger.error("Invalid command usage, no matching option.")
    except Exception as e:
        logger.error(f"Unhandled exception in main: {e}")
        print(f"Error encountered: {e}")


# ------------------------------ Entry Point ------------------------------

if __name__ == "__main__":
    main()