from windows_mcp.analytics import PostHogAnalytics, with_analytics
from live_inspect.watch_cursor import WatchCursor
from windows_mcp.desktop.service import Desktop
from contextlib import asynccontextmanager
from fastmcp.utilities.types import Image
from mcp.types import ToolAnnotations
from typing import Literal, Optional
from humancursor import SystemCursor
from fastmcp import FastMCP, Context
from dotenv import load_dotenv
from textwrap import dedent
import pyautogui as pg
import asyncio
import click
import os

load_dotenv()

pg.FAILSAFE=False
pg.PAUSE=1.0

desktop=Desktop()
cursor=SystemCursor()
watch_cursor=WatchCursor()
windows_version=desktop.get_windows_version()
default_language=desktop.get_default_language()
screen_width,screen_height=desktop.get_resolution()

instructions=dedent(f'''
Windows MCP server provides tools to interact directly with the {windows_version} desktop, 
thus enabling to operate the desktop on the user's behalf.
''')

# Initialize analytics at module level to be used in decorators
if os.getenv("ANONYMIZED_TELEMETRY", "true").lower() == "false":
    analytics = None
else:
    analytics = PostHogAnalytics()

@asynccontextmanager
async def lifespan(app: FastMCP):
    """Runs initialization code before the server starts and cleanup code after it shuts down."""
    try:
        watch_cursor.start()
        await asyncio.sleep(1) # Simulate startup latency
        yield
    finally:
        watch_cursor.stop()
        if analytics:
            await analytics.close()

mcp=FastMCP(name='windows-mcp',instructions=instructions,lifespan=lifespan)

@mcp.tool(
    name="App-Tool",
    description="Manages Windows applications with three modes: 'launch' (start app by name), 'resize' (set window position/size using window_loc=[x,y] and window_size=[width,height]), 'switch' (activate app by name). Essential for application lifecycle management.",
    annotations=ToolAnnotations(
        title="App Tool",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False
    )
    )
@with_analytics(analytics, "App-Tool")
def app_tool(mode:Literal['launch','resize','switch'],name:str|None=None,window_loc:list[int]|None=None,window_size:list[int]|None=None, ctx: Context = None):
    return desktop.app(mode,name,window_loc,window_size)
    
@mcp.tool(
    name='Powershell-Tool',
    description='Execute PowerShell commands directly on the Windows system and return output with status code. Supports all PowerShell cmdlets, scripts, and system commands. Use for file operations, system queries, and administrative tasks.',
    annotations=ToolAnnotations(
        title="Powershell Tool",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True
    )
    )
@with_analytics(analytics, "Powershell-Tool")
def powershell_tool(command: str, ctx: Context = None) -> str:
    response,status_code=desktop.execute_command(command)
    return f'Response: {response}\nStatus Code: {status_code}'

@mcp.tool(
    name='State-Tool',
    description='Captures complete desktop state including: system language, focused/opened apps, interactive elements (buttons, text fields, links, menus with coordinates), and scrollable areas. Set use_vision=True to include screenshot. Set use_dom=True for browser content to get web page elements instead of browser UI. Always call this first to understand the current desktop state before taking actions.',
    annotations=ToolAnnotations(
        title="State Tool",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
    )
@with_analytics(analytics, "State-Tool")
def state_tool(use_vision:bool=False,use_dom:bool=False, ctx: Context = None):
    # Calculate scale factor to cap resolution at 1080p (1920x1080)
    max_width, max_height = 1920, 1080
    scale_width = max_width / screen_width if screen_width > max_width else 1.0
    scale_height = max_height / screen_height if screen_height > max_height else 1.0
    scale = min(scale_width, scale_height)  # Use the smaller scale to ensure both dimensions fit
    
    desktop_state=desktop.get_state(use_vision=use_vision,use_dom=use_dom,as_bytes=True,scale=scale)
    interactive_elements=desktop_state.tree_state.interactive_elements_to_string()
    scrollable_elements=desktop_state.tree_state.scrollable_elements_to_string()
    apps=desktop_state.apps_to_string()
    active_app=desktop_state.active_app_to_string()
    return [dedent(f'''
    Default Language of User:
    {default_language} with encoding: {desktop.encoding}
                            
    Focused App:
    {active_app}

    Opened Apps:
    {apps}

    List of Interactive Elements:
    {interactive_elements or 'No interactive elements found.'}

    List of Scrollable Elements:
    {scrollable_elements or 'No scrollable elements found.'}
    ''')]+([Image(data=desktop_state.screenshot,format='png')] if use_vision else [])

@mcp.tool(
    name='Click-Tool',
    description='Performs mouse clicks at specified coordinates [x, y]. Supports button types: left (default), right (context menu), middle. Supports clicks: 1 (single), 2 (double), 3 (triple). Always use coordinates from State-Tool output to ensure accuracy.',
    annotations=ToolAnnotations(
        title="Click Tool",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False
    )
    )
@with_analytics(analytics, "Click-Tool")
def click_tool(loc:list[int],button:Literal['left','right','middle']='left',clicks:int=1, ctx: Context = None)->str:
    if len(loc) != 2:
        raise ValueError("Location must be a list of exactly 2 integers [x, y]")
    x,y=loc[0],loc[1]
    desktop.click(loc=loc,button=button,clicks=clicks)
    num_clicks={1:'Single',2:'Double',3:'Triple'}
    return f'{num_clicks.get(clicks)} {button} clicked at ({x},{y}).'

@mcp.tool(
    name='Type-Tool',
    description='Types text at specified coordinates [x, y]. Set clear=True to clear existing text first (Ctrl+A then type), clear=False to append. Set press_enter=True to submit after typing. Always click on the target input field first to ensure focus.',
    annotations=ToolAnnotations(
        title="Type Tool",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False
    )
    )
@with_analytics(analytics, "Type-Tool")
def type_tool(loc:list[int],text:str,clear:bool=False,press_enter:bool=False, ctx: Context = None)->str:
    if len(loc) != 2:
        raise ValueError("Location must be a list of exactly 2 integers [x, y]")
    x,y=loc[0],loc[1]
    desktop.type(loc=loc,text=text,clear=clear,press_enter=press_enter)
    return f'Typed {text} at ({x},{y}).'

@mcp.tool(
    name='Scroll-Tool',
    description='Scrolls at coordinates [x, y] or current mouse position if loc=None. Type: vertical (default) or horizontal. Direction: up/down for vertical, left/right for horizontal. wheel_times controls amount (1 wheel ≈ 3-5 lines). Use for navigating long content, lists, and web pages.',
    annotations=ToolAnnotations(
        title="Scroll Tool",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
    )
@with_analytics(analytics, "Scroll-Tool")
def scroll_tool(loc:list[int]=None,type:Literal['horizontal','vertical']='vertical',direction:Literal['up','down','left','right']='down',wheel_times:int=1, ctx: Context = None)->str:
    if loc and len(loc) != 2:
        raise ValueError("Location must be a list of exactly 2 integers [x, y]")
    response=desktop.scroll(loc,type,direction,wheel_times)
    if response:
        return response
    return f'Scrolled {type} {direction} by {wheel_times} wheel times'+f' at ({loc[0]},{loc[1]}).' if loc else ''

@mcp.tool(
    name='Drag-Tool',
    description='Performs drag-and-drop from current mouse position to destination coordinates [x, y]. Click or move to source position first, then call this tool with target coordinates. Use for moving files, reordering items, resizing windows, or any drag-drop UI interactions.',
    annotations=ToolAnnotations(
        title="Drag Tool",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False
    )
    )
@with_analytics(analytics, "Drag-Tool")
def drag_tool(to_loc:list[int], ctx: Context = None)->str:
    if len(to_loc) != 2:
        raise ValueError("to_loc must be a list of exactly 2 integers [x, y]")
    desktop.drag(to_loc)
    x2,y2=to_loc[0],to_loc[1]
    return f'Dragged the element to ({x2},{y2}).'

@mcp.tool(
    name='Move-Tool',
    description='Moves mouse cursor to coordinates [x, y] without clicking. Use for hovering to reveal tooltips/menus, positioning cursor before drag operations, or triggering hover-based UI changes. Does not interact with elements.',
    annotations=ToolAnnotations(
        title="Move Tool",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
    )
@with_analytics(analytics, "Move-Tool")
def move_tool(to_loc:list[int], ctx: Context = None)->str:
    if len(to_loc) != 2:
        raise ValueError("to_loc must be a list of exactly 2 integers [x, y]")
    x,y=to_loc[0],to_loc[1]
    desktop.move(to_loc)
    return f'Moved the mouse pointer to ({x},{y}).'

@mcp.tool(
    name='Shortcut-Tool',
    description='Executes keyboard shortcuts using key combinations separated by +. Examples: "ctrl+c" (copy), "ctrl+v" (paste), "alt+tab" (switch apps), "win+r" (Run dialog), "win" (Start menu), "ctrl+shift+esc" (Task Manager). Use for quick actions and system commands.',
    annotations=ToolAnnotations(
        title="Shortcut Tool",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False
    )
    )
@with_analytics(analytics, "Shortcut-Tool")
def shortcut_tool(shortcut:str, ctx: Context = None):
    desktop.shortcut(shortcut)
    return f"Pressed {shortcut}."

@mcp.tool(
    name='Wait-Tool',
    description='Pauses execution for specified duration in seconds. Use when waiting for: applications to launch/load, UI animations to complete, page content to render, dialogs to appear, or between rapid actions. Helps ensure UI is ready before next interaction.',
    annotations=ToolAnnotations(
        title="Wait Tool",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
    )
@with_analytics(analytics, "Wait-Tool")
def wait_tool(duration:int, ctx: Context = None)->str:
    pg.sleep(duration)
    return f'Waited for {duration} seconds.'

@mcp.tool(
    name='Scrape-Tool',
    description='Fetch content from a URL or the active browser tab. By default (use_dom=False), performs a lightweight HTTP request to the URL and returns markdown content of complete webpage. Note: Some websites may block automated HTTP requests. If this fails, open the page in a browser and retry with use_dom=True to extract visible text from the active tab\'s DOM within the viewport.',
    annotations=ToolAnnotations(
        title="Scrape Tool",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True
    )
    )
@with_analytics(analytics, "Scrape-Tool")
def scrape_tool(url:str,use_dom:bool=False, ctx: Context = None)->str:
    if not use_dom:
        content=desktop.scrape(url)
        return f'URL:{url}\nContent:\n{content}'

    desktop_state=desktop.get_state(use_vision=False,use_dom=use_dom)
    tree_state=desktop_state.tree_state
    if not tree_state.dom_info:
        return f'No DOM information found. Please open {url} in browser first.'
    dom_info=tree_state.dom_info
    vertical_scroll_percent=dom_info.vertical_scroll_percent
    content='\n'.join([node.text for node in tree_state.dom_informative_nodes])
    header_status = "Reached top" if vertical_scroll_percent <= 0 else "Scroll up to see more"
    footer_status = "Reached bottom" if vertical_scroll_percent >= 100 else "Scroll down to see more"
    return f'URL:{url}\nContent:\n[{header_status}]\n{content}\n[{footer_status}]'


@click.command()
@click.option(
    "--transport",
    help="The transport layer used by the MCP server.",
    type=click.Choice(['stdio','sse','streamable-http']),
    default='stdio'
)
@click.option(
    "--host",
    help="Host to bind the SSE/Streamable HTTP server.",
    default="localhost",
    type=str,
    show_default=True
)
@click.option(
    "--port",
    help="Port to bind the SSE/Streamable HTTP server.",
    default=8000,
    type=int,
    show_default=True
)
def main(transport, host, port):
    if transport=='stdio':
        mcp.run()
    else:
        mcp.run(transport=transport,host=host,port=port)

if __name__ == "__main__":
    main()
