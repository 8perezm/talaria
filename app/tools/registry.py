# registry.py — the ONLY central edit when adding a tool: append one line.
# Order matters: index = bit in tools mask. Never reorder, only append.
from tools.tool_get_status import TOOL as Tool_get_status
from tools.tool_gpio_write import TOOL as Tool_gpio_write
from tools.tool_gpio_read import TOOL as Tool_gpio_read
from tools.tool_adc_read import TOOL as Tool_adc_read
from tools.tool_wifi_scan import TOOL as Tool_wifi_scan
from tools.tool_mem_save import TOOL as Tool_mem_save
from tools.tool_mem_read import TOOL as Tool_mem_read
from tools.tool_restart import TOOL as Tool_restart_device
from tools.tool_blink import TOOL as Tool_blink
from tools.tool_web_fetch import TOOL as Tool_web_fetch
from tools.tool_memory import TOOL as Tool_memory
from tools.tool_skills_list import TOOL as Tool_skills_list
from tools.tool_skill_view import TOOL as Tool_skill_view
from tools.tool_session_search import TOOL as Tool_session_search
from tools.tool_cron import TOOL as Tool_cron
from todo import TOOL as Tool_todo
from delegate import TOOL as Tool_delegate_task
from exec_py import TOOL as Tool_exec_py
from read_file import TOOL as Tool_read_file
from write_file import TOOL as Tool_write_file
from patch_file import TOOL as Tool_patch_file
from search_files import TOOL as Tool_search_files

TOOL_REGISTRY = [
    Tool_get_status,
    Tool_gpio_write,
    Tool_gpio_read,
    Tool_adc_read,
    Tool_wifi_scan,
    Tool_mem_save,
    Tool_mem_read,
    Tool_restart_device,
    Tool_blink,
    Tool_web_fetch,
    Tool_memory,
    Tool_skills_list,
    Tool_skill_view,
    Tool_session_search,
    Tool_cron,
    Tool_todo,
    Tool_delegate_task,
    Tool_exec_py,
    Tool_read_file,
    Tool_write_file,
    Tool_patch_file,
    Tool_search_files,
]

TOOL_COUNT = len(TOOL_REGISTRY)


def register_into_agent_tools():
    import agent_tools
    agent_tools.TOOL_REGISTRY = TOOL_REGISTRY
    agent_tools.TOOL_COUNT = TOOL_COUNT
