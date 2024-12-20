"""
This script is used in SABnzbd's post-processing to move and rename UFC files.

The script will attempt to extract the UFC event number (event name),
fighter names (title), and edition from the filename. Plex uses editions
to specify different versions of movies. We can use this to differentiate
between different versions of UFC files.

The editions used in output filenames are: Early Prelims, Prelims, and Main Event.

If the extraction is successful, the script will create a new folder in
destination_folder. It will then rename and move the file to the new folder.

The formatting of the folder name and filenames is defined in the script.

If the extraction is unsuccessful or any other errors occur, the script will
print an error message and exit with a non-zero exit code.
"""

import os
import re
import sys
import stat
import shutil
import argparse
from enum import Enum
from pathlib import Path
from configparser import ConfigParser
from dataclasses import dataclass, fields
from typing import NoReturn, ClassVar, Any, Set, Dict

# Define the configuration file path. Defaults to ufc.ini in the script directory.
# This will fallback to ufc.ini.template if the main file does not exist.
INI_PATH = Path(__file__).parent / "ufc.ini"


class Bracket(Enum):
    """Enum for bracket types."""

    SQUARE = ("[", "]")
    CURLY = ("{", "}")
    ROUND = ("(", ")")


class Edition(Enum):
    """Enum for UFC event editions."""

    EARLY_PRELIMS = "Early Prelims"
    PRELIMS = "Prelims"
    MAIN_EVENT = "Main Event"


@dataclass
class VideoInfo:
    """Defines video information extracted from the file name."""

    event_number: str = ""
    fighter_names: str = ""
    edition: Edition = Edition.MAIN_EVENT
    resolution: str = ""
    path: Path = Path("")

    def __init__(self, path: Path, strict: bool = True) -> None:
        """
        Extracts information from a UFC video file name.

        Cleans up the file name then calls get_ functions to extract information.

        First tries to find the UFC event number. If not found and strict
        is True, the script exits. How it exits is determined by the
        STRICT_MATCHING variable.

        If fighter names are not found and strict is True, find_names()
        is called to attempt to find them from an existing folder.

        If the extraction is successful, assigns info to class attributes.

        :param path: The path of the file to extract information from
        :type path: str
        :param strict: Whether to try hard or not
        :type strict: bool
        """

        if not path or not path.exists():
            exit_log(f"File {path} does not exist", exit_code=1)

        self.path = path

        # Unify separators to spaces to make regex patterns less ungodly
        name = re.sub(r"[\.\s_]", " ", path.name)

        event_number = get_event_number(name)

        if not event_number:
            # might be obfuscated, check folder name
            folder_name = re.sub(r"[\.\s_]", " ", path.parent.name)
            event_number = get_event_number(folder_name)
            if event_number:
                name = folder_name

        if not event_number and strict:
            if Config.strict_matching:
                # error exit
                exit_log(f"Unable to extract UFC event number from {name}", exit_code=1)
            else:
                # silent exit
                exit_log(exit_code=0)

        fighter_names = get_fighter_names(name)

        if not fighter_names and strict:
            # we need to go deeper
            fighter_names = find_names(Config.destination_folder, event_number)

        edition = get_edition(name)

        self.event_number = event_number
        self.fighter_names = fighter_names
        self.edition = edition
        self.resolution = get_resolution(name)


@dataclass(frozen=False)
class Config:
    """
    Configuration settings for the UFC file controller.

    This class uses class variables to store global configuration settings.
    All settings are loaded from an INI file at startup.

    :cvar destination_folder: Root folder for UFC videos
    :cvar ufc_category: Category name for UFC downloads
    :cvar strict_matching: Whether to enforce strict name matching
    :cvar replace_same_res: Whether to replace files with same resolution
    :cvar dry_run: Whether to simulate operations without changes
    :cvar video_extensions: Set of valid video file extensions
    :cvar subfolder: Name of subfolder for non-main events
    :cvar format_order: Order and position of parts in filenames
    :cvar format_tokens: Bracket style for each part
    :cvar format_folder: Parts to include in folder names
    :cvar format_subfolder: Parts to include in filenames inside subfolders

    Note:
        All settings are class variables (ClassVar) to maintain global state.
        Settings are loaded from an INI file and validated at startup.
    """

    destination_folder: ClassVar[Path] = Path("/mnt/media/Sport/")
    ufc_category: ClassVar[str] = "ufc"
    strict_matching: ClassVar[bool] = False
    replace_same_res: ClassVar[bool] = False
    dry_run: ClassVar[bool] = False
    video_extensions: ClassVar[Set[str]] = {".mp4", ".mkv", ".avi", ".mov"}
    subfolder: ClassVar[str | None] = "Other"
    file_permissions: ClassVar[int] = 0o664
    folder_permissions: ClassVar[int] = 0o770
    format_order: ClassVar[Dict[str, int | None]] = {
        "event_number": 0,
        "fighter_names": 1,
        "edition": 2,
        "resolution": 3,
    }
    format_tokens: ClassVar[Dict[str, "Bracket"]] = {
        "edition": Bracket.CURLY,
        "resolution": Bracket.SQUARE,
    }
    format_folder: ClassVar[Set[str]] = {"event_number", "fighter_names"}
    format_subfolder: ClassVar[Set[str]] = {"event_number", "edition"}
    refresh_perms: ClassVar[bool] = False

    @classmethod
    def update(cls, **kwargs) -> None:
        """Update config values"""
        for key, value in kwargs.items():
            if hasattr(cls, key):
                setattr(cls, key, value)

    @classmethod
    def load_from_ini(cls, path: Path) -> None:
        """
        Load configuration settings from an INI file.

        Reads the INI file at the given path and updates the class configuration variables.
        Validates the configuration sections and keys before applying any changes.

        :param path: Path to the INI configuration file
        :type path: Path
        :raises ValueError: If validation fails due to missing/invalid sections/keys
        """

        config = ConfigParser(allow_no_value=True)

        # Read config file or template as fallback
        if path.exists():
            config.read(path)
        else:
            template = Path(__file__).parent / "ufc.ini.template"
            if not template.exists():
                raise FileNotFoundError("No config file or template found")
            config.read(template)
            print(f"Using template config: {template}")

        cls._validate_configuration(config)

        # Load paths
        cls.destination_folder = Path(config["Paths"]["destination_folder"])

        # Handle nullable subfolder name
        subfolder = config["Paths"]["subfolder"]
        subfolder = None if subfolder.lower() in ("none", "", "null") else subfolder
        if subfolder and not is_valid_folder_name(subfolder):
            raise ValueError(f'Invalid subfolder name: "{subfolder}"')
        cls.subfolder = subfolder

        # Load categories
        cls.ufc_category = config["Categories"]["ufc_category"]
        cls.strict_matching = (
            config["Categories"].getboolean("strict_matching") or cls.strict_matching
        )

        # Load file handling
        cls.replace_same_res = (
            config["FileHandling"].getboolean("replace_same_res")
            or cls.replace_same_res
        )
        cls.dry_run = config["FileHandling"].getboolean("dry_run") or cls.dry_run
        cls.video_extensions = set(
            ext.strip().lower()
            for ext in config["FileHandling"]["video_extensions"].split(",")
        )
        try:
            cls.file_permissions = parse_permissions(
                config["FileHandling"]["file_permissions"]
            )
            cls.folder_permissions = parse_permissions(
                config["FileHandling"]["folder_permissions"]
            )
        except ValueError as e:
            raise ValueError("Invalid permission value in configuration") from e

        # Load format order
        # Filter out non-digit values and create ordered list of parts
        ordered_parts = [
            key
            for key, _ in sorted(
                (
                    (key, value)
                    for key, value in config["Format.Order"].items()
                    if value.isdigit()
                ),
                key=lambda item: item[1],
            )
        ]
        if len(ordered_parts) < 2:
            raise ValueError("Format.Order must contain at least 2 parts")
        cls.format_order = ordered_parts

        # Load format tokens
        cls.format_tokens = {}
        for key in config["Format.Brackets"]:
            value = config["Format.Brackets"][key]
            if hasattr(Bracket, value.upper()):
                cls.format_tokens[key] = Bracket[value.upper()]
            else:
                raise ValueError(f"Invalid bracket type: {value}")

        # Load format folder
        cls.format_folder = set(config["Format.Folder"]["parts"].split(","))

        # Load format subfolder
        cls.format_subfolder = set(config["Format.Subfolder"]["parts"].split(","))

    @classmethod
    def _validate_configuration(cls, config: ConfigParser) -> None:
        """
        Validate the configuration.

        Checks if all required sections and keys are present in the config file,
        and validates that all format parts used in various sections are valid VideoInfo fields.

        :param config: ConfigParser object containing the configuration
        :type config: configparser.ConfigParser
        :raises ValueError: If validation fails, with details in the error message
        """

        format_parts = set(f.name for f in fields(VideoInfo)) - {"path"}

        # Validate config sections and keys
        required = {
            "Paths": ["destination_folder", "subfolder"],
            "Categories": ["ufc_category", "strict_matching"],
            "FileHandling": [
                "dry_run",
                "replace_same_res",
                "video_extensions",
                "file_permissions",
                "folder_permissions",
            ],
            "Format.Order": [],  # Dynamic keys
            "Format.Brackets": [],  # Dynamic keys
            "Format.Folder": ["parts"],
            "Format.Subfolder": ["parts"],
        }

        # Validate all sections and keys exist
        missing = []
        for section, keys in required.items():
            if section not in config:
                missing.append(f"Missing section: {section}")
                continue
            for key in keys:
                if key not in config[section]:
                    missing.append(f"Missing key in {section}: {key}")

        if missing:
            raise ValueError("Configuration validation failed:\n" + "\n".join(missing))

        errors = []
        # Format parts must match VideoInfo fields
        for name, parts in [
            ("Order", set(config["Format.Order"].keys())),
            ("Brackets", set(config["Format.Brackets"].keys())),
            ("Folder", set(config["Format.Folder"]["parts"].split(","))),
            ("Subfolder", set(config["Format.Subfolder"]["parts"].split(","))),
        ]:
            invalid = parts - format_parts
            if invalid:
                errors.append(f"Invalid Format.{name} parts: {invalid}")

        if errors:
            raise ValueError("Format parts validation failed:\n" + "\n".join(errors))


def exit_log(message: str = "", exit_code: int = 1) -> NoReturn:
    """
    Logs a message and exits the program with the specified exit code.

    Prints the provided message then terminates the program using sys.exit with the given exit code.

    :param message: The message to be logged before exiting.
    :type message: str
    :param exit_code: The exit code to be used when terminating the program.
    :type exit_code: int
    :return: NoReturn
    :raises SystemExit: Exits the program with the specified exit code.
    """

    print(f"Error: {message}" if exit_code else message)
    sys.exit(exit_code)


def check_path(path: Any, error: bool = True) -> Path | None:
    """
    Checks if the given path exists and is a directory.

    If the path exists and is a directory, returns the Path object.
    If the path does not exist or is not a directory, raises a NotADirectoryError.

    :param path: The path to check.
    :type path: any
    :param error: Whether to raise an error if the path does not exist or is not a directory.
    :type error: bool
    :return: The Path object of the given directory.
    :rtype: Path
    :raises NotADirectoryError: If the path does not exist or is not a directory.
    """

    try:
        if not isinstance(path, (str, Path)):
            raise TypeError("Path must be a string or Path object")
        directory = Path(path)
        if not (directory.exists() and directory.is_dir()):
            raise NotADirectoryError(
                f"Directory path '{
                    directory}' does not exist or is not a directory"
            )
    except (TypeError, ValueError, NotADirectoryError) as e:
        if error:
            raise NotADirectoryError(str(e)) from e
        return None

    return directory


def get_event_number(file_name: str) -> str:
    """
    Extracts the event number from a video file name.

    Returns a string of the event number or if no event number is found, returns "".

    :param file_name: The file name
    :type file_name: str
    :return: The extracted event number or empty string if no event number is found.
    :rtype: str
    """

    # there are also 'UFC Live' events which will not be caught, but they usually
    # don't have a number anyway
    pattern = (
        r"ufc ?(?P<ppv>\d+)"
        r"|ufc ?fight ?night (?P<fnight>\d+)"
        r"|ufc ?on ?(?P<ufc_on>\w+ \d+)"
    )
    match = re.search(pattern, file_name, re.IGNORECASE)

    if not match:
        return ""
    if match.group("ppv"):
        return "UFC " + match.group("ppv")
    if match.group("fnight"):
        return "UFC Fight Night " + match.group("fnight")
    if match.group("ufc_on"):
        return "UFC on " + match.group("ufc_on").upper()
    return ""


def get_fighter_names(file_name: str) -> str:
    """
    Extracts the fighter names from a video file name.

    Returns a string of the fighter names found or if no names are found, returns "".

    :param file_name: The file name
    :type file_name: str
    :return: The extracted names or empty string if no names are found.
    :rtype: str
    """

    # This is a delicate baby
    pattern = (
        r"(?:(?<= )|(?<=^))"  # lookbehind for start of string or space
        r"(?P<name1>(?:(?!ppv|main|event|prelim|preliminary)[a-z-]+ )+)"
        #      can add more words to exclude in the start ^
        r"vs ?"  # or the end of the names v
        r"(?P<name2>(?:(?!ppv|main|prelim|early|web)[a-z-]+(?: |$))+)"
        r"(?:(?![0-9]{2,})(?P<num>[0-9]))?"  # optional rematch number
    )

    match = re.search(pattern, file_name, re.IGNORECASE)

    if not match:
        return ""

    return (
        match.group("name1").strip().title()
        + " vs "
        + match.group("name2").strip().title()
        + (f" {match.group('num')}" if match.group("num") else "")
    )


def get_edition(file_name: str) -> Edition:
    """
    Extracts the edition from a video file name.

    Returns a string of the edition. Defaults to "Main Event".

    :param file_name: The file name
    :type file_name: str
    :return: The extracted edition
    :rtype: str
    """

    pattern = r"early prelims|prelims|preliminary"
    match = re.search(pattern, file_name, re.IGNORECASE)

    edition = match.group(0).lower() if match else "main event"

    # Map string to enum
    return {
        "early prelims": Edition.EARLY_PRELIMS,
        "prelims": Edition.PRELIMS,
        "preliminary": Edition.PRELIMS,
        "main event": Edition.MAIN_EVENT,
    }.get(edition, Edition.MAIN_EVENT)


def get_resolution(file_name: str) -> str:
    """
    Extracts the resolution from a video file name. Not trying to be perfect here.

    Returns a string of the resolution and scan mode or if no resolution is
    found, returns "". 4K and UHD are treated as 2160p

    :param file_name: The file name
    :type file_name: str
    :return: The extracted resolution or "" if no resolution is found.
    :rtype: str
    """

    file_name = re.sub(r"4k|uhd", "2160p", file_name, flags=re.IGNORECASE)
    match = re.search(r"\d{3,4}[pi]", file_name, re.IGNORECASE)

    return "" if not match else match.group(0)


def find_editions(path: Path, event_number: str) -> dict[Edition, VideoInfo]:
    """
    Scans the given directory and extracts editions from the file names.

    Iterates over each file that starts with the supplied event_number in the
    specified directory, extracts information from the file name, and returns a
    dictionary mapping each edition to a VideoInfo object. If a file does not
    start with the event number or does not contain an edition, it is not
    included in the result.

    :param path: The directory path to scan for files.
    :type path: Path
    :param event_number: The event_number to filter by
    :type event_number: str
    :return: A dictionary mapping editions to VideoInfo objects.
    :rtype: dict[str, VideoInfo]
    """

    editions_in_folder: dict[Edition, VideoInfo] = {}
    for file in path.glob(f"*{event_number}*", case_sensitive=False):
        if file.is_file():
            info = VideoInfo(file, strict=False)
            if info.event_number == event_number:
                editions_in_folder[info.edition] = info

    return editions_in_folder


def find_largest_video_file(video_path: Path) -> Path | None:
    """
    Finds the largest video file in the given path.

    Valid video file extensions are defined in VIDEO_EXTENSIONS.
    If video files are found, it returns the largest one based on file size,
    because sometimes a sample video or thumbnail is included.
    If no video files are found, returns None.

    :param video_path: The path to search for video files.
    :type video_path: Path
    :return: Path of the largest video file or None if no video files are found.
    :rtype: Path | None
    """

    if not video_path.is_dir():
        return None

    video_files = [
        f
        for f in video_path.iterdir()
        if f.is_file() and f.suffix.lower() in Config.video_extensions
    ]

    if not video_files:
        return None

    return max(video_files, key=lambda f: f.stat().st_size)


def find_names(
    directory: Path = Config.destination_folder, event_number: str = ""
) -> str:
    """
    Attempts to find fighter names of a given ufc event from an existing folder.

    Searches for a folder in DESTINATION_FOLDER that starts with the event number.
    If a folder is found, it will attempt to extract the fighter names from the
    folder name. Also recursively checks inside the folder.

    This also enables a bulk rename to fix folders with missing fighter names.

    :param directory: The directory to search.
    :type directory: Path
    :param event_number: The UFC event number.
    :type event_number: str
    :return: The fighter names.
    :rtype: str
    """

    for path in directory.glob(f"*{event_number}*", case_sensitive=False):
        info = VideoInfo(path, strict=False)

        if path.is_dir() and not info.fighter_names:
            # If the folder doesn't have fighter names, check inside
            info.fighter_names = find_names(path, event_number)

        if info.fighter_names:
            return info.fighter_names

    return ""


def construct_path(file_path: Path) -> tuple[Path, VideoInfo]:
    """
    Constructs a new file path for a UFC video file based on extracted information.

    The formatting is defined in the FORMAT_X variables.
    The fighter names and resolution may be ommitted if not found in the file name.

    :param file_path: The full path to the original video file.
    :type file_path: Path
    :return: A tuple containing the new file path and a dictionary of extracted information.
    :rtype: tuple[Path, VideoInfo]
    """

    parts = [""] * len(Config.format_order)
    folder_parts = [""] * len(Config.format_order)

    """
    info = VideoInfo(file_path)
    in_subfolder = bool(Config.subfolder and info.edition != Edition.MAIN_EVENT)

    parts = []
    folder_parts = []

    for part in Config.format_order:
        if not (value := getattr(info, part)):
            continue

        if isinstance(value, Edition):
            value = value.value if in_subfolder else f"edition-{value.value}"

        # Add to Main folder name
        if part in Config.format_folder:
            folder_parts.append(value)

        # Limit subfolder filename parts
        if in_subfolder and part not in Config.format_subfolder:
            continue

        # Add brackets if specified
        if token := Config.format_tokens.get(part):
            left, right = token.value
            value = f"{left}{value}{right}"

        # Add to filename
        parts.append(value)

    # e.g. UFC Fight Night 248 Yan vs Figueiredo
    folder_name = " ".join(folder_parts)

    if not is_valid_folder_name(folder_name):
        exit_log(f"Invalid folder name: {folder_name}", exit_code=1)

    dest = Config.destination_folder / folder_name
    if in_subfolder and Config.subfolder:
        dest /= Config.subfolder

    # e.g. UFC Fight Night 248 Yan vs Figueiredo {edition-Main Event} [1080p].mkv
    # or for subfolders: UFC Fight Night 248 Prelims
    file_name = " ".join(parts) + file_path.suffix

    return (dest / file_name), info


def is_valid_folder_name(name: str) -> bool:
    """
    Light validation for folder names:
    - No invalid characters: \\ / : * ? " < > |
    - Cannot be empty or just spaces
    - Cannot start or end with spaces

    :param name: Folder name to validate.
    :return: True if valid, False otherwise.
    """
    if not name or name.strip() != name:  # Empty/whitespace or leading/trailing spaces
        return False

    # Check for invalid characters
    if re.search(r'[\\/:*?"<>|]', name):
        return False

    return True


def not_posix() -> bool:
    """Checks if the script is not running on a POSIX system."""
    return os.name != "posix"


def parse_permissions(perm: str) -> int:
    """Validate and parse a permission string into an integer."""
    if not re.fullmatch(r"[0-7]{3,4}", perm):
        raise ValueError(f"Invalid permission value: {perm}")
    return int(perm, 8)


def get_minimum_permissions(path: Path) -> int:
    """
    Returns the minimum permissions required for a given path.

    If the path is a directory, the minimum permissions are 770.
    If the path is a file, the minimum permissions are 660.

    If the preferred permissions are higher than the minimum, that is used instead.

    :param path: The path to get minimum permissions for.
    :type path: Path
    :return: The minimum permissions required for the path.
    :rtype: int
    """

    if path.is_dir():
        # At least 770
        wanted = Config.folder_permissions & 0o777
        min_mode = stat.S_IRWXU | stat.S_IRWXG
    elif path.is_file():
        # At least 660
        wanted = Config.file_permissions & 0o777
        min_mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP
    else:
        exit_log(f"Permission check failed: {path} is not a file or directory", 1)

    return wanted | min_mode


def fix_permissions(
    path: Path, cur_stat: os.stat_result, ref_stat: os.stat_result, target: int
) -> None:
    """
    Ensures this script and the ref user can rwx to the given path.

    Fixes the permissions of a given path by setting the permissions to at least
    770. If the script is running as root, the owner will be changed to the
    owner of the reference path.

    If the permissions or owner cannot be changed, raises a PermissionError with
    a message suggesting how to fix the permissions manually.

    :param path: The path to fix permissions for.
    :type path: Path
    :param cur_stat: The current stat result of the path.
    :type cur_stat: os.stat_result
    :param ref_stat: The reference stat result.
    :type ref_stat: os.stat_result
    :param target: The target permissions to set.
    :type target: int
    :raises PermissionError: If the permissions or owner cannot be changed.
    """

    if not_posix():
        return

    ref_uid, ref_gid = ref_stat.st_uid, ref_stat.st_gid

    scr_uid = os.getuid()  # type: ignore pylint: disable=no-member
    root = bool(scr_uid == 0)

    if not root and scr_uid != cur_stat.st_uid:
        # Can't fix permissions
        raise PermissionError(
            f"Cannot fix permissions of {path} because the script is not "
            f"running as the owner or root. Try running chown manually:\n"
            f'sudo chown -R {scr_uid}:{scr_uid} "{path}"\n'
        )

    # The script is running as root or owns the path

    try:
        os.chmod(path, target)
        print(f"Changed permissions of {path} to {oct(target)}")
    except PermissionError as e:
        raise PermissionError(
            f"Failed to change permissions of {path}: {e}. "
            f"\nTry running chmod manually:\n"
            f'sudo chmod {oct(target)} "{path}"'
        ) from e
    except OSError as e:
        raise OSError(f"Failed to change permissions of {path}: {e}") from e

    if not root:
        # Done all we can
        return

    new_owner = f"{ref_uid}:{ref_gid}"
    try:
        # Changing ownership so that folders aren't owned by root
        if ref_uid != 0:
            os.chown(path, ref_uid, ref_gid)  # type: ignore pylint: disable=no-member
            print(f"Changed ownership of {path} to {ref_uid}:{ref_gid}")
    except PermissionError as e:
        raise PermissionError(
            f"Failed to change ownership of {path}: {e}. "
            f"\nTry running chown manually:\n"
            f'sudo chown -R {new_owner} "{path}"'
        ) from e


def check_permissions(path: Path, ref: os.stat_result) -> None:
    """
    Apply desired permissions to the given path and its parent directories.

    Only works on POSIX systems. Recursively checks the given path and its
    parents starting from destination_folder. If the permissions or owner
    are incorrect, they are changed to the desired values.

    Minimum permissions are 770 for folders and 660 for files. The owner is
    changed to the owner in the reference stat result.

    :param path: The file or folder to start from.
    :type path: Path
    :param ref: The reference stat object.
    :type ref: os.stat_result
    :raises OSError: If the permissions or owner must be changed but cannot be changed.
    """

    if not_posix():
        return

    if path.is_dir() and not os.access(path, os.W_OK):
        print(f"Error: {path} is not valid and writable")
        return

    if not path.is_relative_to(Config.destination_folder):
        # probably configuration error, so alert
        print(f"Error: {path} is not a child of {Config.destination_folder}")
        return

    if path.parent != Config.destination_folder:
        # start at top
        check_permissions(path.parent, ref)

    cur_stat = os.stat(path)
    target = get_minimum_permissions(path)

    if (cur_stat.st_mode & 0o777) == target:
        return

    fix_permissions(path, cur_stat, ref, target)


def move_file(src: Path, dst: Path) -> tuple[str, int]:
    """
    Moves a file from its original location to a new location.

    :param src: The full path to the original video file.
    :type src: Path
    :param dst: The full path to the new video file.
    :type dst: Path
    :return: A tuple containing a boolean indicating success and an error message.
    :rtype: tuple[str, int]
    """

    if Config.dry_run:
        return f"Moved {src} to {dst}", 0

    parent = dst.parent

    ref_stat = os.stat(Config.destination_folder)

    # Get permissions, minimum 770
    mode = get_minimum_permissions(src.parent)

    if not parent.exists():
        try:
            parent.mkdir(mode=0o770, parents=True, exist_ok=True)
            print(f"Setting permissions of {parent} to {oct(mode)}")
            os.chmod(parent, mode)
        except OSError as e:
            return f"Failed to create directory {parent}: {e}", 1

    # Get permissions, minimum 660
    mode = get_minimum_permissions(src)

    try:
        shutil.move(src, dst)
        print(f"Setting permissions of {dst} to {oct(mode)}")
        os.chmod(dst, mode)
    except shutil.Error as e:
        return f"Failed to move {src} to {dst}: {e}", 1

    try:
        check_permissions(dst, ref_stat)
    except OSError as e:
        return f"Failed permission check: {e}", 1

    return f"Moved {src} to {dst}", 0


def rename_and_move(file_path: Path) -> tuple[str, int]:
    """
    Renames and moves a UFC video file to a new directory based on extracted information.

    Moves the file to the new location under the DESTINATION_FOLDER directory. If the
    extraction is unsuccessful, an error message is printed and the script exits.

    :param file_path: The full path to the downloaded video file.
    :type file_path: Path
    :return: A tuple containing a boolean indicating success and an error message.
    :rtype: tuple[str, int]
    """

    # VideoInfo obj includes file_path, not new_path
    new_path, info = construct_path(file_path)

    if new_path.exists():
        if Config.refresh_perms:
            ref_stat = os.stat(Config.destination_folder)
            try:
                check_permissions(new_path, ref_stat)
            except OSError as e:
                print(f"Error: {e}")
        # If the new file already exists, print an error and exit
        return f"File {new_path.name} already exists in {new_path.parent}", 1

    if not new_path.parent.exists():
        # folder doesn't exist so nothing else to do
        return move_file(info.path, new_path)

    # find if an existing video file with same edition and event number exists
    existing = find_editions(new_path.parent, info.event_number)

    x_info = existing.get(info.edition)

    if x_info is None or x_info.path == file_path:
        return move_file(info.path, new_path)

    # if there is no resolution in either, the new file is preferred
    new_res = int(info.resolution[:-1] or 99999)
    old_res = int(x_info.resolution[:-1] or 0)

    if new_res == old_res or new_res > old_res:
        if new_res == old_res and not Config.replace_same_res:
            if Config.refresh_perms:
                ref_stat = os.stat(Config.destination_folder)
                try:
                    check_permissions(x_info.path, ref_stat)
                except OSError as e:
                    print(f"Error: {e}")
            return (
                f"File {x_info.path.name} already exists in "
                f"{new_path.parent} with the same resolution.",
                1,
            )

        if not Config.dry_run:
            try:
                x_info.path.unlink()
            except OSError as e:
                print(f"Error deleting file: {e}")

        print(f"Replacing {x_info.path.name} with {new_path.name}")

        return move_file(info.path, new_path)

    if Config.refresh_perms:
        ref_stat = os.stat(Config.destination_folder)
        try:
            check_permissions(x_info.path, ref_stat)
        except OSError as e:
            print(f"Error: {e}")

    # If the existing file has a higher resolution, error
    return (
        f"File {x_info.path.name} already exists in "
        f"{new_path.parent} with a higher resolution.",
        1,
    )


def bulk_rename(
    directory: Path = Config.destination_folder,
    remove_empty: bool = False,
    in_ufc_folder: bool = False,
) -> int:
    """
    Recursively renames and moves files in the directory.

    Param in_ufc_folder is used to skip the event number check for recursive
    calls. Can be set to True to avoid the check.

    If remove_empty is True, empty folders will be removed after renaming.
    This is useful for re-organization of existing files and should be run
    after changing the formatting configuration.

    NOTE: This function is recursive and can be destructive.

    :param directory: The directory to rename files in.
    :type directory: Path
    :param remove_empty: Whether to remove empty folders after renaming.
    :type remove_empty: bool
    :param in_ufc_folder: If directory is a UFC folder.
    :type in_ufc_folder: bool
    :return: 0 if successful, 1 or more if an error occurs or a file wasn't moved.
    :rtype: int
    """

    res = 0

    print(f"Renaming files in {directory}")

    for entry in os.scandir(directory):
        path = Path(entry.path)
        if path.name.startswith("."):
            # skip hidden
            continue

        if not in_ufc_folder and not get_event_number(path.name):
            # Checks if the folder has an event number. This check is skipped
            # if we're already in a UFC folder
            continue

        subres = 0

        if path.is_dir():
            subres = bulk_rename(path, remove_empty, in_ufc_folder=True)

            if not subres and remove_empty and not any(path.iterdir()):
                if Config.dry_run:
                    print(f"Removing empty folder {path}")
                else:
                    try:
                        path.rmdir()
                        print(f"Removed empty folder {path}")
                    except OSError as e:
                        print(f"Error deleting folder: {e}")

        elif path.is_file() and path.suffix.lower() in Config.video_extensions:
            message, exit_code = rename_and_move(path)

            print("DNF: " + message if exit_code else message)

            subres = exit_code

        res += subres

    return res


def parse_args():
    """
    Parses command line arguments. Only called if sys.argv[1] is not a directory.

    Mostly made this for re-organization of existing files. Can use arguments
    to run manually. Quick run: python ufc.py -d /path/to/downloaded/folder

    :return: The folder containing the video files.
    :rtype: any
    """

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d",
        "--dir",
        default=Config.destination_folder,
        help="The directory containing the video files to be processed",
    )
    parser.add_argument(
        "-c",
        "--category",
        help=(
            "The category of the download. If it matches UFC_CATEGORY, "
            "STRICT_MATCHING will be set to True"
        ),
    )
    parser.add_argument(
        "-D", "--dest", help="The destination folder for the renamed files"
    )
    parser.add_argument(
        "-r",
        "--replace-same-res",
        action="store_true",
        help="Replace existing files with the same resolution in the name",
    )
    parser.add_argument(
        "-s",
        "--strict-matching",
        action="store_true",
        help="Fail if the event number cannot be found in the file name",
    )
    parser.add_argument(
        "--rename-all",
        action="store_true",
        help="Rename all UFC folders and files in the directory. Use with caution.",
    )
    parser.add_argument(
        "--remove-empty",
        action="store_true",
        help="Remove empty folders after renaming.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print out the new filenames without actually moving the files.",
    )
    parser.add_argument(
        "--refresh-perms", action="store_true", help="Run a check on all permissions."
    )
    args = parser.parse_args()

    if args.dest:
        Config.update(destination_folder=Path(args.dest))

    if args.replace_same_res:
        Config.update(replace_same_res=True)

    if args.strict_matching or args.category == Config.ufc_category:
        Config.update(strict_matching=True)

    if args.dry_run:
        Config.update(dry_run=True)

    if args.refresh_perms:
        Config.update(refresh_perms=True)

    try:
        directory = check_path(args.dir)
        if not directory:
            exit_log("Invalid starting directory.", exit_code=1)
    except NotADirectoryError as e:
        exit_log(f"Invalid starting directory: {e}", exit_code=1)

    if not args.rename_all:
        return directory

    bulk_rename(directory, args.remove_empty)
    exit_log("Done.", exit_code=0)


def main() -> None:
    """
    Main function.

    If it is called by SABnzbd, the environment variables 'SAB_COMPLETE_DIR'
    and 'SAB_CAT' will be set.

    The script will filter the files in the directory to find the largest video file,
    and then attempt to rename and move it to the specified destination folder.

    If the video file is successfully moved, the script will exit with 0.
    If there is an error, the script will exit with 1.

    :return: None
    """

    if len(sys.argv) == 1:
        exit_log("Not enough arguments.", exit_code=1)

    try:
        Config.load_from_ini(INI_PATH)
    except (FileNotFoundError, ValueError) as e:
        exit_log(f"Failed to load configuration: {e}", exit_code=1)

    directory, category = check_path(sys.argv[1], False), None

    if len(sys.argv) == 2 and directory:
        # only a job path is provided
        directory = sys.argv[1]

    elif os.getenv("SAB_COMPLETE_DIR") and os.getenv("SAB_CAT"):
        # running from SABnzbd
        # Print newlines so the 'more' button is available in sabnzbd
        print("\n\n")
        directory = os.getenv("SAB_COMPLETE_DIR")
        category = os.getenv("SAB_CAT")

        if not directory or not category:
            exit_log("SAB_COMPLETE_DIR or SAB_CAT not set.", exit_code=1)

    else:
        # running manually
        directory = parse_args()

    try:
        directory = check_path(directory)
        if not directory:
            raise NotADirectoryError(directory)
    except NotADirectoryError as e:
        exit_log(f"Invalid job directory: {e}", exit_code=1)

    if category == Config.ufc_category:
        Config.update(strict_matching=True)

    # Filter video files
    video_file = find_largest_video_file(directory)

    if not video_file:
        exit_log("No video files found.", exit_code=1)

    exit_log(*rename_and_move(video_file))


main()

sys.exit(0)
