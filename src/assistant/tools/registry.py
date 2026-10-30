"""Tools the agent can use, with their argument schemas and side-effect flag.

How tool calling works: Nemotron never executes anything. It replies with a JSON
"I want to call tool X with these arguments". Our code validates the arguments
against a Pydantic schema and decides whether to run it. Tools with side_effect=True
(they change memory or run code) ALWAYS need the user's explicit approval first.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="What to search for")


class ListFactsArgs(BaseModel):
    pass


class RememberFactArgs(BaseModel):
    fact: str = Field(
        min_length=1,
        max_length=500,
        description="Durable fact about the user, as a short third-person sentence in Spanish",
    )
    category: Literal["preference", "personal", "work", "goal", "other"] = "other"


class ForgetFactArgs(BaseModel):
    fact_id: str = Field(min_length=1, max_length=64, description="Exact id from list_facts")


class RunCodeArgs(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=20_000,
        description="Complete Python 3 program. Print the results with print().",
    )
    explanation: str = Field(
        default="",
        max_length=500,
        description="One short sentence in Spanish explaining what the code does",
    )


class ListSkillsArgs(BaseModel):
    pass


class SaveSkillArgs(BaseModel):
    name: str = Field(
        pattern=r"^[a-z0-9][a-z0-9_]{1,39}$",
        description="Short snake_case name, e.g. calcular_ahorro",
    )
    description: str = Field(
        min_length=1, max_length=300, description="What the skill does, one sentence in Spanish"
    )
    parameters: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Names of the inputs, e.g. ['ahorro_mensual', 'objetivo']",
    )
    code: str = Field(
        min_length=1,
        max_length=20_000,
        description="Python 3 program that reads its inputs from the dict `params` "
        "(e.g. params['objetivo']) and prints the result. Do not define `params` yourself.",
    )


class RunSkillArgs(BaseModel):
    name: str = Field(min_length=1, max_length=40, description="Name of a saved skill")
    params: dict[str, Any] = Field(
        default_factory=dict, description="Values for the skill's parameters"
    )


class DeleteSkillArgs(BaseModel):
    name: str = Field(min_length=1, max_length=40)


NOTE_PATH = Field(
    min_length=4,
    max_length=300,
    description="Path relative to the Obsidian vault, with .md, e.g. 'Diario/2026-10-30.md'",
)


REPO_PATH = Field(
    min_length=1,
    max_length=300,
    description="Repository folder relative to the projects folder, e.g. 'Algoria'",
)


class ListProjectsArgs(BaseModel):
    pass


class RepoArgs(BaseModel):
    repo: str = REPO_PATH


class GitCommitArgs(BaseModel):
    repo: str = REPO_PATH
    message: str = Field(
        min_length=3,
        max_length=500,
        description="Commit message: short imperative summary (Conventional Commits if the "
        "repo uses them), based on git_diff",
    )


class CreateFolderArgs(BaseModel):
    path: str = Field(
        min_length=1,
        max_length=300,
        description="New folder relative to the projects folder, e.g. 'Pruebas de IA'",
    )


class ListNotesArgs(BaseModel):
    folder: str = Field(default="", max_length=200, description="Only notes inside this folder")
    query: str = Field(
        default="", max_length=100, description="Only notes whose path contains this"
    )


class ReadNoteArgs(BaseModel):
    path: str = NOTE_PATH


class SearchNotesArgs(BaseModel):
    text: str = Field(
        min_length=1, max_length=200, description="Exact text to find (case-insensitive)"
    )


class ListTasksArgs(BaseModel):
    pass


class WriteNoteArgs(BaseModel):
    path: str = NOTE_PATH
    content: str = Field(min_length=1, max_length=50_000, description="Markdown to write")
    mode: Literal["create", "append", "overwrite"] = Field(
        description="create: new note (fails if it exists); append: add at the end (creates it "
        "if missing); overwrite: replace the whole note (read it first, keep what should stay)"
    )


class MediaControlArgs(BaseModel):
    action: Literal["play_pause", "next", "previous", "volume_up", "volume_down", "mute"] = Field(
        description="play_pause toggles; next/previous change the song; volume_* / mute"
    )


class NowPlayingArgs(BaseModel):
    pass


class SpotifyPlayArgs(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=200,
        description="Only the title of the song/album/playlist (or the artist name when kind is "
        "artist), e.g. 'Parce' — without the artist",
    )
    artist: str = Field(
        default="",
        max_length=100,
        description="The artist, separately, when the user names one, e.g. 'Maluma'",
    )
    kind: Literal["track", "artist", "album", "playlist"] = Field(
        default="track", description="track for a song; artist/album/playlist to play a collection"
    )


class NoArgs(BaseModel):
    pass


class SetReminderArgs(BaseModel):
    text: str = Field(min_length=1, max_length=300, description="What to remind, in Spanish")
    in_minutes: float | None = Field(
        default=None, gt=0, le=60 * 24 * 30, description="Minutes from now"
    )
    at: str | None = Field(
        default=None,
        max_length=40,
        description="Exact local time, ISO 8601 with offset, e.g. 2026-10-31T07:00:00-06:00 "
        "(compute it from NOW). Give either in_minutes or at.",
    )


class ReminderIdArgs(BaseModel):
    id: str = Field(min_length=1, max_length=40)


class OpenAppArgs(BaseModel):
    name: str = Field(
        min_length=1, max_length=100, description="App name, e.g. 'Discord', 'Chrome'"
    )


class OpenUrlArgs(BaseModel):
    url: str = Field(min_length=8, max_length=500, pattern=r"^https?://", description="http(s) URL")


class OpenFolderArgs(BaseModel):
    path: str = Field(
        min_length=1,
        max_length=300,
        description="'Descargas', 'Escritorio', 'Documentos', or a folder relative to the "
        "projects folder",
    )


class OpenFileArgs(BaseModel):
    path: str = Field(min_length=1, max_length=400, description="File path from find_files")


class OpenInEditorArgs(BaseModel):
    project: str = Field(min_length=1, max_length=300, description="Project folder, e.g. 'Algoria'")


ROUTINE_STEP_TOOLS = Literal[
    "open_app", "open_url", "open_folder", "open_in_editor", "spotify_play", "media_control"
]


class RoutineStep(BaseModel):
    tool: ROUTINE_STEP_TOOLS
    args: dict[str, Any] = Field(default_factory=dict)


class SaveRoutineArgs(BaseModel):
    name: str = Field(
        pattern=r"^[a-z0-9áéíóúñ ]{2,40}$", description="Short name, e.g. 'modo trabajo'"
    )
    description: str = Field(default="", max_length=200)
    steps: list[RoutineStep] = Field(min_length=1, max_length=10)


class RunRoutineArgs(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class WriteClipboardArgs(BaseModel):
    text: str = Field(min_length=1, max_length=20_000, description="Text to leave copied")


class LookAtScreenArgs(BaseModel):
    question: str = Field(
        min_length=1, max_length=300, description="What to find out from the screen, in Spanish"
    )


class WeatherArgs(BaseModel):
    place: str = Field(min_length=2, max_length=100, description="City, e.g. 'Torreón'")
    days: int = Field(default=1, ge=1, le=7, description="Days of forecast")


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=300, description="What to look up on the web")


class FindFilesArgs(BaseModel):
    query: str = Field(min_length=1, max_length=100, description="Words in the file name")
    extension: str = Field(default="", max_length=10, description="Optional, e.g. 'pdf'")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    side_effect: bool
    # Runs on the user's computer, in the desktop app (e.g. media keys, Spotify). The API
    # hands the call to the app and waits for its result. Low-risk actions only.
    client_side: bool = False
    # Extra rule: needs approval for these particular arguments (e.g. a URL carrying data).
    approve_if: Callable[[Any], bool] | None = None


def requires_approval(tool: Tool, args: Any) -> bool:
    """Side-effect tools always need the user's approval; some others only for risky args."""
    return tool.side_effect or (
        tool.approve_if is not None and args is not None and tool.approve_if(args)
    )


def url_carries_data(args: Any) -> bool:
    """Only a bare homepage (https://www.youtube.com) opens without approval. Anything with a
    path, query or fragment could carry the user's data out (e.g. text read from a note), so
    the user sees the exact URL first."""
    parsed = urlparse(args.url)
    return bool(parsed.path.strip("/") or parsed.query or parsed.fragment or parsed.params)


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "search_knowledge",
            "Search the user's personal notes and documents. Use it when the provided "
            "context is missing or not enough to answer.",
            SearchKnowledgeArgs,
            side_effect=False,
        ),
        Tool(
            "list_facts",
            "List the facts stored about the user, with their ids.",
            ListFactsArgs,
            side_effect=False,
        ),
        Tool(
            "remember_fact",
            "Store a durable fact about the user in long-term memory. Use it when the user "
            "asks you to remember something or states a lasting preference.",
            RememberFactArgs,
            side_effect=True,
        ),
        Tool(
            "forget_fact",
            "Delete a stored fact about the user. Call list_facts first to get the id.",
            ForgetFactArgs,
            side_effect=True,
        ),
        Tool(
            "run_code_in_sandbox",
            "Run a Python 3 program in an isolated sandbox: no internet, no access to the "
            "user's files, 30 s limit, UTC clock; numpy and pandas are available. Use it for "
            "multi-step calculations, data processing, or when the user asks to run code. "
            "Never for the current time/date or simple arithmetic: answer those directly.",
            RunCodeArgs,
            side_effect=True,
        ),
        Tool(
            "list_skills",
            "List the user's saved reusable skills with their parameters.",
            ListSkillsArgs,
            side_effect=False,
        ),
        Tool(
            "save_skill",
            "Save a working Python program as a reusable skill for the user. Generalize it: "
            "read the inputs from `params` instead of hardcoding them. Call it only when the "
            "user asks to save something as a skill.",
            SaveSkillArgs,
            side_effect=True,
        ),
        Tool(
            "run_skill",
            "Run one of the user's saved skills in the sandbox with the given parameters. "
            "Prefer it over writing new code when a saved skill fits the request.",
            RunSkillArgs,
            side_effect=True,
        ),
        Tool(
            "delete_skill",
            "Delete one of the user's saved skills.",
            DeleteSkillArgs,
            side_effect=True,
        ),
        Tool(
            "list_notes",
            "List the notes in the user's Obsidian vault (most recent first), optionally by "
            "folder or by a word in the path.",
            ListNotesArgs,
            side_effect=False,
        ),
        Tool(
            "read_note",
            "Read one note from the user's Obsidian vault.",
            ReadNoteArgs,
            side_effect=False,
        ),
        Tool(
            "search_notes",
            "Find an exact word or phrase in the Obsidian vault; returns matching lines with "
            "note path and line number. Use search_knowledge for questions by meaning.",
            SearchNotesArgs,
            side_effect=False,
        ),
        Tool(
            "list_tasks",
            "List unchecked tasks (- [ ]) across the Obsidian vault.",
            ListTasksArgs,
            side_effect=False,
        ),
        Tool(
            "media_control",
            "Control the music playing on the user's computer (Spotify or any player): "
            "pause/resume, next or previous song, volume.",
            MediaControlArgs,
            side_effect=False,
            client_side=True,
        ),
        Tool(
            "now_playing",
            "Which song is playing now in Spotify on the user's computer.",
            NowPlayingArgs,
            side_effect=False,
            client_side=True,
        ),
        Tool(
            "spotify_play",
            "Search Spotify and play a song, artist, album or playlist on the user's computer.",
            SpotifyPlayArgs,
            side_effect=False,
            client_side=True,
        ),
        # ---- reminders (kept by the desktop app; notification + voice when due) ----------
        Tool(
            "set_reminder",
            "Set a reminder or timer that notifies the user (with voice) at a time.",
            SetReminderArgs,
            side_effect=False,
            client_side=True,
        ),
        Tool(
            "list_reminders",
            "List the user's pending reminders with their ids.",
            NoArgs,
            side_effect=False,
            client_side=True,
        ),
        Tool(
            "cancel_reminder",
            "Cancel a pending reminder by id (from list_reminders).",
            ReminderIdArgs,
            side_effect=False,
            client_side=True,
        ),
        # ---- open things on the computer ----------------------------------------------------
        Tool(
            "open_app",
            "Open an installed app on the user's computer (Start menu apps only).",
            OpenAppArgs,
            side_effect=False,
            client_side=True,
        ),
        Tool(
            "open_url",
            "Open a website in the user's browser (a bare homepage opens directly; URLs with a "
            "path or search terms are shown to the user for approval).",
            OpenUrlArgs,
            side_effect=False,
            client_side=True,
            approve_if=url_carries_data,
        ),
        Tool(
            "open_folder",
            "Open a folder in the file explorer.",
            OpenFolderArgs,
            side_effect=False,
            client_side=True,
        ),
        Tool(
            "open_file",
            "Open a document, image or media file (from find_files) with its default app.",
            OpenFileArgs,
            side_effect=False,
            client_side=True,
        ),
        Tool(
            "open_in_editor",
            "Open a project folder in Visual Studio Code.",
            OpenInEditorArgs,
            side_effect=False,
            client_side=True,
        ),
        # ---- routines (several actions under one name) -------------------------------------
        Tool(
            "list_routines",
            "List the user's saved routines and their steps.",
            NoArgs,
            side_effect=False,
            client_side=True,
        ),
        Tool(
            "save_routine",
            "Save a routine: a named list of computer actions (open_app, open_url, open_folder, "
            "open_in_editor, spotify_play, media_control) to run together, e.g. 'modo trabajo'.",
            SaveRoutineArgs,
            side_effect=True,
            client_side=True,
        ),
        Tool(
            "run_routine",
            "Run one of the user's saved routines by name.",
            RunRoutineArgs,
            side_effect=False,
            client_side=True,
        ),
        # ---- clipboard and screen ------------------------------------------------------------
        Tool(
            "read_clipboard",
            "Read the text the user has copied (to summarize, translate, fix it...). Needs "
            "approval: the clipboard may hold passwords or codes.",
            NoArgs,
            side_effect=True,
            client_side=True,
        ),
        Tool(
            "write_clipboard",
            "Leave a text copied in the user's clipboard (replaces what is there).",
            WriteClipboardArgs,
            side_effect=True,
            client_side=True,
        ),
        Tool(
            "look_at_screen",
            "Take a screenshot of the user's screen and answer a question about it (it is sent "
            "to the AI provider). Use only when the user asks about what is on their screen.",
            LookAtScreenArgs,
            side_effect=True,
            client_side=True,
        ),
        # ---- information ---------------------------------------------------------------------
        Tool(
            "get_weather",
            "Current weather and forecast for a city.",
            WeatherArgs,
            side_effect=False,
        ),
        Tool(
            "web_search",
            "Search the web for current information (news, facts, prices...). Returns an "
            "answer with sources.",
            WebSearchArgs,
            side_effect=False,
        ),
        Tool(
            "find_files",
            "Find files by name in the user's projects folder (e.g. Documents).",
            FindFilesArgs,
            side_effect=False,
        ),
        Tool(
            "repos_overview",
            "Local git status of every repository in the projects folder (no network): "
            "uncommitted changes and unpushed commits. Good for a morning briefing.",
            NoArgs,
            side_effect=False,
        ),
        Tool(
            "list_projects",
            "List the folders and git repositories in the user's projects folder.",
            ListProjectsArgs,
            side_effect=False,
        ),
        Tool(
            "git_status",
            "Git status of a repository: branch, uncommitted changes, commits not pushed "
            "(and not pulled). Use it for 'are there pending commits?'.",
            RepoArgs,
            side_effect=False,
        ),
        Tool(
            "git_diff",
            "The uncommitted changes of a repository (stat + diff), to understand them or "
            "to write a commit message.",
            RepoArgs,
            side_effect=False,
        ),
        Tool(
            "git_commit",
            "Stage all changes (git add -A) and commit them with a message. Call git_diff "
            "first to write a good message.",
            GitCommitArgs,
            side_effect=True,
        ),
        Tool(
            "git_push",
            "Push the current branch of a repository to its remote (GitHub).",
            RepoArgs,
            side_effect=True,
        ),
        Tool(
            "create_folder",
            "Create a new folder (and missing parents) inside the user's projects folder.",
            CreateFolderArgs,
            side_effect=True,
        ),
        Tool(
            "write_note",
            "Create a note, append to one (e.g. today's daily note or a task list) or replace "
            "a note in the Obsidian vault. The user sees and approves the exact content.",
            WriteNoteArgs,
            side_effect=True,
        ),
    )
}


def openai_tool_specs() -> list[dict[str, Any]]:
    """Tool definitions in the OpenAI `tools` format that Nebius accepts."""
    specs = []
    for tool in TOOLS.values():
        schema = tool.args_model.model_json_schema()
        schema.pop("title", None)
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": schema,
                },
            }
        )
    return specs
