"""SABnzbd post-processing script to organize UFC videos by event.

Extracts event number, fighter names, and edition (Early Prelims/Prelims/Main Event)
from filenames. Creates folders and moves files with consistent naming for Plex.

The script:
- Parses UFC filenames for metadata, falls back to folder names if obfuscated
- Creates folders and optional subfolders with consistent format (configurable)
- Moves and renames files accordingly
- Handles multiple editions via Plex edition tags
"""

import os
import re
import sys
import shutil
import argparse
from enum import Enum
from pathlib import Path
from dataclasses import dataclass
from configparser import ConfigParser
from typing import NoReturn, ClassVar

# Define the configuration file path. Defaults to ufc.ini in the script directory.
# This will fallback to ufc.ini.template if the given path does not exist.
# INI_PATH = Path("/path/to/ini")
INI_PATH = Path(__file__).parent / "ufc.ini"


class Bracket(Enum):
    """Enum for bracket types."""

    SQUARE = ("[", "]")
    CURLY = ("{", "}")
    ROUND = ("(", ")")

    def surround(self, text: str) -> str:
        """Surround the given text with the bracket."""
        left, right = self.value
        return f"{left}{text}{right}"


class Edition(Enum):
    """Enum for UFC event editions."""

    EARLY_PRELIMS = "Early Prelims"
    PRELIMS = "Prelims"
    MAIN_EVENT = "Main Event"

    def __str__(self) -> str:
        return self.value


class UFCAttr(Enum):
    """Enum for UFC event attributes."""

    EVENT_NUMBER = "event_number"
    FIGHTER_NAMES = "fighter_names"
    EDITION = "edition"
    RESOLUTION = "resolution"

    def __str__(self) -> str:
        return self.value


class UFCRegex(Enum):
    """Enum for regex patterns used to extract UFC event attributes."""

    EVENT_NUMBER = (
        r"ufc ?(?P<ppv>\d+)"
        r"|ufc ?fight ?night (?P<fnight>\d+)"
        r"|ufc ?on ?(?P<ufc_on>\w+ \d+)"
    )
    FIGHTER_NAMES = (
        r"(?:(?<= )|(?<=^))[{[(]?"
        r"(?P<name1>(?:(?!ppv|main|event|prelim|preliminary)[a-z-]+ )+)"
        r"vs(?P<name2>(?:(?: )?(?!ppv|main|prelim|early|web)[a-z-]+)+)"
        r"(?: ?(?![0-9]{2,})(?P<num>[0-9]))?[}\])]?"
    )
    EDITION = r"early prelims|prelims|preliminary"

    def __str__(self) -> str:
        return self.value


@dataclass
class Config:
    """Configuration settings for the UFC file controller.

    Attributes:
        destination_folder: Root folder for UFC videos.
        subfolder: Name of subfolder for non-main events.
        ufc_category: Category name for UFC downloads.
        strict_matching: Whether to enforce strict name matching.
        replace_same_res: Whether to replace files with same resolution.
        dry_run: Whether to simulate operations without changes.
        video_extensions: Valid video file extensions.
        file_permissions: Default file permissions.
        folder_permissions: Default folder permissions.
        format_order: Order of parts in formatted path names.
        format_tokens: Bracket style for each part.
        format_folder: Parts to include in folder names.
        format_subfolder: Parts to include in filenames inside subfolders.
        refresh_perms: Whether to check and fix permissions aggressively.
    """

    # The following docstrings are for hints in IDEs, not for documentation
    destination_folder: ClassVar[Path]
    """Root folder for UFC videos"""
    subfolder: ClassVar[str | None]
    """Name of subfolder for non-main events"""
    ufc_category: ClassVar[str]
    """Category name for UFC downloads"""
    strict_matching: ClassVar[bool]
    """Whether to enforce strict name matching"""
    replace_same_res: ClassVar[bool]
    """Whether to replace files with same resolution"""
    dry_run: ClassVar[bool]
    """Whether to simulate operations without changes"""
    video_extensions: ClassVar[set[str]]
    """Valid video file extensions"""
    file_permissions: ClassVar[int]
    """Default file permissions"""
    folder_permissions: ClassVar[int]
    """Default folder permissions"""
    format_order: ClassVar[list[str]]
    """Order of parts in fomatted path names"""
    format_tokens: ClassVar[dict[str, "Bracket"]]
    """Bracket style for each part"""
    format_folder: ClassVar[set[str]]
    """Parts to include in folder names"""
    format_subfolder: ClassVar[set[str]]
    """Parts to include in filenames inside subfolders"""
    refresh_perms: ClassVar[bool]
    """Whether to check and fix permissions aggressively"""

    @classmethod
    def update(cls, **kwargs) -> None:
        """Update config values"""
        for key, value in kwargs.items():
            if hasattr(cls, key):
                setattr(cls, key, value)

    @classmethod
    def load_from_ini(cls, path: Path) -> None:
        """Load configuration settings from an INI file.

        Reads the INI file and updates class config variables. Validates all sections
        and keys before applying changes.

        Args:
            path (Path): Path to the INI configuration file

        Raises:
            FileNotFoundError: If both the config file and template are missing
            ValueError: If validation fails due to missing/invalid sections/keys
        """
        config = ConfigParser(allow_no_value=True)
        cls._read_config_file(config, path)
        cls._validate_keys(config)
        cls._validate_format_parts(config)
        cls._load_paths(config)
        cls._load_categories(config)
        cls._load_file_handling(config)
        cls._load_format_settings(config)

    @classmethod
    def _read_config_file(cls, config: ConfigParser, path: Path) -> None:
        """Read the configuration file or template."""
        if path.exists():
            config.read(path)
        else:
            if not (template := Path(__file__).parent / "ufc.ini.template").exists():
                raise FileNotFoundError("No config file or template found")
            config.read(template)
            print(f"Warning: INI not found. Using template config: {template}")

    @classmethod
    def _load_paths(cls, config: ConfigParser) -> None:
        """Load path settings from the configuration."""
        cls.destination_folder = Path(config["Paths"]["destination_folder"])
        subfolder = config["Paths"]["subfolder"]
        if subfolder.lower() in ("none", "", "null"):
            subfolder = None
        elif not is_valid_folder_name(subfolder):
            raise ValueError(f'Invalid folder name: "{subfolder}"')
        cls.subfolder = subfolder

    @classmethod
    def _load_categories(cls, config: ConfigParser) -> None:
        """Load category settings from the configuration."""
        cls.ufc_category = config["Categories"]["ufc_category"]
        cls.strict_matching = config["Categories"].getboolean("strict_matching")

    @classmethod
    def _load_file_handling(cls, config: ConfigParser) -> None:
        """Load file handling settings from the configuration."""
        section = config["FileHandling"]
        cls.replace_same_res = section.getboolean("replace_same_res")
        cls.dry_run = section.getboolean("dry_run", cls.dry_run)
        cls.video_extensions = set(
            ext.strip().lower() for ext in section["video_extensions"].split(",")
        )
        cls.file_permissions = cls.parse_permissions(section["file_permissions"])
        cls.folder_permissions = cls.parse_permissions(section["folder_permissions"])

    @classmethod
    def _load_format_settings(cls, config: ConfigParser) -> None:
        """Load format settings from the configuration."""
        cls.format_order = cls._get_ordered_parts(config)
        cls.format_tokens = cls._get_format_tokens(config)
        cls.format_folder = set(config["Format.Folder"]["parts"].split(","))
        cls.format_subfolder = set(config["Format.Subfolder"]["parts"].split(","))

    @classmethod
    def _get_ordered_parts(cls, config: ConfigParser) -> list[str]:
        """Get ordered parts from the configuration."""
        section = config["Format.Order"]
        ordered_parts = [
            key
            for key, _ in sorted(
                ((key, value) for key, value in section.items() if value.isdigit()),
                key=lambda item: item[1],
            )
        ]
        if str(UFCAttr.EVENT_NUMBER) not in ordered_parts:
            raise ValueError("Format.Order must contain 'event_number'.")
        if len(ordered_parts) < 2:
            raise ValueError("Format.Order must contain at least 2 parts.")
        if len(ordered_parts) != len(set(ordered_parts)):
            raise ValueError("Format.Order contains duplicate parts.")
        return ordered_parts

    @classmethod
    def _get_format_tokens(cls, config: ConfigParser) -> dict[str, Bracket]:
        """Get format tokens from the configuration."""
        format_tokens = {}
        for key, value in config["Format.Brackets"].items():
            if hasattr(Bracket, value.upper()):
                format_tokens[key] = Bracket[value.upper()]
            else:
                raise ValueError(f"Invalid bracket type: {value}")
        return format_tokens

    @classmethod
    def _validate_keys(cls, config: ConfigParser) -> None:
        """Confirm all section and keys in INI file exist."""
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

    @classmethod
    def _validate_format_parts(cls, config: ConfigParser) -> None:
        """Validate format parts against VideoInfo fields."""
        format_parts = set(str(x) for x in UFCAttr)
        # Format parts must match VideoInfo fields
        errors = []
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

    @classmethod
    def parse_permissions(cls, perm: str) -> int:
        """Validate and parse a permission string into an integer.

        Converts Unix-style file permissions from either symbolic (rwxrw-r--) or
        octal (755) format into their integer representation.

        Args:
            perm: The permission string to parse.

        Returns:
            The permissions as an integer in octal format.

        Raises:
            ValueError: If the permission string is invalid or doesn't match either format.
        """
        if not re.fullmatch(r"^(?:0?[0-7]{3}|(?:[r-][w-][x-]){3})$", perm):
            raise ValueError(f"Invalid permission value: {perm}")

        if perm.isdigit():
            return int(perm, 8)

        char_to_bit = {"r": 4, "w": 2, "x": 1, "-": 0}
        result = 0
        for i in range(0, 9, 3):
            value = sum(char_to_bit[c] for c in perm[i : i + 3])
            result = (result << 3) | value

        return result

    @classmethod
    def get_permissions(cls, path: Path) -> int:
        """Returns the minimum permissions required for a given path.

        - Directories: minimum 770 (rwxrwx---)
        - Files: minimum 660 (rw-rw----)

        Plus any additional permissions from ini.

        Args:
            path: The path to check.

        Returns:
            The permissions in octal required for the path.
        """
        if path.is_dir():
            return cls.folder_permissions | 0o770
        if path.is_file():
            return cls.file_permissions | 0o660
        exit_log(f"Permission check failed: {path} is not a file or directory", 1)


@dataclass(frozen=True)
class VideoInfo:
    """Defines video information extracted from the file name."""

    event_number: str = ""
    """The UFC event number e.g. UFC 248"""
    fighter_names: str = ""
    """The fighter names e.g. Yan vs Figueiredo 2"""
    edition: Edition = Edition.MAIN_EVENT
    """The UFC event edition as an Enum"""
    resolution: str = ""
    """The video resolution e.g. 1080p"""
    path: Path = Path("")
    """The full path to the source video file"""
    _name: str = ""
    """The original file (or folder) name"""
    _strict: bool = True
    """Whether to enforce strict name matching"""

    def __init__(self, path: Path, strict: bool = True) -> None:
        """Extracts and assigns information from a UFC video file name.

        Args:
            path: Path of the file to extract information from
            strict: Whether to  attempt to find missing info in other folders

        Extracts the event number, fighter names, edition and resolution from
        the filename. With strict=True, will try harder to find info and fail
        on errors. If strict_matching is false, will silently exit on errors.

        Raises:
            SystemExit: If required info cannot be found in strict mode
        """

        if not path.exists():
            exit_log(f"File {path} does not exist", exit_code=1)

        object.__setattr__(self, "path", path)
        object.__setattr__(self, "_strict", strict)
        # Unify separators to spaces to make regex patterns less ungodly
        name = re.sub(r"[\.\s_]", " ", path.name)

        if not (event_number := self.get_event_number(name)) and path.is_file():
            # Check folder name and reassign name for further parsing
            name = re.sub(r"[\.\s_]", " ", path.parent.name)
            event_number = self.get_event_number(name)
        object.__setattr__(self, "event_number", event_number)
        object.__setattr__(self, "_name", name)

        self.set_fighter_names()
        if not self.fighter_names and self._strict:
            self.find_names()

        self.set_edition()
        self.set_resolution()

    def __post_init__(self):
        """Post-initialization method to validate extracted information."""
        if not self.event_number and self._strict:
            if Config.strict_matching:
                exit_log(
                    f"Unable to extract UFC event number from {self.path}", exit_code=1
                )
            else:
                exit_log(exit_code=0)

    @staticmethod
    def get_event_number(name: str) -> str:
        """Extracts the event number from a string.

        Args:
            name: The string to search in.

        Returns:
            The extracted event number including the event type (UFC, Fight Night, etc.),
            or `""` if no event number is found.
        """
        # there are also 'UFC Live' events which will not be caught, but they usually
        # don't have a number anyway.
        event_fmt = {
            "ppv": lambda m: f"UFC {m}",
            "fnight": lambda m: f"UFC Fight Night {m}",
            "ufc_on": lambda m: f"UFC on {m.upper()}",
        }

        if match := re.search(UFCRegex.EVENT_NUMBER.value, name, re.I):
            group = match.lastgroup
            return event_fmt[group](match.group(group)) if group else ""
        return ""

    def set_fighter_names(self, name: str | None = None) -> None:
        """Assigns fighter names from a video file name.

        Args:
            name: The string to search in.
        """
        if match := re.search(
            UFCRegex.FIGHTER_NAMES.value, name or self.path.name, re.I
        ):
            name1 = match.group("name1").strip().title()
            name2 = match.group("name2").strip().title()
            num = match.group("num")
            object.__setattr__(
                self, "fighter_names", f"{name1} vs {name2}{f' {num}' if num else ''}"
            )

    def find_names(self, directory: Path | None = None) -> None:
        """Attempts to find and set fighter names from existing folders.

        Recursively searches the directory for matches of `event_number`. This also
        enables a bulk rename to fix folders with missing fighter names.
        """
        directory = directory or Config.destination_folder
        for path in directory.glob(f"*{self.event_number}*", case_sensitive=False):
            self.set_fighter_names(path.name)

            if path.is_dir() and not self.fighter_names:
                self.find_names(path)

            if self.fighter_names:
                break

    def set_edition(self) -> None:
        """Sets the edition from `_name`.

        Assigns a value from the Edition enum based on extracted edition type.
        If no edition is detected in the filename, assigns Edition.MAIN_EVENT as default.
        """
        match = re.search(UFCRegex.EDITION.value, self._name, re.I)

        # Map match to enum
        edition = {
            "early prelims": Edition.EARLY_PRELIMS,
            "prelims": Edition.PRELIMS,
            "preliminary": Edition.PRELIMS,
        }.get(match.group(0).lower() if match else "", Edition.MAIN_EVENT)
        object.__setattr__(self, "edition", edition)

    def set_resolution(self) -> None:
        """Sets the resolution extracted from `_name`.

        Normalizes different resolution formats to a consistent string.
        Converts 4K/UHD to 2160p. Looks for resolution with scan mode (p/i)
        and sets empty string if no resolution found.
        """
        name = re.sub(r"4k|uhd", "2160p", self._name, flags=re.I)
        if match := re.search(r"\d{3,4}[pi]", name, re.I):
            object.__setattr__(self, "resolution", match.group(0).lower())

    def construct_path(self) -> Path:
        """Constructs a new file path, conforming to configured fomatting rules.

        Returns:
            A new file path following the configured format rules.
        """
        in_subfolder = bool(Config.subfolder and self.edition != Edition.MAIN_EVENT)

        parts = []
        folder_parts = []

        for part in Config.format_order:
            if not (value := getattr(self, part)):
                continue

            if isinstance(value, Edition):
                value = str(value) if in_subfolder else f"edition-{value}"

            # Add to folder name
            if part in Config.format_folder:
                folder_parts.append(value)

            # Limit subfolder filename parts
            if in_subfolder and part not in Config.format_subfolder:
                continue

            # Add brackets if specified
            if token := Config.format_tokens.get(part):
                value = token.surround(value)

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
        # or for subfolders: UFC Fight Night 248 {Prelims}.mkv
        file_name = " ".join(parts) + self.path.suffix

        return dest / file_name


def exit_log(message: str = "", exit_code: int = 1) -> NoReturn:
    """Logs a message and exits the program with the specified exit code.

    Args:
        message: The message to be logged before exiting.
        exit_code: The exit code to be used when terminating the program.

    Returns:
        NoReturn

    Raises:
        SystemExit: Exits the program with the specified exit code.
    """
    print(f"Error: {message}" if exit_code else message)
    sys.exit(exit_code)


def check_path(path: object, error: bool = True) -> Path | None:
    """Checks if the given path exists and is a directory.

    Args:
        path: The path to check. Must be a string or Path object.
        error: If True, raises an error if `path` is not a directory.

    Returns:
        The Path object of the given directory if it is an existing directory,
        otherwise None.

    Raises:
        TypeError: If `path` is not a string or Path object.
        NotADirectoryError: If `path` is not an existing directory.
    """
    if not isinstance(path, (str, Path)):
        if error:
            raise TypeError("Path must be a string or Path object")
        return None

    if not (directory := Path(path)).is_dir():
        if error:
            raise NotADirectoryError(
                f"Directory path '{directory}' does not exist or is not a directory"
            )
        return None

    return directory


def is_valid_folder_name(name: str) -> bool:
    """Validates folder name. Returns `True` if valid, `False` otherwise."""
    return bool(name and name.strip() == name and not re.search(r'[\\/:*?"<>|]', name))


def not_posix() -> bool:
    """Checks if the script is not running on a POSIX system."""
    return os.name != "posix"


def find_editions(path: Path, event_number: str) -> dict[Edition, VideoInfo]:
    """Scans the given directory and returns an `Edition`: `VideoInfo` map.

    Args:
        path: The directory path to scan for files.
        event_number: The event number to filter by.

    Returns:
        A dictionary mapping editions to `VideoInfo` objects.
    """
    return {
        info.edition: info
        for file in path.glob(f"*{event_number}*", case_sensitive=False)
        if file.is_file()
        and (info := VideoInfo(file, strict=False)).event_number == event_number
    }


def find_largest_video_file(video_path: Path) -> Path | None:
    """Finds the largest video file in the given path.

    Valid video file extensions returned are defined in `Config.video_extensions`.
    If no video files are found, returns `None`.

    Args:
        video_path: The path to search for video files.

    Returns:
        Path of the largest video file or `None` if no video files are found.
    """
    try:
        return max(
            (
                f
                for f in video_path.iterdir()
                if f.is_file() and f.suffix.lower() in Config.video_extensions
            ),
            key=lambda f: f.stat().st_size,
            default=None,
        )
    except (NotADirectoryError, FileNotFoundError):
        return None


def fix_permissions(
    path: Path, cur_stat: os.stat_result, ref_stat: os.stat_result, target: int
) -> None:
    """Ensures this script and the ref user can rwx to the given path.

    Fixes the permissions of a given path by setting the permissions to at least
    770. If the script is running as root, the owner will be changed to the
    owner of the reference path.

    Args:
        path: The path to fix permissions for.
        cur_stat: The current stat result of the path.
        ref_stat: The reference stat result.
        target: The target permissions to set.

    Raises:
        PermissionError: If the permissions or owner cannot be changed.
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
    """Apply permissions to a given path and its parent directories.

    Only works on POSIX systems. Recursively checks the path and its parents
    starting from destination_folder. Fixes incorrect permissions and ownership
    to match target values.

    Args:
        path: The file or folder to check.
        ref: Reference stat object to compare against.

    Raises:
        OSError: If permissions or ownership cannot be fixed.
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
    target = Config.get_permissions(path)

    if (cur_stat.st_mode & 0o777) == target:
        return

    fix_permissions(path, cur_stat, ref, target)


def move_file(src: Path, dst: Path) -> tuple[str, int]:
    """Moves a file from its original location to a new location.

    Args:
        src: The full path to the original video file.
        dst: The full path to the new video file.

    Returns:
        A tuple containing the status message and exit code (0 for success, 1 for error).
    """

    if Config.dry_run:
        return f"Moved {src} to {dst}", 0

    parent = dst.parent

    ref_stat = os.stat(Config.destination_folder)

    # Get permissions, minimum 770
    mode = Config.get_permissions(src.parent)

    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
            print(f"Setting permissions of {parent} to {oct(mode)}")
            os.chmod(parent, mode)
        except OSError as e:
            return f"Failed to create directory {parent}: {e}", 1

    # Get permissions, minimum 660
    mode = Config.get_permissions(src)

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
    """Renames and moves a UFC video file to a new directory based on extracted information.

    Args:
        file_path: The full path to the downloaded video file.

    Returns:
        A tuple containing a message indicating the result and an exit code.
    """

    # VideoInfo obj includes file_path, not new_path
    info = VideoInfo(file_path)
    new_path = info.construct_path()

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
    directory: Path,
    remove_empty: bool = False,
    in_ufc_folder: bool = False,
) -> int:
    """Recursively renames and moves files in the directory.

    Renames video files according to configured format and moves them to appropriate
    locations. Can optionally remove empty directories after processing.

    Args:
        directory: The directory to process. Defaults to Config.destination_folder.
        remove_empty: If True, removes empty folders after processing. Defaults to False.
        in_ufc_folder: Indicates if directory is already a UFC folder,
            skipping event number check. Defaults to False.

    Returns:
        0 if successful, positive integer indicating number of errors otherwise.

    Note:
        - Function operates recursively on all subdirectories.
        - Only processes files with extensions defined in `Config.video_extensions`.
        - Skips hidden files (starting with '.').
        - Can be destructive when `remove_empty=True`.
    """

    res = 0

    print(f"Renaming files in {directory}")

    for entry in os.scandir(directory):
        path = Path(entry.path)
        if path.name.startswith("."):
            # skip hidden
            continue

        if not in_ufc_folder and not VideoInfo.get_event_number(path.name):
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


def parse_args() -> object:
    """Parses command line arguments.

    Returns:
        The directory path to process if provided, otherwise None.

    Examples:
    - `python ufc.py -d /path/to/directory` # Rename and move file in the directory
    - `python ufc.py --rename-all --remove-empty` # Bulk rename all files in the directory
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
    """Main function for processing and organizing UFC video files.

    Handles both manual invocation and SABnzbd post-processing modes. When called by
    SABnzbd, uses environment variables `SAB_COMPLETE_DIR` and `SAB_CAT` to locate files.

    Flow:
    1. Finds the largest video file in the specified directory.
    2. Extracts metadata from the filename.
    3. Moves the file to a consistently named destination folder.

    Returns:
        None

    Raises:
        SystemExit: With code 0 on success, 1 on error
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
